"""Scene plan -> audio -> frames -> one H.264/AAC encode -> split into ten 6 s HLS segments."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import cards

SEG = 6.0
N_SCENES = 10
FRAMES_PER_SCENE = int(SEG * cards.FPS)


def spoken(s: str) -> str:
    return s.replace("...", ".").replace("“", "").replace("”", "")


def build_plan(script: dict) -> list[dict]:
    """Ten 6 s scenes. Every claim-bearing headline scene is followed by its citation card."""
    stories = script["stories"]
    assert len(stories) == 4, "Day 0 bulletin needs exactly 4 stories"
    plan = [{"kind": "chart", "title": "Today's sources", "chart": script["chart"],
             "claims": [], "citation": {"source": "feeds", "url": "", "published": ""},
             "narration": script["intro"]}]
    for i, s in enumerate(stories):
        cite = {"source": s["source"], "url": s["url"], "published": s["published"]}
        plan.append({"kind": "headline", "story": i, "headline": s["headline"],
                     "claims": [s["headline"]], "citation": cite,
                     "narration": spoken(s["headline"])})
        plan.append({"kind": "citation", "story": i, "claims": [s["quote"]], "citation": cite,
                     "narration": f"According to {s['source']}. {spoken(s['quote'])}"})
    plan.append({"kind": "outro", "title": "That was the bulletin",
                 "subtitle": "AI-generated. Every item cites its source.",
                 "claims": [], "citation": {"source": "", "url": "", "published": ""},
                 "narration": script["outro"]})
    assert len(plan) == N_SCENES
    return plan


def ticker_text(script: dict) -> str:
    return "".join(f"[{s['source']}] {s['headline']}     •     " for s in script["stories"])


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def make_audio(plan, tts, work: Path) -> float:
    """Synthesise each scene, fit to exactly 6.0 s at 48 kHz mono, concat into master.wav."""
    parts = []
    for i, sc in enumerate(plan):
        raw, fit = work / f"tts_{i:02d}.wav", work / f"fit_{i:02d}.wav"
        tts.synth(sc["narration"], str(raw))
        dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                         "csv=p=0", str(raw)]).stdout)
        avail = SEG - 0.5 - 0.2  # 0.5 s lead-in, 0.2 s tail
        tempo = min(1.35, max(1.0, dur / avail))
        af = f"atempo={tempo:.3f},adelay=500,aresample=48000,apad"
        run(["ffmpeg", "-y", "-i", str(raw), "-af", af, "-ac", "1", "-ar", "48000", "-t", str(SEG), str(fit)])
        sc["tts_seconds"], sc["tempo"] = round(dur, 2), round(tempo, 3)
        parts.append(fit)
    lst = work / "audio.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(work / "master.wav")])
    return len(plan) * SEG


def render_video(plan, script, work: Path, out: Path) -> dict:
    ticker = ticker_text(script)
    surface = cards.new_surface()
    canvas = surface.getCanvas()
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{cards.W}x{cards.H}",
           "-r", str(cards.FPS), "-i", "-", "-i", str(work / "master.wav"),
           "-t", str(N_SCENES * SEG),
           "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "23",
           "-pix_fmt", "yuv420p", "-r", str(cards.FPS), "-g", "60", "-keyint_min", "60",
           "-sc_threshold", "0", "-bf", "2", "-x264-params", "open-gop=0:scenecut=0",
           "-force_key_frames", "expr:gte(t,n_forced*2)",
           "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "1",
           "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
           "-hls_flags", "independent_segments", "-hls_segment_type", "mpegts",
           "-hls_segment_filename", str(out / "seg_%03d.ts"), str(out / "index.m3u8")]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    draw_s = 0.0
    t0 = time.time()
    frame = 0
    for sc in plan:
        for f in range(FRAMES_PER_SCENE):
            d0 = time.perf_counter()
            cards.draw_scene(canvas, sc, f / cards.FPS, frame, ticker)
            buf = cards.frame_bytes(surface)
            draw_s += time.perf_counter() - d0
            p.stdin.write(buf)
            frame += 1
    p.stdin.close()
    err = p.stderr.read().decode("utf-8", "replace")
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed: " + err[-800:])
    return {"frames": frame, "skia_draw_seconds": round(draw_s, 2),
            "skia_fps_draw_and_readback": round(frame / draw_s, 1),
            "pipeline_fps_incl_encode": round(frame / (time.time() - t0), 1)}
