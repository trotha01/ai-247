from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def probe_duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       check=True, capture_output=True, text=True)
    return float(r.stdout)


def probe_streams(p: Path) -> dict:
    """Per-stream and container durations. 'duration' is the video-stream duration (what EXTINF carries)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration",
                        "-of", "json", str(p)], check=True, capture_output=True, text=True)
    j = json.loads(r.stdout)
    d = {s["codec_type"]: float(s["duration"]) for s in j["streams"]}
    return {"duration": d["video"], "audio_duration": d["audio"], "container_duration": float(j["format"]["duration"])}


def build_manifest(out: Path, script: dict, plan: list[dict]) -> dict:
    segs = []
    for i, p in enumerate(sorted(out.glob("seg_*.ts"))):
        segs.append({"index": i, "file": p.name, **{k: round(v, 3) for k, v in probe_streams(p).items()},
                     "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                     "scene": plan[i]["kind"] if i < len(plan) else None})
    m = {"version": 1, "segment_seconds": 6, "generated_by": script["generated_by"],
         "segments": segs, "sources": [{"source": s["source"], "url": s["url"], "published": s["published"]}
                                       for s in script["stories"]]}
    (out / "manifest.json").write_text(json.dumps(m, indent=2))
    return m
