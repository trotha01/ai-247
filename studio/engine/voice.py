#!/usr/bin/env python3
"""Voice pass for a Puddle Park scene script (runs before Blender).

For every "say" event: synthesize the line with the speaker's voice (Kokoro TTS),
apply the character's pitch, set the event's real duration, and store a per-frame
loudness envelope ("env") that Blender uses to open and close the puppet's mouth.
Then mix all lines into one track at their start times.

  python voice.py scene.json out_dir/   ->  out_dir/scene.voiced.json, out_dir/voices.wav

Cast voice spec (in the scene script):
  "pip": {"voice": {"id": "af_sky", "speed": 1.05, "pitch": 1.3}}
  id     Kokoro voice name
  speed  speaking rate (1.0 = normal)
  pitch  pitch multiplier (1.3 = higher, squeakier; 0.8 = deeper)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

MODEL_DIR = Path("/hyperai/home/models/kokoro")
SR_OUT = 48000
DEFAULT_VOICE = {"id": "af_heart", "speed": 1.0, "pitch": 1.0}


def pitch_shift(samples, sr, pitch):
    """Shift pitch without changing duration (ffmpeg: asetrate + atempo)."""
    if abs(pitch - 1.0) < 1e-3:
        return samples, sr
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.wav", Path(d) / "out.wav"
        sf.write(src, samples, sr)
        tempo = 1.0 / pitch
        chain = []
        while tempo < 0.5:  # atempo accepts 0.5..2.0 per stage
            chain.append("atempo=0.5")
            tempo /= 0.5
        while tempo > 2.0:
            chain.append("atempo=2.0")
            tempo /= 2.0
        chain.append(f"atempo={tempo:.5f}")
        af = f"asetrate={int(sr * pitch)},aresample={sr}," + ",".join(chain)
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-af", af, str(dst)],
                       check=True)
        out, sr2 = sf.read(dst, dtype="float32")
    return out, sr2


def envelope(samples, sr, fps):
    """Per-video-frame mouth openness 0..1 from RMS loudness, lightly smoothed."""
    hop = sr / fps
    n = int(np.ceil(len(samples) / hop))
    rms = np.array([np.sqrt(np.mean(samples[int(i * hop):int((i + 1) * hop)] ** 2) + 1e-12) for i in range(n)])
    db = 20 * np.log10(rms)
    env = np.clip((db + 45) / 30, 0, 1)  # -45 dB = closed, -15 dB = fully open
    env = np.convolve(env, [0.25, 0.5, 0.25], mode="same")
    env[env < 0.12] = 0.0
    return [round(float(x), 3) for x in env]


def resample(samples, sr, target):
    if sr == target:
        return samples
    x = np.linspace(0, len(samples), int(len(samples) * target / sr), endpoint=False)
    return np.interp(x, np.arange(len(samples)), samples).astype(np.float32)


def main():
    scene_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    scene = json.loads(scene_path.read_text())
    fps = int(scene.get("fps", 30))
    total = float(scene.get("seconds", 15))
    k = Kokoro(str(MODEL_DIR / "kokoro-v1.0.int8.onnx"), str(MODEL_DIR / "voices-v1.0.bin"))
    mix = np.zeros(int(total * SR_OUT), dtype=np.float32)
    report = []
    says = sorted((e for e in scene["timeline"] if e["do"] == "say"), key=lambda e: e["t"])
    for i, ev in enumerate(says):
        v = {**DEFAULT_VOICE, **scene["cast"][ev["who"]].get("voice", {})}
        samples, sr = k.create(ev["text"], voice=v["id"], speed=float(v["speed"]), lang="en-us")
        samples, sr = pitch_shift(np.asarray(samples, dtype=np.float32), sr, float(v["pitch"]))
        # trim leading/trailing silence so the mouth starts on the first sound
        nz = np.where(np.abs(samples) > 0.01)[0]
        if len(nz):
            samples = samples[max(0, nz[0] - int(0.03 * sr)): nz[-1] + int(0.06 * sr)]
        dur = len(samples) / sr
        ev["dur"] = round(dur, 3)
        ev["env"] = envelope(samples, sr, fps)
        nxt = says[i + 1]["t"] if i + 1 < len(says) else total
        if ev["t"] + dur > nxt + 0.05:
            report.append(f"WARNING: '{ev['text']}' ({dur:.2f}s at {ev['t']}s) overlaps the next line at {nxt}s")
        s48 = resample(samples, sr, SR_OUT)
        a = int(ev["t"] * SR_OUT)
        b = min(len(mix), a + len(s48))
        mix[a:b] += s48[: b - a] * 0.9
        report.append(f"{ev['who']:>8} {ev['t']:5.2f}s +{dur:.2f}s  {ev['text']}")
    peak = float(np.max(np.abs(mix))) if mix.any() else 1.0
    if peak > 0.98:
        mix *= 0.98 / peak
    sf.write(out_dir / "voices.wav", np.stack([mix, mix], axis=1), SR_OUT)
    (out_dir / "scene.voiced.json").write_text(json.dumps(scene, indent=1))
    print("\n".join(report))


if __name__ == "__main__":
    main()
