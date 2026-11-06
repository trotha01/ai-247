"""Replay-pool bootstrap: publish `pool/manifest.json`, the loop the Worker falls back to when `manifest.json` is
missing, empty, stale or points at missing segments (see docs/FAILOVER.md). No cron, no notifier: run it once by
hand (`python -m newsbot.replay_pool ...`) or from the dispatch-only workflow `.github/workflows/replay-pool.yml`.

Two ways to build the pool:
  --from-r2        pick the newest bulletin/episode already in R2 (`bulletins/<ts>/manifest.json`) whose segments
                   are all present with the recorded sizes ("latest good episode"); the pool references those keys,
                   nothing is re-uploaded. Older incomplete uploads are skipped and listed in the report.
  --from-dir DIR   use a local render (the Day 0 bulletin artifact, or `out1/episode`): segments are sha256-checked
                   against the directory's manifest.json and uploaded under `pool/<id>/`, then the manifest last.

The pool manifest has the channel-manifest shape the Worker already reads (`blocks[].segments[].uri`), plus
`kind: "replay-pool"`, `built_at` and `built_from` for /healthz. `uri` is an R2 key relative to the Worker PREFIX.
Credentials are read from the R2_* environment variables only (never printed); without them the pool manifest is
written locally (`--write`) and nothing is uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from . import r2

POOL_KEY = "pool/manifest.json"
BULLETIN_PREFIX = "bulletins/"
CONTENT_TYPES = {".ts": "video/mp2t", ".json": "application/json", ".m3u8": "application/vnd.apple.mpegurl"}


# ---------------------------------------------------------------- building ------------------------------------
def _segments_of(manifest: dict) -> list[dict]:
    """Flatten the Day 0 shape ({segments:[{file}]}) or the channel shape ({blocks:[{segments:[{uri}]}]})."""
    if manifest.get("blocks"):
        return [dict(s) for b in manifest["blocks"] for s in b.get("segments", [])]
    return [dict(s) for s in manifest.get("segments", [])]


def block_from_dir(d: Path, block_id: str, key_prefix: str) -> dict:
    """One pool block from a local render directory. Every segment is sha256-checked against manifest.json."""
    m = json.loads((d / "manifest.json").read_text())
    segs = []
    for s in _segments_of(m):
        name = s.get("file") or Path(s["uri"]).name
        p = d / name
        if not p.exists():
            raise FileNotFoundError(f"{p} listed in {d / 'manifest.json'} is missing")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if s.get("sha256") and digest != s["sha256"]:
            raise ValueError(f"{p}: sha256 mismatch (corrupt render)")
        segs.append({"uri": f"{key_prefix}/{name}", "file": name, "duration": float(s["duration"]), "bytes": p.stat().st_size, "sha256": digest})
    if not segs:
        raise ValueError(f"{d}: no segments")
    return {"id": block_id, "kind": "replay", "segments": segs, "seconds": round(sum(s["duration"] for s in segs), 3),
            "local_dir": str(d), "segment_seconds": m.get("segment_seconds", 6)}


def build_pool_manifest(blocks: list[dict], epoch: int | None, built_from: dict, segment_seconds: int = 6) -> dict:
    if not blocks:
        raise ValueError("replay pool would be empty")
    out = {"version": 2, "kind": "replay-pool", "segment_seconds": segment_seconds,
           "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "built_from": built_from,
           "blocks": [{"id": b["id"], "kind": b.get("kind", "replay"), "seconds": b.get("seconds"),
                       "segments": [{k: s[k] for k in ("uri", "file", "duration", "bytes", "sha256") if k in s} for s in b["segments"]]}
                      for b in blocks]}
    if epoch is not None:
        out["epoch"] = int(epoch)
    return out


# ---------------------------------------------------------------- R2 side -------------------------------------
def client():
    """boto3 S3 client for R2 from the R2_* environment (same convention as newsbot/r2.py). Never logs them."""
    import boto3
    return boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def _list_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        keys += [o["Key"] for o in r.get("Contents", [])]
        if not r.get("IsTruncated"):
            return keys
        token = r.get("NextContinuationToken")


def _get_json(s3, bucket: str, key: str) -> dict:
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def _head_size(s3, bucket: str, key: str) -> int | None:
    try:
        return int(s3.head_object(Bucket=bucket, Key=key)["ContentLength"])
    except Exception:
        return None


def candidate_manifests(s3, bucket: str, prefix: str = BULLETIN_PREFIX) -> list[str]:
    """`<prefix><ts>/manifest.json` keys, newest first (timestamps sort lexically)."""
    keys = [k for k in _list_keys(s3, bucket, prefix) if k.endswith("/manifest.json") and k.count("/") == prefix.count("/") + 1]
    return sorted(keys, reverse=True)


def check_r2_episode(s3, bucket: str, manifest_key: str) -> dict:
    """Verify that every segment the per-bulletin manifest lists exists in R2 with the recorded size."""
    m = _get_json(s3, bucket, manifest_key)
    base = manifest_key.rsplit("/", 1)[0]
    segs, problems = [], []
    for s in _segments_of(m):
        name = s.get("file") or Path(s["uri"]).name
        key = s["uri"] if s.get("uri") and "/" in s["uri"] else f"{base}/{name}"
        size = _head_size(s3, bucket, key)
        if size is None:
            problems.append(f"missing {key}")
        elif s.get("bytes") is not None and int(s["bytes"]) != size:
            problems.append(f"{key}: size {size} != manifest {s['bytes']}")
        else:
            segs.append({"uri": key, "file": name, "duration": float(s["duration"]), "bytes": size, **({"sha256": s["sha256"]} if s.get("sha256") else {})})
    if not segs:
        problems.append("no segments")
    return {"manifest_key": manifest_key, "ok": not problems, "problems": problems, "segments": segs,
            "segment_seconds": m.get("segment_seconds", 6), "epoch": m.get("epoch")}


def pool_from_r2(s3, bucket: str, prefix: str = BULLETIN_PREFIX, max_blocks: int = 1, epoch: int | None = None) -> tuple[dict, dict]:
    """Newest complete episode(s) already in R2 -> pool manifest (no uploads). Returns (manifest, report)."""
    report = {"candidates": [], "skipped": []}
    blocks, seg_s, first_epoch = [], 6, None
    live_epoch = None
    try:
        live_epoch = _get_json(s3, bucket, "manifest.json").get("epoch")
    except Exception:
        pass
    for key in candidate_manifests(s3, bucket, prefix):
        report["candidates"].append(key)
        c = check_r2_episode(s3, bucket, key)
        if not c["ok"]:
            report["skipped"].append({"manifest_key": key, "problems": c["problems"][:5]})
            continue
        ts = key.rsplit("/", 2)[-2]
        blocks.append({"id": f"pool-{ts}", "kind": "replay", "segments": c["segments"], "seconds": round(sum(s["duration"] for s in c["segments"]), 3)})
        if len(blocks) == 1:
            seg_s, first_epoch = int(c["segment_seconds"]), c["epoch"]
        if len(blocks) >= max_blocks:
            break
    if not blocks:
        raise RuntimeError(f"no complete episode under {prefix} in R2; render one first or use --from-dir")
    if epoch is None:
        epoch = live_epoch if live_epoch is not None else first_epoch
    built_from = {"source": "r2", "manifest_keys": [f"{prefix}{b['id'].removeprefix('pool-')}/manifest.json" for b in blocks]}
    return build_pool_manifest(blocks, epoch, built_from, seg_s), report


def publish(s3, bucket: str, manifest: dict, local_blocks: list[dict] | None = None, pool_key: str = POOL_KEY) -> list[str]:
    """Upload local block segments (if any) under their pool keys, then the pool manifest LAST in one PutObject.
    Returns the keys written in order."""
    written = []
    for b in local_blocks or []:
        d = Path(b["local_dir"])
        for s in b["segments"]:
            s3.upload_file(str(d / s["file"]), bucket, s["uri"], ExtraArgs={"ContentType": CONTENT_TYPES[".ts"]})
            written.append(s["uri"])
    s3.put_object(Bucket=bucket, Key=pool_key, Body=json.dumps(manifest, indent=1).encode(), ContentType=CONTENT_TYPES[".json"])
    written.append(pool_key)
    return written


# ---------------------------------------------------------------- CLI -----------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from-r2", action="store_true", help="build from the newest complete episode already in R2")
    ap.add_argument("--from-dir", action="append", default=[], help="local render dir with manifest.json + segments (repeatable; each becomes a block)")
    ap.add_argument("--id", action="append", default=[], help="block id for each --from-dir (default: the dir name)")
    ap.add_argument("--bulletin-prefix", default=BULLETIN_PREFIX, help="R2 prefix holding <ts>/manifest.json uploads")
    ap.add_argument("--max-blocks", type=int, default=1, help="--from-r2: how many newest complete episodes to loop")
    ap.add_argument("--epoch", type=int, default=None, help="channel epoch (unix s); default: the live manifest's, if it has one")
    ap.add_argument("--pool-key", default=POOL_KEY)
    ap.add_argument("--write", default="pool-manifest.json", help="also write the pool manifest to this local path")
    ap.add_argument("--upload", action="store_true", help="publish to R2 (needs R2_* env; otherwise only --write happens)")
    a = ap.parse_args(argv)
    if not a.from_r2 and not a.from_dir:
        ap.error("choose --from-r2 and/or --from-dir DIR")

    s3 = bucket = None
    if a.from_r2 or a.upload:
        if not r2.r2_configured():
            if a.from_r2:
                print("R2 secrets not set: cannot read R2 (--from-r2); nothing done")
                return 2
            print("R2 secrets not set: skipping upload, writing the pool manifest locally only")
        else:
            s3, bucket = client(), os.environ["R2_BUCKET"]

    blocks, local_blocks, report, epoch, seg_s = [], [], {}, a.epoch, 6
    if a.from_r2 and s3:
        m, report = pool_from_r2(s3, bucket, a.bulletin_prefix, a.max_blocks, a.epoch)
        blocks, epoch, seg_s = list(m["blocks"]), m.get("epoch"), int(m["segment_seconds"])
    for i, d in enumerate(a.from_dir):
        d = Path(d)
        bid = a.id[i] if i < len(a.id) else d.name
        b = block_from_dir(d, f"pool-{bid}", f"pool/{bid}")
        local_blocks.append(b)
        blocks.append(b)
        if not a.from_r2:
            seg_s = int(b["segment_seconds"])
    built_from = {"source": "r2+dir" if a.from_r2 and a.from_dir else ("r2" if a.from_r2 else "dir"),
                  "dirs": [b["local_dir"] for b in local_blocks], **({"r2": report} if report else {})}
    manifest = build_pool_manifest(blocks, epoch, built_from, seg_s)
    Path(a.write).write_text(json.dumps(manifest, indent=1))
    n = sum(len(b["segments"]) for b in manifest["blocks"])
    print(f"pool manifest: {len(manifest['blocks'])} block(s), {n} segments, {sum(b.get('seconds') or 0 for b in manifest['blocks'])} s -> {a.write}")
    for sk in report.get("skipped", []):
        print(f"  skipped {sk['manifest_key']}: {'; '.join(sk['problems'])}")
    if a.upload and s3:
        written = publish(s3, bucket, manifest, local_blocks, a.pool_key)
        print(f"uploaded {len(written)} object(s); {a.pool_key} written last")
    return 0


if __name__ == "__main__":
    sys.exit(main())
