#!/usr/bin/env python3
"""Channel worker: scene scripts in -> live stream out.

Loop on the GPU box:
  1. take up to BLOCK scene scripts from INBOX (oldest first),
  2. voice + render them in Blender (RENDERS at once), encode each to a 15 s clip (720p30, AAC 48 kHz),
  3. join them into one block and cut 6 s HLS segments (closed 2 s GOP, same codec settings every time),
  4. publish with Trevor's ai-247 uploader (newsbot.publish.publish_many): segments first, root manifest.json last,
     earlier blocks kept as replays, swap timing per docs/MANIFEST-SWAP.md. Every key is put under PREFIX so
     several channels can share one bucket (the Worker reads PREFIX/manifest.json),
  5. keep the bucket under CAP_GB: delete the oldest blocks the live manifest no longer references.

  python channel_worker.py --root /hyperai/home/loop/puddle --prefix puddle/ --cap-gb 8
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BL = "/hyperai/home/bl.sh"
PY = "/hyperai/home/venv/bin/python"
FPS_OUT = 30
ACTIONS_LIVE = Path("/hyperai/home/loop/puddle/actions/live")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class PrefixS3:
    """Wrap a boto3 S3 client so every Key gets a prefix (Trevor's uploader writes bucket-root keys)."""

    def __init__(self, s3, prefix):
        self.s3, self.p = s3, prefix

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        return self.s3.upload_file(filename, bucket, self.p + key, ExtraArgs=ExtraArgs)

    def put_object(self, Bucket, Key, **kw):
        return self.s3.put_object(Bucket=Bucket, Key=self.p + Key, **kw)

    def get_object(self, Bucket, Key, **kw):
        return self.s3.get_object(Bucket=Bucket, Key=self.p + Key, **kw)


LIB = None  # backdrops.Library, set in main()
CARD_S = 2.0


def render_clip(scene_path: Path, work: Path) -> Path:
    """voices -> Blender frames -> clip.mp4 (720p30, AAC 48 kHz stereo, closed 2 s GOP); a title card goes in front."""
    work.mkdir(parents=True, exist_ok=True)
    sc0 = json.loads(scene_path.read_text())
    card = None
    if LIB is not None:
        bd = LIB.path(sc0["backdrop"]) if sc0.get("backdrop") else None
        if bd:
            sc0["backdrop_path"] = str(bd)
        card = LIB.path(sc0["card"]) if sc0.get("card") else None
    scene_path = work / "scene.json"
    scene_path.write_text(json.dumps(sc0))
    subprocess.run([PY, str(HERE / "voice.py"), str(scene_path), str(work)], check=True,
                   stdout=open(work / "voice.txt", "w"), stderr=subprocess.STDOUT)
    # Blender runs as the unprivileged user "render": approved plug-in actions are AI-written code, so they get no
    # access to keys or the channel's files, only this scene's work folder. Time-limited so a bad plug-in cannot hang.
    subprocess.run(["chown", "-R", "render", str(work)], check=True)
    env = {**os.environ, "HOME": "/tmp/render-home", "PUDDLE_ACTIONS": str(ACTIONS_LIVE)}
    subprocess.run([BL, "-b", "--python", str(HERE / "puddle.py"), "--", str(work / "scene.voiced.json"), str(work)],
                   check=True, stdout=open(work / "blender.log", "w"), stderr=subprocess.STDOUT, user="render",
                   env=env, timeout=600)
    sc = json.loads((work / "scene.voiced.json").read_text())
    fps = int(sc.get("fps", 24))
    step = int(sc.get("step", 2 if sc.get("on_twos") else 1))
    seconds = float(sc.get("seconds", 15))
    ext = sorted((work / "frames").iterdir())[0].suffix
    out = work / "clip.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                    "-framerate", str(fps / step), "-pattern_type", "glob", "-i", str(work / "frames" / f"*{ext}"),
                    "-i", str(work / "voices.wav"),
                    "-vf", f"fps={FPS_OUT},scale=1280:720,format=yuv420p", "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-g", str(FPS_OUT * 2),
                    "-keyint_min", str(FPS_OUT * 2), "-sc_threshold", "0",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k", "-af", "apad", "-shortest", str(out)],
                   check=True)
    shutil.rmtree(work / "frames", ignore_errors=True)
    if card:
        out = add_card(card, out, work / "clip_card.mp4")
    return out


