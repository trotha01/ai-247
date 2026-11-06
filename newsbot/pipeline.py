"""Day 0 entry point: python -m newsbot.pipeline --out out [--offline-fixture PATH]"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import feeds as feedmod
from . import llm, manifest, playlist, r2, render, script as scriptmod
from .tts import Tts


def sysinfo() -> dict:
    mem = {}
    for ln in Path("/proc/meminfo").read_text().splitlines():
        k, v = ln.split(":")
        if k in ("MemTotal", "MemAvailable"):
            mem[k] = int(v.split()[0]) // 1024
    model = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines()
                  if l.startswith("model name")), "?")
    return {"cpu_count": os.cpu_count(), "cpu_model": model, "mem_total_mb": mem.get("MemTotal"),
            "mem_available_mb": mem.get("MemAvailable"), "python": platform.python_version(),
            "os": platform.platform()}  # no environment variables are read or printed


class Timer:
    def __init__(self):
        self.stages, self.t0 = {}, time.time()

    @contextmanager
    def stage(self, name):
        t = time.time()
        print(f"--- stage: {name}", flush=True)
        try:
            yield
        finally:
            self.stages[name] = round(time.time() - t, 2)
            print(f"--- stage {name}: {self.stages[name]} s", flush=True)

    def total(self):
        return round(time.time() - self.t0, 2)


def load_fixture(path: Path):
    """Offline dry run: items previously saved by --save-items (real feed text, fetched elsewhere)."""
    data = json.loads(path.read_text())
    return [feedmod.Item(**d) for d in data["items"]], data.get("reports", [])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--items-json", help="use saved items instead of fetching (offline dry run)")
    ap.add_argument("--tts", choices=["kokoro", "espeak-ng"], help="force a TTS engine")
    a = ap.parse_args(argv)
    out, work = Path(a.out), Path("work")
    out.mkdir(parents=True, exist_ok=True), work.mkdir(exist_ok=True)
    tm, info = Timer(), sysinfo()
    print("runner:", json.dumps(info))

    with tm.stage("fetch_feeds"):
        if a.items_json:
            items, reports = load_fixture(Path(a.items_json))
        else:
            items, reports = feedmod.fetch_all()
            reports = feedmod.reports_json(reports)
        (out / "items.json").write_text(json.dumps({"items": [i.__dict__ for i in items], "reports": reports}, indent=1))
        ok_feeds = sum(1 for r in reports if r.get("ok"))
        print(f"{len(items)} items from {ok_feeds} working feeds")
        if len(items) < 4:
            print("not enough items to build a bulletin", file=sys.stderr)
            return 2

    with tm.stage("write_script"):
        counts = scriptmod.source_counts(items)
        sc = llm.write_with_claude(items, counts)  # None unless ANTHROPIC_API_KEY is set (and checks pass)
        if sc is None:
            sc = scriptmod.extractive_script(items, counts)
        bad = scriptmod.check_script(sc)
        if bad:  # drop failing stories is not possible in the extractive path; fail loudly
            print(f"fact check failed: {bad}", file=sys.stderr)
            return 3
        (out / "script.json").write_text(json.dumps(sc, indent=1))
        print("script by:", sc["generated_by"])

    with tm.stage("tts"):
        plan = render.build_plan(sc)
        tts = Tts(force_engine=a.tts)
        print("tts engine:", tts.engine)
        render.make_audio(plan, tts, work)

    with tm.stage("render_and_encode"):
        perf = render.render_video(plan, sc, work, out)
        print("render perf:", json.dumps(perf))

    with tm.stage("manifest"):
        m = manifest.build_manifest(out, sc, plan)
        (out / "plan.json").write_text(json.dumps(plan, indent=1))
        (out / "rolling_example.m3u8").write_text(playlist.rolling_playlist(m, now=6 * 23.5))

    uploaded = 0
    if r2.r2_configured():
        with tm.stage("r2_upload"):
            uploaded = r2.upload(out, time.strftime("bulletins/%Y%m%dT%H%M%SZ", time.gmtime()))
    else:
        print("R2 secrets not set: skipping R2 upload")

    report = {"runner": info, "stage_seconds": tm.stages, "total_seconds": tm.total(), "render": perf,
              "tts_engine": tts.engine, "tts_fallback_reason": tts.fallback_reason,
              "script_by": sc["generated_by"], "feeds": reports, "r2_files_uploaded": uploaded,
              "segments": len(m["segments"])}
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print("REPORT", json.dumps({k: report[k] for k in ("runner", "stage_seconds", "total_seconds", "render", "tts_engine")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
