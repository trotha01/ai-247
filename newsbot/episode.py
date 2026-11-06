"""Day 1: build a 10-minute episode (variable-length scenes) and render it as 6 s HLS segments.

Scenes: intro (rundown) -> per story [headline, one scene per aired sentence, source card] -> recap -> outro ->
standby pad to exactly TARGET seconds. Every scene that carries a claim carries its citation on screen.
"""
from __future__ import annotations

import datetime as dt
import math
import subprocess
import time
from pathlib import Path

from . import cards
from .render import run, ticker_text

SEG = 6.0
TARGET = 600.0
LEAD, TAIL, MIN_SCENE = 0.5, 0.5, 4.0
WORDS_PER_SEC = 2.4        # rough Kokoro pace, used only for the story-selection estimate
MAX_PAD = 40.0


def spoken_date(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso)
        return f"{d.strftime('%B')} {d.day}"
    except Exception:
        return ""


def spoken(s: str) -> str:
    return s.replace("...", ".").replace("“", "").replace("”", "").replace("’", "'")


def story_scenes(i: int, story: dict) -> list[dict]:
    cite = {"source": story["source"], "url": story["url"], "published": story["published"]}
    base = {"story": i, "headline": story["headline"], "citation": cite}
    sc = [{**base, "kind": "headline", "claims": [story["headline"]], "narration": spoken(story["headline"])}]
    for s in story["sentences"]:
        sc.append({**base, "kind": "sentence", "claims": [s["text"]], "narration": spoken(s["text"])})
    d = spoken_date(story["published"])
    sc.append({**base, "kind": "source", "claims": [],
               "narration": f"That was reported by {story['source']}" + (f", published {d}." if d else ".") + " The link is on screen."})
    return sc


def est_seconds(scenes) -> float:
    return sum(max(MIN_SCENE, math.ceil((len(s["narration"].split()) / WORDS_PER_SEC + LEAD + TAIL) * 2) / 2) for s in scenes)


def _items(stories):
    return [(s["source"], s["headline"]) for s in stories]


def frame_dur(seconds: float) -> float:
    return max(MIN_SCENE, math.ceil(seconds * 2) / 2)  # multiples of 0.5 s => whole frames and whole audio samples


def synth_scene(sc, tts, work: Path, cache: dict):
    """Synthesise a scene's narration once per distinct text (cache survives story drops)."""
    key = sc["narration"]
    if key not in cache:
        raw = work / f"tts_{len(cache):03d}.wav"
        tts.synth(key, str(raw))
        secs = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(raw)]).stdout)
        cache[key] = (raw, secs)
    raw, secs = cache[key]
    sc["tts_seconds"] = round(secs, 2)
    sc["duration"] = frame_dur(secs + LEAD + TAIL)
    sc["_raw"] = raw


def build_episode(script: dict, tts, work: Path, target: float = TARGET, max_stories: int = 12):
    """Select stories to fit `target`, synthesise, fix up with real TTS durations, pad to exactly target."""
    stories = script["stories"]
    intro = {"kind": "rundown", "title": script.get("rundown_title") or "In this episode", "items": [], "claims": [], "headline": "",
             "citation": {"source": "", "url": "", "published": ""}, "narration": script["intro"]}
    outro = {"kind": "outro", "title": "End of episode", "subtitle": "AI-generated. Every sentence cites its source.",
             "claims": [], "headline": "", "citation": {"source": "", "url": "", "published": ""}, "narration": script["outro"]}

    def recap_for(chosen):
        return {"kind": "recap", "title": "Recap", "items": _items(chosen), "claims": [], "headline": "",
                "citation": {"source": "", "url": "", "published": ""},
                "narration": "Recap. " + " ".join(spoken(s["headline"]).rstrip(".") + "." for s in chosen)}

    chart_scene = None
    if script.get("chart", {}).get("data"):
        data = script["chart"]["data"]
        chart_scene = {"kind": "chart", "title": "Where the stories come from", "chart": script["chart"], "claims": [], "headline": "",
                       "citation": {"source": "feeds", "url": "", "published": ""},
                       "narration": "Here is where today's stories come from. " + " ".join(
                           f"{src} supplied {n} items." for src, n in data[:6])}
    # 1. estimate-based selection in rank order (skip stories that do not fit, keep trying shorter ones)
    chosen, fixed = [], est_seconds([intro, outro] + ([chart_scene] if chart_scene else [])) + MAX_PAD
    for s in stories[:max_stories]:
        sc = story_scenes(len(chosen), s)
        if fixed + est_seconds(sum((story_scenes(k, c) for k, c in enumerate(chosen)), []) + sc) + est_seconds([recap_for(chosen + [s])]) <= target:
            chosen.append(s)
    cache: dict = {}
    # 2. synthesise, then drop trailing stories until the real total fits
    while True:
        intro["items"] = _items(chosen)
        scenes = [intro] + ([chart_scene] if chart_scene else [])
        for k, s in enumerate(chosen):
            scenes += story_scenes(k, s)
        scenes += [recap_for(chosen), outro]
        for sc in scenes:
            synth_scene(sc, tts, work, cache)
        total = sum(sc["duration"] for sc in scenes)
        if total <= target or len(chosen) <= 1:
            break
        chosen = chosen[:-1]
    pad = round(target - total, 3)
    if pad > 0:
        scenes.append({"kind": "standby", "title": "Next episode soon", "subtitle": "AI-generated news channel proof of concept.",
                       "claims": [], "headline": "", "citation": {"source": "", "url": "", "published": ""},
                       "narration": "", "duration": pad, "tts_seconds": 0.0, "_raw": None})
    return scenes, chosen, {"estimated_total": round(total, 2), "pad_seconds": max(pad, 0), "stories": len(chosen)}