def add_card(card: Path, clip: Path, out: Path) -> Path:
    """CARD_S seconds of the title card (fading in from and out to black, silent) in front of the clip."""
    fade = 0.3
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                    "-loop", "1", "-framerate", str(FPS_OUT), "-t", str(CARD_S), "-i", str(card),
                    "-f", "lavfi", "-t", str(CARD_S), "-i", "anullsrc=r=48000:cl=stereo", "-i", str(clip),
                    "-filter_complex",
                    f"[0:v]scale=1280:720,format=yuv420p,setsar=1,fade=in:st=0:d={fade},fade=out:st={CARD_S - fade}:d={fade}[cv];"
                    f"[2:v]setsar=1[mv];[cv][1:a][mv][2:a]concat=n=2:v=1:a=1[v][a]",
                    "-map", "[v]", "-map", "[a]", "-r", str(FPS_OUT),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-g", str(FPS_OUT * 2),
                    "-keyint_min", str(FPS_OUT * 2), "-sc_threshold", "0",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k", str(out)], check=True)
    return out


def make_block(clips: list[Path], block_dir: Path) -> Path:
    """Join clips and cut 6 s segments into block_dir/episode/ with the manifest Trevor's uploader reads."""
    ep = block_dir / "episode"
    ep.mkdir(parents=True, exist_ok=True)
    lst = block_dir / "clips.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    joined = block_dir / "block.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(joined)], check=True)
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(joined),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-g", str(FPS_OUT * 2),
                    "-keyint_min", str(FPS_OUT * 2), "-sc_threshold", "0",
                    "-force_key_frames", "expr:gte(t,n_forced*2)", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
                    "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod", "-hls_flags", "independent_segments",
                    "-hls_segment_filename", str(ep / "seg_%03d.ts"), str(ep / "index.m3u8")], check=True)
    segs = []
    for p in sorted(ep.glob("seg_*.ts")):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                             capture_output=True, text=True).stdout.split()
        d = float(out[0]) if out else 6.0
        segs.append({"file": p.name, "duration": round(d, 3), "bytes": p.stat().st_size})
    (ep / "manifest.json").write_text(json.dumps({"segments": segs}, indent=1))
    return ep


def referenced_keys(manifest: dict) -> set[str]:
    keys = set()
    for m in (manifest, manifest.get("prev") or {}):
        for b in m.get("blocks", []):
            for s in b.get("segments", []):
                keys.add(s["uri"])
    return keys


