"""TTS with fallback chain: Kokoro-82M (kokoro-onnx, CPU) -> espeak-ng."""
from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

# Model files are fetched from GitHub releases (huggingface.co may be blocked on some networks).
MODEL_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
MODEL_FILES = {"kokoro-v1.0.int8.onnx": 92_000_000, "voices-v1.0.bin": 28_000_000}
VOICE = os.environ.get("NEWSBOT_VOICE", "af_heart")


class Tts:
    def __init__(self, model_dir="models", force_engine: str | None = None, log=print):
        self.log, self.engine, self._k, self.speed = log, None, None, 1.0
        order = [force_engine] if force_engine else ["kokoro", "espeak-ng"]
        errs = []
        for name in order:
            try:
                if name == "kokoro":
                    self._init_kokoro(Path(model_dir))
                elif name == "espeak-ng":
                    if not shutil.which("espeak-ng"):
                        raise RuntimeError("espeak-ng not installed")
                self.engine = name
                break
            except Exception as e:
                errs.append(f"{name}: {type(e).__name__}: {str(e)[:100]}")
                log(f"tts engine {name} unavailable: {errs[-1]}")
        if not self.engine:
            raise RuntimeError("no TTS engine available: " + "; ".join(errs))
        self.fallback_reason = "; ".join(errs)

    def _init_kokoro(self, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        for fn, min_size in MODEL_FILES.items():
            p = d / fn
            if not p.exists() or p.stat().st_size < min_size:
                self.log(f"downloading {fn}")
                req = urllib.request.Request(f"{MODEL_BASE}/{fn}", headers={"User-Agent": "ai-247-newsbot"})
                with urllib.request.urlopen(req, timeout=120) as r, open(p, "wb") as f:
                    shutil.copyfileobj(r, f)
        from kokoro_onnx import Kokoro
        self._k = Kokoro(str(d / "kokoro-v1.0.int8.onnx"), str(d / "voices-v1.0.bin"))

    def synth(self, text: str, wav_path: str) -> None:
        if self.engine == "kokoro":
            import soundfile as sf
            samples, sr = self._k.create(text, voice=VOICE, speed=self.speed, lang="en-us")
            sf.write(wav_path, samples, sr)
        else:
            subprocess.run(["espeak-ng", "-v", "en-us", "-s", str(int(165 * self.speed)), "-w", wav_path, text],
                           check=True, capture_output=True)
