"""Tiny nodes for tests/test_spine.py (no ffmpeg, no network)."""
import json
import os

from spine.contract import Job, Skip


def make(job: Job):
    n_file = job.state / "n"
    n = int(n_file.read_text()) if n_file.exists() else 0
    n_file.write_text(str(n + 1))
    job.out("script.json").write_text(json.dumps({"n": n}))
    return {"script.json": "script.json"}, f"item {n}"


def render(job: Job):
    sc = json.loads(job.inputs["script.json"].read_text())
    if sc["n"] in job.params.get("fail", []):
        raise RuntimeError("boom")
    if sc["n"] in job.params.get("skip", []):
        raise Skip("nothing to say")
    job.out("clip.txt").write_text(f"{job.params.get('voice', 'a')}:{sc['n']}")
    return {"clip.mp4": "clip.txt"}


def join(job: Job):
    clips = job.inputs["clip.mp4"]
    out = job.out("out")
    (out / "episode").mkdir(parents=True)
    (out / "episode" / "manifest.json").write_text(json.dumps({"clips": [c.read_text() for c in clips]}))
    return {"out": out}


def no_result(job: Job):
    os._exit(0)  # exits before result.json: must count as fail