def enforce_cap(s3, bucket: str, prefix: str, cap_bytes: int, min_age_s: int = 3600):
    """Delete whole old blocks that the live manifest (and its prev) no longer reference, oldest first, until the
    channel's prefix is under cap_bytes. Blocks younger than min_age_s are kept (cached playlists may still list them)."""
    cur = json.loads(s3.get_object(Bucket=bucket, Key=prefix + "manifest.json")["Body"].read())
    live = referenced_keys(cur)
    objs, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix + "bulletins/"}
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        objs += r.get("Contents", [])
        if not r.get("IsTruncated"):
            break
        token = r["NextContinuationToken"]
    total = sum(o["Size"] for o in objs)
    blocks = {}
    for o in objs:
        rel = o["Key"][len(prefix):]
        bid = rel.split("/")[1]
        b = blocks.setdefault(bid, {"keys": [], "bytes": 0, "t": o["LastModified"].timestamp(), "live": False})
        b["keys"].append(o["Key"])
        b["bytes"] += o["Size"]
        b["t"] = min(b["t"], o["LastModified"].timestamp())
        if rel in live:
            b["live"] = True
    deleted = 0
    for bid, b in sorted(blocks.items(), key=lambda kv: kv[1]["t"]):
        if total <= cap_bytes:
            break
        if b["live"] or time.time() - b["t"] < min_age_s:
            continue
        for i in range(0, len(b["keys"]), 1000):
            s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in b["keys"][i:i + 1000]]})
        total -= b["bytes"]
        deleted += 1
    log(f"storage: {total / 1e9:.2f} GB under {prefix} (cap {cap_bytes / 1e9:.1f} GB), deleted {deleted} old block(s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("/hyperai/home/loop/puddle"))
    ap.add_argument("--prefix", default="puddle/")
    ap.add_argument("--block", type=int, default=4, help="scenes per published block (4 x 15 s = 1 minute)")
    ap.add_argument("--renders", type=int, default=2, help="Blender renders at once")
    ap.add_argument("--max-wait", type=int, default=180, help="publish a partial block if the oldest scene waited this long")
    ap.add_argument("--cap-gb", type=float, default=8.0)
    ap.add_argument("--image-every", type=int, default=600, help="seconds between MOSS image windows (0 = never)")
    ap.add_argument("--images-per-window", type=int, default=3)
    a = ap.parse_args()
    global LIB
    import backdrops
    LIB = backdrops.Library(a.root / "library")
    last_window = 0.0
    sys.path.insert(0, "/hyperai/home/ai-247")
    from newsbot import publish, r2
    s3_raw, bucket = r2.client(), r2.bucket()
    s3 = PrefixS3(s3_raw, a.prefix)
    inbox, done, failed, work = (a.root / d for d in ("inbox", "done", "failed", "work"))
    for d in (inbox, done, failed, work):
        d.mkdir(parents=True, exist_ok=True)
    log(f"channel worker: inbox {inbox}, bucket {bucket}/{a.prefix}, block {a.block}, renders {a.renders}")
    while not (a.root / "STOP").exists():
        scenes = sorted(inbox.glob("*.json"), key=lambda p: p.stat().st_mtime)
        oldest_wait = time.time() - scenes[0].stat().st_mtime if scenes else 0
        if len(scenes) < a.block and not (scenes and oldest_wait > a.max_wait):
            time.sleep(5)
            continue
        batch = scenes[: a.block]
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        bdir = work / ts
        t0 = time.time()
        clips = []
        with ThreadPoolExecutor(a.renders) as ex:
            futs = {p: ex.submit(render_clip, p, bdir / p.stem) for p in batch}
            for p, f in futs.items():
                try:
                    clips.append(f.result())
                    p.rename(done / p.name)
                except Exception as e:
                    log(f"FAILED {p.name}: {e!r}")
                    p.rename(failed / p.name)
        if not clips:
            continue
        t1 = time.time()
        try:
            make_block(clips, bdir)
            t2 = time.time()
            summary = publish.publish_many([bdir], s3, bucket, run_ts=ts)
            t3 = time.time()
        except Exception as e:
            log(f"BLOCK FAILED {ts}: {e!r} (work kept in {bdir})")
            time.sleep(10)
            continue
        log(f"ON AIR block {ts}: {len(clips)} scenes, {summary['fresh_minutes']} min fresh | render {t1 - t0:.0f}s "
            f"segment {t2 - t1:.0f}s upload {t3 - t2:.0f}s | cycle_start_k {summary['cycle_start_k']}")
        try:
            enforce_cap(s3_raw, bucket, a.prefix, int(a.cap_gb * 1e9))
        except Exception as e:
            log(f"cap check failed (will retry next block): {e!r}")
        shutil.rmtree(bdir, ignore_errors=True)
        # Blender is idle here: if the producer ordered images, give MOSS the GPU for a short window
        if a.image_every and LIB.pending() and time.time() - last_window > a.image_every:
            try:
                LIB.make_pending(a.images_per_window)
            except Exception as e:
                log(f"image window failed: {e!r}")
            last_window = time.time()
    log("stopped")


if __name__ == "__main__":
    main()
