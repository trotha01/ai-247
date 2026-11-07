"""Render one lesson script to clip.mp4: HTML/CSS cards -> PNG (headless Chromium), Piper voices -> WAV, ffmpeg.

    python -m lang.render 0 --out /tmp/lesson0          # lesson 0 -> /tmp/lesson0/clip.mp4

Voices (licences in lang/LICENSES.md, all allow commercial use): Latin it_IT-paola-medium (CC0 data), read from an
ecclesiastical respelling; Greek el_GR-rapunzelina-medium (CC0 data); Hebrew: the same Greek voice driven by IPA
phonemes built from the transliteration (the only Piper Hebrew voice is trained on non-commercial data); English
en_US-ljspeech-medium (public-domain data). Output: 1280x720 30 fps H.264 + AAC 48 kHz stereo, closed 2 s GOP,
the same settings as studio/pipeline/channel_worker.py so blocks can be joined and cut into HLS segments.
"""
from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from .translit import hebrew_ipa, latin_speech

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"
VOICE_DIR = Path(os.environ.get("LANG_VOICES", HERE.parent.parent / "voices"))
VOICES = {"la": "it_IT-paola-medium", "grc": "el_GR-rapunzelina-medium", "he": "el_GR-rapunzelina-medium",
          "en": "en_US-ljspeech-medium"}
FPS = 30
SR = 22050
GAP_S, TAIL_S = 0.35, 0.7
CREDITS = {
    "la": "Latin: Clementine Vulgate (VulSearch text, public domain) · parsing: Whitaker's WORDS · English: World English Bible (public domain)",
    "grc": "Greek: SBLGNT (CC BY 4.0) · lemmas, parsing, glosses: MACULA Greek, Biblica (CC BY 4.0) · English: World English Bible (public domain)",
    "he": "Hebrew: Westminster Leningrad Codex (public domain) · morphology: OSHB / MACULA Hebrew, Biblica (CC BY 4.0) · English: World English Bible (public domain)",
}

_voices = {}


def voice(lang: str):
    from piper import PiperVoice
    name = VOICES[lang]
    if name not in _voices:
        _voices[name] = PiperVoice.load(str(VOICE_DIR / f"{name}.onnx"))
    return _voices[name]


def speak(lang: str, text: str, rate: float) -> np.ndarray:
    """float32 mono audio at SR for one utterance."""
    from piper import SynthesisConfig
    v = voice(lang)
    cfg = SynthesisConfig(length_scale=rate)
    if lang == "he":
        ids = v.phonemes_to_ids(list(hebrew_ipa(text)))
        audio = v.phoneme_ids_to_audio(ids, cfg)
        audio = audio[0] if isinstance(audio, tuple) else audio
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        m = float(np.max(np.abs(audio))) if audio.size else 0.0
        return audio / m * 0.9 if m > 1e-8 else audio
    if lang == "la":
        text = latin_speech(text)
    parts = [np.asarray(c.audio_float_array, dtype=np.float32) for c in v.synthesize(text, cfg)]
    return np.concatenate(parts) if parts else np.zeros(1, np.float32)


