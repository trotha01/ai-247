"""Hourly planner (newsbot/hourly.py): aired-URL memory from per-bulletin manifests, ordering (never aired first),
dealing into slices with per-source caps, shortfall handling, fixture files newsbot.day1 can read, job summary."""
import io
import json
import time
from pathlib import Path

from newsbot import feeds, hourly, rank
from newsbot.pipeline import load_fixture

NOW = 1_800_000_000.0


def mk(source, title, url, age_h=1.0, summary=None):
    return feeds.Item(source, title, summary or ("Sentence one about " + title + " with sixty plus characters of text. Second sentence here."),
                      url, "2026-11-06", NOW - age_h * 3600)


def many(n_per_source=12, sources=("OpenAI", "Google AI", "Hugging Face", "NVIDIA Developer", "arXiv cs.AI", "Microsoft Research", "Claude Code releases", "Google DeepMind")):
    out = []
    for si, s in enumerate(sources):
        for i in range(n_per_source):
            words = " ".join(f"w{si}x{i}y{t}" for t in range(5))  # distinct tokens per item: no near-duplicate titles
            out.append(mk(s, f"{s} item {i}: {words}", f"https://x.test/{s.replace(' ', '')}/{i}", age_h=i + 1))
    return out


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def list_objects_v2(self, Bucket, Prefix, Delimiter=None, ContinuationToken=None):
        keys = [k for k in sorted(self.objects) if k.startswith(Prefix)]
        if Delimiter is None:
            return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}
        # a delimiter listing returns the objects directly under Prefix and the common prefixes one level down
        pre = sorted({Prefix + k[len(Prefix):].split(Delimiter)[0] + Delimiter for k in keys if Delimiter in k[len(Prefix):]})
        return {"Contents": [{"Key": k} for k in keys if Delimiter not in k[len(Prefix):]],
                "CommonPrefixes": [{"Prefix": p} for p in pre], "IsTruncated": False}

    def get_object(self, Bucket, Key):
        if Key == "bulletins/20261106T130000Z-01/manifest.json":
            raise RuntimeError("boom")  # an unreadable manifest is skipped, not fatal
        return {"Body": io.BytesIO(json.dumps(self.objects[Key]).encode())}


def test_aired_urls_newest_airing_wins_and_errors_are_reported():
    s3 = FakeS3({
        "bulletins/20261106T120000Z/manifest.json": {"sources": [{"url": "https://x.test/a"}, {"url": "https://x.test/b"}]},
        "bulletins/20261106T120000Z/seg_000.ts": {},
        "bulletins/20261106T130000Z-00/manifest.json": {"sources": [{"url": "https://x.test/b"}, {"url": "https://x.test/c"}]},
        "bulletins/20261106T130000Z-01/manifest.json": {"sources": [{"url": "https://x.test/z"}]},
        "bulletins/20261106T130000Z-00/slate/manifest.json": {"segments": []},  # not a bulletin manifest (deeper key)
    })
    assert hourly.bulletin_manifest_keys(s3, "bkt") == ["bulletins/20261106T130000Z-01/manifest.json", "bulletins/20261106T130000Z-00/manifest.json", "bulletins/20261106T120000Z/manifest.json"]
    aired, rep = hourly.aired_urls(s3, "bkt")
    assert aired == {"https://x.test/a": "20261106T120000Z", "https://x.test/b": "20261106T130000Z-00", "https://x.test/c": "20261106T130000Z-00"}
    assert rep["ok"] and rep["manifests_read"] == 2 and rep["urls"] == 3

    class Broken:
        def list_objects_v2(self, **kw):
            raise RuntimeError("no network")
    aired, rep = hourly.aired_urls(Broken(), "bkt")
    assert aired == {} and not rep["ok"] and "no network" in rep["error"]


