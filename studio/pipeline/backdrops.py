#!/usr/bin/env python3
"""Image library for the channel: MOSS-Image Turbo makes backdrops and title cards on request, once, and they are reused.

Layout under LIB (e.g. /hyperai/home/loop/puddle/library):
  requests/<name>.json   {"name", "kind": "backdrop"|"card", "prompt", "text"?}   written by the producer
  images/<name>.png      finished 1280x720 image
  index.json             {name: {"kind", "prompt", "text", "made"}} for everything finished
  failed/<name>.json     requests MOSS could not make

The GPU is shared with Qwen (18 GB, always loaded) and Blender, so images are made in short "windows" that the channel
worker opens between blocks while Blender is idle: start ComfyUI (MOSS text encoder on the CPU, model in low-VRAM
mode), make up to N pending images, stop ComfyUI so its RAM comes back. The channel replays recent blocks meanwhile.

  python backdrops.py --lib /hyperai/home/loop/puddle/library --max 4     # one window by hand
"""
import argparse
import json
import re
import shutil
import subprocess
import time
import urllib.request
import uuid
import zlib
from pathlib import Path

HOME = Path("/hyperai/home")
URL = "http://127.0.0.1:8188"
COMFY_OUT = HOME / "ComfyUI" / "output"

STYLE = {
    "backdrop": ("A wide panoramic painted backdrop for a preschool puppet show: {prompt}. Handmade felt, paper and cardboard "
                 "textures, soft warm light, bright gentle colors. The scenery sits along the bottom edge as if standing on "
                 "the ground, with sky above. No characters, no people, no animals, no text."),
    "card": ("A cheerful preschool TV title card that says \"{text}\" in big round friendly letters made of colorful felt, "
             "centered and easy to read. {prompt}. Handmade felt and paper style, soft light, no other words, no people."),
}

# backdrops are panoramic (3.5:1): Blender's wide shot sees a strip of the back wall above the floor; cards fill the screen
SIZE = {"backdrop": (1792, 512), "card": (1280, 720)}


def log(*a):
    print(time.strftime("%H:%M:%S"), "[library]", *a, flush=True)


def safe_name(s):
    return re.sub(r"[^a-z0-9_]+", "_", str(s).lower()).strip("_")[:40]


class Library:
    def __init__(self, lib: Path):
        self.lib = lib
        self.req, self.img, self.failed = lib / "requests", lib / "images", lib / "failed"
        for d in (self.req, self.img, self.failed):
            d.mkdir(parents=True, exist_ok=True)
        self.index_path = lib / "index.json"

    def index(self) -> dict:
        try:
            return json.loads(self.index_path.read_text())
        except Exception:
            return {}

    def ready(self, kind=None) -> dict:
        return {k: v for k, v in self.index().items() if (kind is None or v["kind"] == kind) and (self.img / f"{k}.png").exists()}

    def pending(self) -> list[dict]:
        out = []
        for p in sorted(self.req.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                out.append(json.loads(p.read_text()))
            except Exception:
                p.rename(self.failed / p.name)
        return out

    def request(self, name, kind, prompt, text=None) -> str | None:
        """Queue an image unless it exists or is queued. Returns the safe name, or None if the request is unusable."""
        name = safe_name(name)
        if not name or kind not in STYLE or not str(prompt).strip():
            return None
        if kind == "card" and not str(text or "").strip():
            return None
        if (self.img / f"{name}.png").exists() or (self.req / f"{name}.json").exists():
            return name
        body = {"name": name, "kind": kind, "prompt": str(prompt)[:400], "text": (str(text)[:40] if text else None)}
        tmp = self.req / f"{name}.json.tmp"
        tmp.write_text(json.dumps(body))
        tmp.rename(self.req / f"{name}.json")
        return name

    def path(self, name) -> Path | None:
        p = self.img / f"{safe_name(name)}.png"
        return p if p.exists() else None

    # ---- generation window -------------------------------------------------------------------------------------
    def make_pending(self, max_n=4, timeout_s=600) -> int:
        todo = self.pending()[:max_n]
        if not todo:
            return 0
        t0 = time.time()
        proc = start_comfy()
        made = 0
        try:
            wait_comfy(timeout_s=240)
            log(f"ComfyUI up in {time.time() - t0:.0f}s, making {len(todo)} image(s)")
            for r in todo:
                t = time.time()
                try:
                    w, h = SIZE[r["kind"]]
                    src = generate(STYLE[r["kind"]].format(prompt=r["prompt"], text=r.get("text") or ""),
                                   seed=zlib.crc32(r["name"].encode()), w=w, h=h)
                    shutil.copy(src, self.img / f"{r['name']}.png")
                    src.unlink(missing_ok=True)
                    idx = self.index()
                    idx[r["name"]] = {"kind": r["kind"], "prompt": r["prompt"], "text": r.get("text"), "made": time.time()}
                    tmp = self.index_path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(idx, indent=1))
                    tmp.rename(self.index_path)
                    (self.req / f"{r['name']}.json").unlink(missing_ok=True)
                    made += 1
                    log(f"made {r['kind']} '{r['name']}' in {time.time() - t:.0f}s")
                except Exception as e:
                    # a transient ComfyUI error should not lose the order: retry in later windows, give up after 3
                    tries = int(r.get("tries", 0)) + 1
                    p = self.req / f"{r['name']}.json"
                    log(f"FAILED {r['name']} (try {tries}/3): {e!r}"[:300])
                    if p.exists():
                        if tries >= 3:
                            p.rename(self.failed / p.name)
                        else:
                            tmp = p.with_suffix(".tmp")
                            tmp.write_text(json.dumps({**r, "tries": tries}))
                            tmp.rename(p)
                if time.time() - t0 > timeout_s:
                    break
        finally:
            stop_comfy(proc)
        log(f"window done: {made} image(s) in {time.time() - t0:.0f}s")
        return made


