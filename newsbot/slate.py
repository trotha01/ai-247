"""Standby/slate loop segment set: same encode parameters as an episode, silent audio, so the stream never goes dark."""
from __future__ import annotations

from pathlib import Path

from . import episode

SLATE_SECONDS = 30.0  # five 6 s segments


def build_slate(out: Path, work: Path, seconds: float = SLATE_SECONDS) -> dict:
    scenes = [{"kind": "standby", "title": "Standby", "subtitle": "The next episode is being prepared. Replays and this slate keep the channel on air.",
               "claims": [], "headline": "", "citation": {"source": "", "url": "", "published": ""},
               "narration": "", "duration": seconds, "_raw": None}]
    work.mkdir(parents=True, exist_ok=True)
    master = _silent(work, seconds)
    perf = episode.render_scenes(scenes, "AI-GENERATED STANDBY SLATE  •  no claims are made on this slide     •     ", master, out, prefix="slate")
    return perf


def _silent(work: Path, seconds: float) -> Path:
    from .render import run
    p = work / "slate_silence.wav"
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(seconds), str(p)])
    return p
