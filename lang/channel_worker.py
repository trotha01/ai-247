#!/usr/bin/env python3
"""Language channel worker: lesson scripts in -> live stream out (the studio channel_worker model).

Loop:
  1. take up to BLOCK lesson scripts from ROOT/inbox (oldest first); publish a partial block if the oldest has
     waited MAX_WAIT seconds,
  2. render each (lang.render: cards in headless Chromium, Piper voices, ffmpeg) into a ~45 s clip; a lesson that
     fails goes to ROOT/failed and is skipped,
  3. join the clips into one block and cut 6 s HLS segments (closed 2 s GOP),
  4. publish with newsbot.publish.publish_many under PREFIX (default lang/): segments first, root manifest last,
     earlier blocks kept as replays,
  5. keep the prefix under CAP_GB (delete the oldest blocks the live manifest no longer references).

    python -m lang.channel_worker --root /srv/channels/lang/run --prefix lang/     # ROOT/lang/run of install.sh
    python -m lang.channel_worker --root /tmp/lang --max-blocks 25        # bounded test run, then exit
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lang import render  # noqa: E402

FPS = render.FPS


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class PrefixS3:
    """Wrap a boto3 S3 client so every Key gets a prefix (newsbot.publish writes bucket-root keys)."""

    def __init__(self, s3, prefix):
        self.s3, self.p = s3, prefix

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        return self.s3.upload_file(filename, bucket, self.p + key, ExtraArgs=ExtraArgs)

    def put_object(self, Bucket, Key, **kw):
        return self.s3.put_object(Bucket=Bucket, Key=self.p + Key, **kw)

    def get_object(self, Bucket, Key, **kw):
        return self.s3.get_object(Bucket=Bucket, Key=self.p + Key, **kw)


def normalize_r2_secret(env=os.environ) -> bool:
    """R2 secret access keys are 64 hex characters. A key pasted with dashes in it (seen on a box 2026-11-07:
    66 characters, two '-') signs requests wrongly (SignatureDoesNotMatch / 403). Drop the dashes only when what
    remains is exactly 64 hex characters; returns True if the value was changed. The value is never printed."""
    v = env.get("R2_SECRET_ACCESS_KEY", "")
    fixed = v.strip().replace("-", "")
    if fixed != v and len(fixed) == 64 and all(c in "0123456789abcdefABCDEF" for c in fixed):
        env["R2_SECRET_ACCESS_KEY"] = fixed
        return True
    return False


def check_prefix(prefix: str) -> str:
    """The language channel may write only under lang/ in the shared bucket (ai-247 owns the root, Puddle Park puddle/)."""
    if not (prefix == "lang/" or (prefix.startswith("lang/") and prefix.endswith("/"))) or ".." in prefix:
        raise SystemExit(f"--prefix must be lang/ or a folder under it, not {prefix!r}")
    return prefix


def make_block(clips: list[Path], block_dir: Path) -> Path:
    """Join clips and cut 6 s segments into block_dir/episode/ with the manifest newsbot.publish reads."""
    ep = block_dir / "episode"
    ep.mkdir(parents=True, exist_ok=True)
    lst = block_dir / "clips.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    joined = block_dir / "block.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(joined)], check=True)
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(joined),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-tune", "stillimage", "-g", str(FPS * 2),
                    "-keyint_min", str(FPS * 2), "-sc_threshold", "0",
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


def take_batch(inbox: Path, block: int, max_wait: float, now: float | None = None) -> list[Path]:
    """The scripts to render now: a full block, or a partial one once the oldest waited max_wait seconds."""
    now = time.time() if now is None else now
    scripts = sorted(inbox.glob("*.json"), key=lambda p: (p.stat().st_mtime, p.name))
    if not scripts:
        return []
    if len(scripts) >= block or now - scripts[0].stat().st_mtime > max_wait:
        return scripts[:block]
    return []


def referenced_keys(manifest: dict) -> set[str]:
    keys = set()
    for m in (manifest, manifest.get("prev") or {}):
        for b in m.get("blocks", []):
            for s in b.get("segments", []):
                keys.add(s["uri"])
    return keys


def enforce_cap(s3, bucket: str, prefix: str, cap_bytes: int, min_age_s: int = 3600, pool_keys: set[str] = frozenset()):
    """Delete whole old blocks under PREFIX/bulletins/ that neither the live manifest (with its prev) nor the replay
    pool references, oldest first, until the prefix is under cap_bytes. Blocks younger than min_age_s are kept."""
    cur = json.loads(s3.get_object(Bucket=bucket, Key=prefix + "manifest.json")["Body"].read())
    live = referenced_keys(cur)
    try:
        pool = json.loads(s3.get_object(Bucket=bucket, Key=prefix + "pool/manifest.json")["Body"].read())
        live |= {s["uri"] for b in pool.get("blocks", []) for s in b.get("segments", [])}
    except Exception:
        pass
    live |= set(pool_keys)
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


def pace_wait(fresh_seconds, ahead_s: float) -> float:
    """Seconds to wait so the unplayed fresh queue drains to ahead_s (rendering is ~4x faster than real time)."""
    try:
        return max(0.0, float(fresh_seconds) - ahead_s)
    except (TypeError, ValueError):
        return 0.0


def prune_local(root: Path, cap_bytes: int) -> int:
    """Keep ROOT under cap_bytes: delete the oldest leftover work/<block>/ folders (failed blocks keep theirs), then
    the oldest done/ and failed/ scripts. Returns how many paths were removed."""
    def size(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
    items = [p for d in ("work", "done", "failed") for p in (root / d).glob("*")]
    total = sum(size(p) for p in items)
    removed = 0
    for p in sorted(items, key=lambda p: p.stat().st_mtime):
        if total <= cap_bytes:
            break
        total -= size(p)
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        removed += 1
    return removed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True, help="channel state folder (inbox/, done/, work/ ...)")
    ap.add_argument("--prefix", default="lang/")
    ap.add_argument("--block", type=int, default=1, help="lessons per published block (1 lesson = ~45-60 s)")
    ap.add_argument("--max-wait", type=int, default=120, help="publish a partial block if the oldest script waited this long")
    ap.add_argument("--cap-gb", type=float, default=6.0)
    ap.add_argument("--local-cap-gb", type=float, default=3.0, help="cap on this machine's work/done/failed folders")
    ap.add_argument("--max-replays", type=int, default=30, help="earlier blocks kept looping behind the fresh one")
    ap.add_argument("--ahead-s", type=float, default=300,
                    help="pace to real time: after a publish, wait until at most this many seconds of fresh lessons are unplayed")
    ap.add_argument("--max-blocks", type=int, default=0, help="stop after this many published blocks (0 = run forever)")
    ap.add_argument("--dry-run", action="store_true", help="render and segment, do not upload")
    a = ap.parse_args(argv)
    check_prefix(a.prefix)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from newsbot import publish, r2
    s3_raw = bucket = s3 = None
    if not a.dry_run:
        if normalize_r2_secret():
            log("R2_SECRET_ACCESS_KEY had dashes in it: using it without them (64 hex characters)")
        if not r2.r2_configured():
            raise SystemExit("R2_* environment not set (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET)")
        s3_raw, bucket = r2.client(), r2.bucket()
        s3 = PrefixS3(s3_raw, a.prefix)
    inbox, done, failed, work = (a.root / d for d in ("inbox", "done", "failed", "work"))
    for d in (inbox, done, failed, work):
        d.mkdir(parents=True, exist_ok=True)
    log(f"lang worker: inbox {inbox}, bucket {bucket}/{a.prefix}, block {a.block}, max-wait {a.max_wait}s")
    published = 0
    while not (a.root / "STOP").exists():
        batch = take_batch(inbox, a.block, a.max_wait)
        if not batch:
            if a.max_blocks and not any(inbox.glob("*.json")):
                break  # bounded run: nothing left to render
            time.sleep(3)
            continue
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        bdir = work / ts
        t0 = time.time()
        clips = []
        for p in batch:
            try:
                sc = json.loads(p.read_text(encoding="utf-8"))
                clips.append(render.render_clip(sc, bdir / p.stem))
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
            if a.dry_run:
                summary = {"fresh_minutes": "dry-run", "cycle_start_k": "-"}
            else:
                summary = publish.publish_many([bdir], s3, bucket, run_ts=ts, max_replays=a.max_replays)
            t3 = time.time()
        except Exception as e:
            log(f"BLOCK FAILED {ts}: {e!r} (work kept in {bdir})")
            time.sleep(10)
            continue
        published += 1
        log(f"ON AIR block {ts}: {len(clips)} lesson(s), {summary['fresh_minutes']} min fresh | render {t1 - t0:.0f}s "
            f"segment {t2 - t1:.0f}s upload {t3 - t2:.0f}s | cycle_start_k {summary['cycle_start_k']}")
        if not a.dry_run:
            try:
                enforce_cap(s3_raw, bucket, a.prefix, int(a.cap_gb * 1e9))
            except Exception as e:
                log(f"cap check failed (will retry next block): {e!r}")
            shutil.rmtree(bdir, ignore_errors=True)
        wait = pace_wait(summary.get("fresh_seconds"), a.ahead_s)
        if wait and not a.max_blocks:
            log(f"{summary['fresh_seconds']:.0f} s of fresh lessons queued: waiting {wait:.0f} s (real-time pacing)")
            end = time.time() + wait
            while time.time() < end and not (a.root / "STOP").exists():
                time.sleep(min(10, end - time.time()))
        if prune_local(a.root, int(a.local_cap_gb * 1e9)):
            log(f"local cache over {a.local_cap_gb} GB: pruned oldest work/done/failed")
        if a.max_blocks and published >= a.max_blocks:
            break
    log("stopped")


if __name__ == "__main__":
    main()
