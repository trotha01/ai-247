"""Day 1 entry point: python -m newsbot.day1 --out out1 [--items-json items.json] [--replay-dir DIR ...]

fetch -> topic research (pick topic, read primary sources, plan; docs/TOPICS.md) -> rule-based rank (fallback) ->
script (Claude Haiku + fact-check if ANTHROPIC_API_KEY, else extractive) -> episode (TTS, 10 min) -> HLS render ->
slate -> manifests -> replay pool + channel playlist -> report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import episode, llm, manifest, pool as poolmod, playlist, rank, script as sm, slate, topics
from . import feeds as feedmod
from .pipeline import Timer, load_fixture, sysinfo
from .render import run
from .tts import Tts

N_RUNDOWN = 12


def slate_manifest(d: Path) -> dict:
    segs = []
    for i, p in enumerate(sorted(d.glob("slate_*.ts"))):
        segs.append({"index": i, "file": p.name, **{k: round(v, 3) for k, v in manifest.probe_streams(p).items()},
                     "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    m = {"version": 1, "segment_seconds": 6, "segments": segs}
    (d / "manifest.json").write_text(json.dumps(m, indent=2))
    return m


def sentence_audit(script: dict) -> dict:
    """Aired-sentence accounting. 'supported' is the verdict that gated airing (checker + deterministic grounding,
    or verbatim extraction); 'grounded' re-runs the deterministic number/entity check on what actually airs."""
    total = sup = grounded = unsourced = 0
    for s in script["stories"]:
        if not (s["source"] and s["url"].startswith("http")):
            unsourced += len(s["sentences"]) + 1
        for x in s["sentences"]:
            total += 1
            sup += 1 if x.get("supported") is True else 0
            grounded += 0 if sm.sentence_problems(x["text"], s["source_text"]) else 1
    return {"aired_sentences": total, "supported": sup, "supported_pct": round(100 * sup / total, 2) if total else 0.0,
            "grounded": grounded, "grounded_pct": round(100 * grounded / total, 2) if total else 0.0,
            "unsourced_items": unsourced}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out1")
    ap.add_argument("--items-json")
    ap.add_argument("--replay-dir", action="append", default=[], help="dir holding earlier episode output(s)")
    ap.add_argument("--tts", default="")
    ap.add_argument("--target", type=float, default=episode.TARGET)
    a = ap.parse_args(argv)
    out = Path(a.out)
    ep, sl, work = out / "episode", out / "slate", Path("work1")
    for d in (ep, sl, work):
        d.mkdir(parents=True, exist_ok=True)
    tm, info = Timer(), sysinfo()
    print("runner:", json.dumps(info))

    with tm.stage("fetch_feeds"):
        if a.items_json:
            os.environ["NEWSBOT_OFFLINE"] = "1"   # fixture run: the topic stage fetches nothing either
            items, reports = load_fixture(Path(a.items_json))
        else:
            items, reports = feedmod.fetch_all()
            reports = feedmod.reports_json(reports)
        (ep / "items.json").write_text(json.dumps({"items": [i.__dict__ for i in items], "reports": reports}, indent=1))
        print(f"{len(items)} items from {sum(1 for r in reports if r.get('ok'))} working feeds")

    now = time.time()
    client, meter = llm.make_client(), llm.Meter()   # one budget for the whole run (topic calls + writer)
    with tm.stage("topic_research"):
        # docs/TOPICS.md: pick a topic, read its primary sources, plan the order; falls back to the general rundown
        tr = {"info": {"mode": "feeds", "topic": None}, "ranked": None, "counts": None, "script_extra": {}, "covered": set()}
        if topics.enabled():
            try:
                tr = topics.research_stage(items, reports, now, client, meter, ep)
                items = tr["items"]
            except llm.BudgetExceeded as e:
                print(f"topic stage: budget stop ({e}); general rundown")
            except Exception as e:   # a malformed topics.json entry or any stage bug must not darken the channel
                print(f"topic stage failed ({type(e).__name__}: {str(e)[:120]}); falling back to the general rundown")
                tr["info"]["fallback"] = f"topic stage error: {type(e).__name__}"
                (ep / "topic_pick.json").write_text(json.dumps(tr["info"], indent=1, ensure_ascii=False))
        else:
            print("topic mode off (NEWSBOT_TOPIC_MODE): general rundown")
        src_chars = topics.SOURCE_CHARS if tr["ranked"] is not None else llm.SRC_CHARS

    with tm.stage("rank"):
        ranked = tr["ranked"]
        if ranked is not None and len(ranked) < 5:   # a thin topic (forced, or sources that failed) never darkens the channel
            print(f"topic {(tr['info'].get('topic') or {}).get('id')}: only {len(ranked)} stories; falling back to the general rundown")
            tr.update({"ranked": None, "counts": None, "script_extra": {}})
            tr["info"].update({"mode": "feeds", "topic": None, "fallback": "too few topic stories"})
            (ep / "topic_pick.json").write_text(json.dumps(tr["info"], indent=1, ensure_ascii=False))
            ranked, src_chars = None, llm.SRC_CHARS
        if ranked is None:
            fresh = [i for i in items if i.url not in tr["covered"]]   # dedupe against past episodes here too
            ranked = rank.rank(fresh, N_RUNDOWN, now)
            if len(ranked) < 6:
                ranked = rank.rank(items, N_RUNDOWN, now)
            if os.environ.get("NEWSBOT_RUNDOWN_INTERLEAVE") == "1":
                # hourly slices (per-source cap 4): round-robin by source so the stories that fit the 10 minutes
                # (the first 8-9) come from as many sources as the slice has, not 4 + 4 + 1 (run 42298386727)
                ranked = rank.interleave_sources(ranked)
        (ep / "rank.json").write_text(json.dumps(rank.explain(ranked, now), indent=1))
        print(f"rundown: {len(ranked)} stories from {len({i.source for i in ranked})} sources; topic: {tr['info'].get('topic')}")
        # topic mode may air 5 stories (min_items); the general rundown needs 6. After the fallback above tr["ranked"] is None.
        if len(ranked) < (5 if tr["ranked"] is not None else 6):
            print("not enough rankable items", file=sys.stderr)
            return 2

    with tm.stage("write_script"):
        counts = tr["counts"] or sm.source_counts(items)
        sc, stats = llm.write_episode_script(ranked, counts, client=client, meter=meter, src_chars=src_chars)  # (None, ...) without a key
        if sc is None:
            sc = sm.build_episode_script([sm.extractive_story(i) for i in ranked], counts, "extractive", {"llm_stats": stats})
        sc.update(tr["script_extra"])
        sc["topic"] = tr["info"].get("topic")
        sc["stories"] = [s for s in sc["stories"] if len(s["sentences"]) >= 1]  # a story with nothing sayable is dropped
        # airing gate: nothing ungrounded and nothing unsourced may air
        for s in list(sc["stories"]):
            if sm.story_problems(s):
                print(f"gate: dropping story from {s['source']}: {sm.story_problems(s)}")
                sc["stories"].remove(s)
        print("script by:", sc["generated_by"], "| llm:", json.dumps(stats))

    with tm.stage("discovery"):
        # Discovery lane after the writer (docs/TOPICS.md): one web-searching Fable call; a budget stop here costs
        # nothing that airs. Applied to topics/topics.json by `newsbot.topics record` after the publish step.
        disc = {"accepted": False, "reason": "topic mode off"}
        if topics.enabled():
            disc = topics.discover_stage(items, now, client, meter, ep)
        stats.update({"cost_usd_estimate": round(meter.usd, 5), "api_calls": meter.calls, "tokens_in": meter.tokens_in,
                      "tokens_out": meter.tokens_out, "cost_by_kind": dict(meter.by_kind), "web_searches": getattr(meter, "searches", 0)}
                     if stats.get("used") else {})
        print("discovery:", json.dumps({k: v for k, v in disc.items() if k != "entry"}))

    with tm.stage("tts_and_plan"):
        tts = Tts(force_engine=a.tts or None)
        tts.speed = 0.92  # slightly unhurried news pace; also fills the 10 minutes with speech instead of standby
        print("tts engine:", tts.engine)
        scenes, chosen, plan_info = episode.build_episode(sc, tts, work, a.target)
        sc["stories"] = chosen  # only what airs is reported
        (ep / "script.json").write_text(json.dumps(sc, indent=1))
        (ep / "plan.json").write_text(json.dumps(episode.public_plan(scenes), indent=1))
        print("plan:", json.dumps(plan_info))

    with tm.stage("render_and_encode"):
        master = episode.make_master_audio(scenes, work)
        perf = episode.render_scenes(scenes, episode.episode_ticker(chosen), master, ep)
        print("render perf:", json.dumps(perf))

    with tm.stage("slate"):
        slate.build_slate(sl, work)
        slate_manifest(sl)

    with tm.stage("manifest_and_pool"):
        m = manifest.build_manifest(ep, sc, [])
        # one file that plays in any player (stream copy of the HLS output)
        run(["ffmpeg", "-y", "-i", str(ep / "index.m3u8"), "-c", "copy", "-bsf:a", "aac_adtstoasc", str(out / "episode.mp4")])
        replay_dirs = [Path(d) for d in a.replay_dir]
        pl = poolmod.build_pool([ep] + replay_dirs, sl)
        (out / "pool.json").write_text(json.dumps({k: v for k, v in pl.items()}, indent=1))
        blocks = poolmod.channel_blocks(pl, ep.name)
        segs, _ = playlist.cycle_layout(blocks)
        lives = [len(segs) - 3, len(segs), len(segs) + 3]  # a window spanning the wrap of the loop
        (out / "channel_example.m3u8").write_text("\n".join(playlist.channel_playlist(blocks, k) for k in lives))
        print("channel blocks:", [(b["kind"], len(b["segments"])) for b in blocks])

    audit = sentence_audit(sc)
    secs = round(sum(s["duration"] for s in m["segments"]), 3)
    report = {"runner": info, "stage_seconds": tm.stages, "total_seconds": tm.total(), "render": perf,
              "tts_engine": tts.engine, "script_by": sc["generated_by"], "llm": stats, "audit": audit,
              "episode_seconds": secs, "segments": len(m["segments"]), "plan": plan_info,
              "rundown_stories": len(chosen), "rundown_sources": sorted({s["source"] for s in chosen}),
              "feeds": reports, "replay_blocks": sum(1 for b in blocks if b["kind"] == "replay"),
              "topic": {"mode": tr["info"].get("mode"), **(tr["info"].get("topic") or {}),
                        "fetched_sources": sum(1 for f in tr["info"].get("fetches", []) if f.get("fetched")),
                        "discovery": disc.get("reason"), "discovery_accepted": disc.get("accepted"),
                        "discovery_model": disc.get("model"), "discovery_cost_usd": disc.get("cost_usd"),
                        "web_searches": disc.get("searches"),
                        "plan_model": (tr["info"].get("plan") or {}).get("model"),
                        "history": tr["info"].get("history")}}
    (ep / "report.json").write_text(json.dumps(report, indent=1))
    shutil.copy(ep / "report.json", out / "report.json")
    print("REPORT", json.dumps({k: report[k] for k in ("stage_seconds", "total_seconds", "episode_seconds", "audit", "llm", "topic")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