def card_html(sc: dict, card: dict) -> str:
    lang, rtl = sc["lang"], sc["dir"] == "rtl"
    hi = card.get("i") if card["kind"] == "word" else None
    spans = []
    for i, w in enumerate(sc["words"]):
        cls = "w hi" if i == hi else "w"
        spans.append(f'<span class="{cls}">{html.escape(w["text"])}</span>{html.escape(w.get("after", ""))}')
    verse = " ".join(spans)
    tl = " ".join(w["translit"] for w in sc["words"] if w["translit"])
    body = ""
    if card["kind"] == "intro":
        body = (f'<div class="intro"><div class="lang">{html.escape(sc["language"])}</div>'
                f'<div class="ref big">{html.escape(sc["ref"])}</div>'
                f'<div class="v {"rtl" if rtl else ""}">{verse}</div></div>')
    else:
        body = f'<div class="v {"rtl" if rtl else ""}">{verse}</div>'
        if tl:
            body += f'<div class="tl">{html.escape(tl)}</div>'
        if card["kind"] == "word":
            w = sc["words"][hi]
            body += ('<div class="panel">'
                     f'<div class="pw {"rtl" if rtl else ""}">{html.escape(w["text"])}</div>'
                     f'<div class="pt">{html.escape(w["translit"])}</div>'
                     f'<div class="pg">“{html.escape(w["gloss"])}”</div>'
                     f'<div class="pl"><span class="k">lemma</span> <span class="{"rtl" if rtl else ""}">{html.escape(w["lemma"])}</span></div>'
                     f'<div class="pp"><span class="k">parsing</span> {html.escape(w["parse"])}</div></div>')
        if card.get("english"):
            body += f'<div class="en">{html.escape(sc["english"])}</div>'
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: NotoSerif; src: url("file://{FONTS}/NotoSerif.ttf"); }}
@font-face {{ font-family: NotoSerifHebrew; src: url("file://{FONTS}/NotoSerifHebrew.ttf"); }}
html, body {{ margin: 0; width: 1280px; height: 720px; overflow: hidden; }}
body {{ background: radial-gradient(ellipse at 50% 30%, #2b2438 0%, #15121c 70%); color: #efe6d2;
  font-family: NotoSerif, NotoSerifHebrew, serif; display: flex; flex-direction: column; padding: 34px 60px 26px;
  box-sizing: border-box; }}
.top {{ display: flex; justify-content: space-between; font-size: 22px; letter-spacing: .08em; color: #c9a85b;
  text-transform: uppercase; }}
.main {{ flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 18px; }}
.v {{ font-size: {58 if rtl else 46}px; line-height: 1.45; text-align: center; }}
.rtl {{ direction: rtl; unicode-bidi: isolate; font-family: NotoSerifHebrew, serif; }}
.w {{ padding: 0 .08em; border-radius: 8px; }}
.w.hi {{ background: #c9a85b; color: #15121c; }}
.tl {{ font-size: 26px; font-style: italic; text-align: center; color: #b9b0c9; }}
.en {{ font-size: 30px; text-align: center; color: #f6efe0; border-top: 1px solid #4a405c; padding-top: 16px; }}
.panel {{ margin: 6px auto 0; padding: 18px 34px; border: 1px solid #c9a85b; border-radius: 14px; min-width: 560px;
  text-align: center; background: rgba(0,0,0,.25); }}
.pw {{ font-size: 54px; }} .pt {{ font-size: 26px; font-style: italic; color: #b9b0c9; }}
.pg {{ font-size: 36px; color: #ffe7a8; margin: 4px 0; }}
.pl, .pp {{ font-size: 24px; color: #d8cfe6; }} .k {{ color: #8e83a3; font-size: 18px; text-transform: uppercase; letter-spacing: .1em; }}
.intro {{ text-align: center; }} .lang {{ font-size: 30px; color: #c9a85b; letter-spacing: .1em; text-transform: uppercase; }}
.big {{ font-size: 64px; margin: 10px 0 30px; }}
.foot {{ font-size: 14px; color: #7d7390; text-align: center; }}
</style></head><body>
<div class="top"><span>Lingua · {html.escape(sc["language"])}</span><span>{html.escape(sc["ref"])}</span></div>
<div class="main">{body}</div>
<div class="foot">{html.escape(CREDITS[lang])} · AI-247 language channel, code-made, may contain errors</div>
</body></html>"""


def render_cards(sc: dict, work: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        exe = os.environ.get("LANG_CHROMIUM") or None  # a system Chromium (e.g. from nix) instead of Playwright's download
        b = p.chromium.launch(executable_path=exe, args=["--allow-file-access-from-files"])
        page = b.new_page(viewport={"width": 1280, "height": 720})
        cache = {}
        for i, st in enumerate(sc["steps"]):
            key = json.dumps(st["card"], sort_keys=True)
            if key not in cache:
                h = work / f"card_{len(cache):02d}.html"
                h.write_text(card_html(sc, st["card"]), encoding="utf-8")
                page.goto(h.as_uri())
                page.evaluate("document.fonts.ready")
                png = h.with_suffix(".png")
                page.screenshot(path=str(png))
                cache[key] = png
            out.append(cache[key])
        b.close()
    return out


def render_audio(sc: dict, work: Path) -> tuple[Path, list[float]]:
    pieces, durs = [], []
    gap = np.zeros(int(GAP_S * SR), np.float32)
    for st in sc["steps"]:
        seg = []
        for u in st["say"]:
            if u["text"].strip():
                seg += [speak(u["voice"], u["text"], u["rate"]), gap]
        seg.append(np.zeros(int(TAIL_S * SR), np.float32))
        a = np.concatenate(seg)
        # every step lasts a whole number of video frames, so pictures and voice stay in step
        n = int(np.ceil(len(a) / SR * FPS)) * SR // FPS
        a = np.pad(a, (0, max(0, n - len(a))))[:n]
        pieces.append(a)
        durs.append(len(a) / SR)
    audio = np.concatenate(pieces)
    wav = work / "voice.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return wav, durs


def render_clip(sc: dict, work: Path) -> Path:
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work / "script.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
    pngs = render_cards(sc, work)
    wav, durs = render_audio(sc, work)
    lst = work / "frames.txt"
    lines = []
    for png, d in zip(pngs, durs):
        lines += [f"file '{png}'", f"duration {d:.6f}"]
    lines.append(f"file '{pngs[-1]}'")
    lst.write_text("\n".join(lines) + "\n")
    total = sum(durs)
    out = work / "clip.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-i", str(wav), "-vf", f"fps={FPS},scale=1280:720,format=yuv420p", "-t", f"{total:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-tune", "stillimage", "-g", str(FPS * 2),
                    "-keyint_min", str(FPS * 2), "-sc_threshold", "0",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k", "-af", "apad", "-shortest", str(out)],
                   check=True)
    return out


def main(argv=None):
    import argparse
    from .lesson import lesson
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("n", type=int)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    print(render_clip(lesson(a.n), a.out))


if __name__ == "__main__":
    main()