def start_comfy():
    subprocess.run(["pkill", "-f", "ComfyUI/main.py"], check=False)
    logf = open(HOME / "loop" / "comfy.log", "a")
    return subprocess.Popen([str(HOME / "venv/bin/python"), "ComfyUI/main.py", "--listen", "127.0.0.1", "--port", "8188",
                             "--disable-auto-launch", "--lowvram"],
                            cwd=HOME, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def wait_comfy(timeout_s=240):
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            urllib.request.urlopen(URL + "/system_stats", timeout=5)
            return
        except Exception:
            time.sleep(2)
    raise TimeoutError("ComfyUI did not start")


def stop_comfy(proc):
    try:
        post("/free", {"unload_models": True, "free_memory": True})
    except Exception:
        pass
    proc.terminate()
    try:
        proc.wait(20)
    except subprocess.TimeoutExpired:
        proc.kill()


def post(path, body):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def generate(text, seed, steps=8, w=1280, h=720) -> Path:
    prefix = f"lib_{uuid.uuid4().hex[:8]}"
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "moss_image_sft_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3.5_9b_int8_convrot.safetensors", "type": "moss_image", "device": "cpu"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": text}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
                                                   "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }
    pid = post("/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})["prompt_id"]
    end = time.time() + 400
    while time.time() < end:
        h = json.load(urllib.request.urlopen(f"{URL}/history/{pid}", timeout=30))
        if pid in h and h[pid].get("status", {}).get("completed") is not None:
            st = h[pid]["status"]
            if st.get("status_str") != "success":
                raise RuntimeError(json.dumps(st)[:400])
            ims = [im for n in h[pid].get("outputs", {}).values() for im in n.get("images", [])]
            return COMFY_OUT / ims[0].get("subfolder", "") / ims[0]["filename"]
        time.sleep(1)
    raise TimeoutError("image took too long")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", type=Path, default=HOME / "loop/puddle/library")
    ap.add_argument("--max", type=int, default=4)
    ap.add_argument("--request", nargs=3, metavar=("NAME", "KIND", "PROMPT"))
    ap.add_argument("--text")
    a = ap.parse_args()
    lib = Library(a.lib)
    if a.request:
        print(lib.request(*a.request, text=a.text))
        return
    lib.make_pending(a.max)


if __name__ == "__main__":
    main()
