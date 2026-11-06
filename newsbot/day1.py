"""Day 1 entry point: python -m newsbot.day1 --out out1 [--items-json items.json] [--replay-dir DIR ...]

fetch -> rule-based rank -> script (Claude Haiku + fact-check if ANTHROPIC_API_KEY, else extractive) ->
episode (TTS, 10 min) -> HLS render -> slate -> manifests -> replay pool + channel playlist -> report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

from . import episode, llm, manifest, pool as poolmod, playlist, rank, script as sm, slate
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
            items, reports = load_fixture(Path(a.items_json))
        else:
            items, reports = feedmod.fetch_all()
            reports = feedmod.reports_json(reports)
        (ep / "items.json").write_text(json.dumps({"items": [i.__dict__ for i in items], "reports": reports}, indent=1))
        print(f"{len(items)} items from {sum(1 for r in reports if r.get('ok'))} working feeds")

    with tm.stage("rank"):
        now = time.time()
        ranked = rank.rank(items, N_RUNDOWN, now)
        (ep / "rank.json").write_text(json.dumps(rank.explain(ranked, now), indent=1))
        print(f"rundown: {len(ranked)} stories from {len({i.source for i in ranked})} sources")
        if len(ranked) < 6:
            print("not enough rankable items", file=sys.stderr)
            return 2

    with tm.stage("write_script"):
        counts = sm.source_counts(items)
        sc, stats = llm.write_episode_script(ranked, counts)  # (None, ...) unless ANTHROPIC_API_KEY is set
        if sc is None:
            sc = sm.build_episode_script([sm.extractive_story(i) for i in ranked], counts, "extractive", {"llm_stats": stats})
        sc["stories"] = [s for s in sc["stories"] if len(s["sentences"]) >= 1]  # a story with nothing sayable is dropped
        # airing gate: nothing ungrounded and nothing unsourced may air
        for s in list(sc["stories"]):
            if sm.story_problems(s):
                print(f"gate: dropping story from {s['source']}: {sm.story_problems(s)}")
                sc["stories"].remove(s)
        print("script by:", sc["generated_by"], "| llm:", json.dumps(stats))

    with tm.stage("tts_and_plan"):
        tts = Tts(force_engine=a.tts or None)
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
              "feeds": reports, "replay_blocks": sum(1 for b in blocks if b["kind"] == "replay")}
    (ep / "report.json").write_text(json.dumps(report, indent=1))
    shutil.copy(ep / "report.json", out / "report.json")
    print("REPORT", json.dumps({k: report[k] for k in ("stage_seconds", "total_seconds", "episode_seconds", "audit", "llm")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
