"""Language channel nodes: thin wrappers around lang.lesson (generator) and lang.render (cards + Piper + ffmpeg)."""
from __future__ import annotations

import json

from spine.contract import Job


def pick_lesson(job: Job):
    """-> script.json: lang.lesson.lesson(n) with n kept in the node's state folder (next_n, same file the old
    lang.producer_loop used, so a swap carries on the lesson sequence). params: start (first n when no state)."""
    from lang.lesson import lesson
    st = job.state / "next_n"
    n = int(st.read_text().strip() or 0) if st.exists() else int(job.params.get("start", 0))
    sc = lesson(n)
    job.out("script.json").write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
    st.write_text(f"{n + 1}\n")
    return {"script.json": "script.json"}, f"lesson {n} {sc['id']} {sc['ref']}"


def render_lesson(job: Job):
    """script.json -> clip.mp4 (lang.render.render_clip). params: voices {lang code: Piper voice name} overrides
    lang.render.VOICES (la, grc, he, en), e.g. to swap the English narrator by editing only the channel YAML."""
    from lang import render
    for k, v in (job.params.get("voices") or {}).items():
        if k not in render.VOICES:
            raise ValueError(f"unknown voice slot {k!r} (have {sorted(render.VOICES)})")
        render.VOICES[k] = v
    sc = json.loads(job.inputs["script.json"].read_text(encoding="utf-8"))
    clip = render.render_clip(sc, job.out("render"))
    voices = ",".join(f"{k}={render.VOICES[k]}" for k in sorted(render.VOICES))
    return {"clip.mp4": clip}, f"{sc['id']} rendered ({voices})"