def test_candidates_dedupe_and_never_aired_first_then_oldest_airing():
    items = many(4)
    dup = mk("OpenAI", "other title entirely", "https://x.test/OpenAI/0", age_h=0.1)  # same URL -> dropped
    near = mk("Hugging Face", items[0].title + " again", "https://x.test/other/near", age_h=0.1)  # near-identical title -> dropped
    thin = mk("OpenAI", "thin", "https://x.test/thin", summary="too short")
    aired = {"https://x.test/OpenAI/0": "20261106T140000Z", "https://x.test/GoogleAI/0": "20261106T120000Z"}
    c = hourly.candidates(items + [dup, near, thin], NOW, aired)
    urls = [i.url for i in c]
    assert len(urls) == len(set(urls)) and "https://x.test/thin" not in urls and "https://x.test/other/near" not in urls
    assert urls[-2:] == ["https://x.test/GoogleAI/0", "https://x.test/OpenAI/0"]  # aired last, the one aired longest ago first
    assert all(u not in aired for u in urls[:-2])
    assert rank.score(c[0], NOW) >= rank.score(c[1], NOW)  # never-aired block in score order


def test_deal_balances_slices_and_caps_sources():
    cands = hourly.candidates(many(12), NOW, {})
    dealt = hourly.deal(cands, 6, per_slice=14, max_per_source=4)
    assert [len(s) for s in dealt] == [14] * 6
    for s in dealt:
        counts = {}
        for i in s:
            counts[i.source] = counts.get(i.source, 0) + 1
        assert max(counts.values()) <= 4 and len(counts) >= 4
    assert len({i.url for s in dealt for i in s}) == 84  # no item in two slices


def test_plan_shrinks_when_supply_is_short_and_writes_fixtures_day1_can_read(tmp_path):
    items = many(2)  # 16 items -> 2 slices of 8
    p = hourly.plan(items, [{"name": "OpenAI", "ok": True, "items": 2}], NOW, {}, slices=6)
    assert p["slices"] == 2 and p["slices_wanted"] == 6 and "only 16 candidate" in p["shortfall"]
    assert [s["items"] for s in p["slice_report"]] == [8, 8]
    hourly.write_plan(p, tmp_path)
    assert json.loads((tmp_path / "slices.json").read_text()) == [0, 1]
    got, reports = load_fixture(tmp_path / "slice_1.json")
    assert len(got) == 8 and isinstance(got[0], feeds.Item) and reports[0]["name"] == "OpenAI"
    rep = json.loads((tmp_path / "plan.json").read_text())
    assert "slice_items" not in rep and rep["run_ts"].endswith("Z") and rep["candidates"] == 16


def test_plan_full_supply_gives_six_slices_with_fresh_stories_spread(tmp_path):
    items = many(12)
    aired = {i.url: "20261106T120000Z" for i in items[:60]}  # 60 of 96 aired before
    p = hourly.plan(items, [], NOW, aired, slices=6)
    assert p["slices"] == 6 and p["shortfall"] is None and p["never_aired"] == 36
    assert all(5 <= s["never_aired"] <= 7 for s in p["slice_report"])  # the 36 fresh stories are dealt round-robin


def test_summary_markdown_reports_footage_cost_and_shortfall(tmp_path):
    plan_dir = tmp_path / "plan"
    p = hourly.plan(many(3), [{"name": "OpenAI", "ok": True, "robots": "allowed", "items": 3, "note": ""}], NOW, {}, slices=6)
    p["aired_store"] = {"ok": False, "error": "R2 secrets not set"}
    hourly.write_plan(p, plan_dir)
    dirs = []
    for j in range(2):
        d = tmp_path / f"bulletin-{j}"
        d.mkdir()
        (d / "report.json").write_text(json.dumps({"episode_seconds": 600.0, "segments": 100, "rundown_stories": 10, "rundown_sources": ["a", "b"],
                                                   "audit": {"aired_sentences": 25, "supported_pct": 100.0}, "script_by": "extractive",
                                                   "llm": {"used": j == 0, "cost_usd_estimate": 0.0047}, "total_seconds": 400}))
        dirs.append(d)
    (dirs[0] / "publish.json").write_text(json.dumps({"prefix": "bulletins/X-00", "fresh_blocks": 2, "objects": 212, "bytes": 1, "cycle_start_k": 5,
                                                      "loop_from": 2, "fresh_minutes": 20.0, "blocks": [["bulletin", "X-00", 100], ["bulletin", "X-01", 100], ["slate", "s", 5]],
                                                      "inherited_blocks": 0}))
    md = hourly.summary_markdown(plan_dir, dirs)
    assert "**20.0 min of new footage rendered**" in md and "below the 60-minute hourly target" in md
    assert "0.0047 USD" in md and "`bulletins/X-00`" in md and "| OpenAI | True |" in md
    assert "only 24 candidate" in md