def make_master_audio(scenes, work: Path) -> Path:
    """Per-scene wav: 0.5 s lead-in + speech, padded/trimmed to exactly the scene duration at 48 kHz mono."""
    parts = []
    for n, sc in enumerate(scenes):
        fit = work / f"fit_{n:03d}.wav"
        if sc["_raw"] is None:
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(sc["duration"]), str(fit)])
        else:
            run(["ffmpeg", "-y", "-i", str(sc["_raw"]), "-af", f"adelay={int(LEAD * 1000)},aresample=48000,apad",
                 "-ac", "1", "-ar", "48000", "-t", str(sc["duration"]), str(fit)])
        parts.append(fit)
    lst = work / "audio.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    master = work / "master.wav"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(master)])
    return master


# Shared encode settings: every Day 1 media file (episode, slate) uses exactly these.
def encode_args(total_seconds: float) -> list[str]:
    return ["-t", str(total_seconds),
            "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", str(cards.FPS), "-g", "60", "-keyint_min", "60",
            "-sc_threshold", "0", "-bf", "2", "-x264-params", "open-gop=0:scenecut=0",
            "-force_key_frames", "expr:gte(t,n_forced*2)",
            "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "1",
            "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments", "-hls_segment_type", "mpegts"]


def render_scenes(scenes, ticker: str, master: Path, out: Path, prefix: str = "seg") -> dict:
    cards.LABEL = "AI NEWS 24/7  |  Day 1 episode"
    total = sum(sc["duration"] for sc in scenes)
    surface = cards.new_surface()
    canvas = surface.getCanvas()
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-nostats", "-loglevel", "warning", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{cards.W}x{cards.H}",
           "-r", str(cards.FPS), "-i", "-", "-i", str(master), *encode_args(total),
           "-hls_segment_filename", str(out / f"{prefix}_%03d.ts"), str(out / "index.m3u8")]
    errlog = out.parent / f"ffmpeg_{prefix}.log"  # a file, not a pipe: an undrained stderr pipe deadlocks long encodes
    errf = open(errlog, "wb")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errf)
    draw_s, t0, frame = 0.0, time.time(), 0
    for sc in scenes:
        n = int(round(sc["duration"] * cards.FPS))
        for f in range(n):
            d0 = time.perf_counter()
            cards.draw_scene(canvas, sc, f / cards.FPS, frame, ticker)
            buf = cards.frame_bytes(surface)
            draw_s += time.perf_counter() - d0
            p.stdin.write(buf)
            frame += 1
    p.stdin.close()
    rc = p.wait()
    errf.close()
    if rc != 0:
        raise RuntimeError("ffmpeg failed: " + errlog.read_text(errors="replace")[-800:])
    return {"frames": frame, "skia_fps_draw_and_readback": round(frame / draw_s, 1),
            "pipeline_fps_incl_encode": round(frame / (time.time() - t0), 1)}


def public_plan(scenes) -> list[dict]:
    """Scene plan without private fields, written to plan.json (start/end give the timeline)."""
    t, out = 0.0, []
    for sc in scenes:
        d = {k: v for k, v in sc.items() if not k.startswith("_")}
        d["start"], d["end"] = round(t, 3), round(t + sc["duration"], 3)
        t += sc["duration"]
        out.append(d)
    return out


def episode_ticker(stories) -> str:
    return ticker_text({"stories": stories})
