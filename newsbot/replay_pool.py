"""Replay-pool bootstrap and refresh: publish `pool/manifest.json`, the loop the Worker falls back to when
`manifest.json` is missing, empty, stale or points at missing segments (see docs/FAILOVER.md). No notifier: run it
by hand (`python -m newsbot.replay_pool ...`) or from `.github/workflows/replay-pool.yml` (manual, plus a daily
cron that refreshes the pool from the newest episodes). The refresh is guarded: an existing good pool manifest is
never replaced by one with nothing playable or fewer than `--min-segments` segments (and nothing is written when
no complete episode exists), it is left untouched when the newest episodes are the ones it already lists, and an
existing pool that still verifies in R2 (every segment HEAD-checked) is not replaced by an *older* episode (e.g.
when the newest upload is truncated and `--from-r2` fell back). A skipped run writes the pool that stays live to
`--write`, so the job summary always shows what the Worker serves.

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
class PrefixedS3:
    """A boto3 S3 client seen through a channel prefix (e.g. Puddle Park's `puddle/` in the shared bucket): every Key
    and list Prefix gets the prefix, listed keys come back without it. So pool keys and segment uris stay relative to
    the Worker PREFIX, exactly as for ai-247 at the root, and nothing outside the prefix is read or written."""

    def __init__(self, s3, prefix: str):
        self.s3, self.p = s3, prefix

    def list_objects_v2(self, Bucket, Prefix, **kw):
        r = dict(self.s3.list_objects_v2(Bucket=Bucket, Prefix=self.p + Prefix, **kw))
        r["Contents"] = [{**o, "Key": o["Key"][len(self.p):]} for o in r.get("Contents", []) if o["Key"].startswith(self.p)]
        return r

    def get_object(self, Bucket, Key, **kw):
        return self.s3.get_object(Bucket=Bucket, Key=self.p + Key, **kw)

    def head_object(self, Bucket, Key, **kw):
        return self.s3.head_object(Bucket=Bucket, Key=self.p + Key, **kw)

    def put_object(self, Bucket, Key, **kw):
        return self.s3.put_object(Bucket=Bucket, Key=self.p + Key, **kw)

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        return self.s3.upload_file(filename, bucket, self.p + key, ExtraArgs=ExtraArgs)


def check_key_prefix(prefix: str) -> str:
    """'' (ai-247 at the bucket root) or a channel folder like `puddle/`; anything else is refused."""
    if prefix and (not prefix.endswith("/") or prefix.startswith("/") or ".." in prefix):
        raise SystemExit(f"--key-prefix must be empty or a folder like puddle/, not {prefix!r}")
    return prefix


def channel_client(prefix: str = ""):
    s3 = r2.client()
    return PrefixedS3(s3, prefix) if prefix else s3


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


def pool_usable(manifest) -> bool:
    """What the Worker's `layout()` accepts as a pool: at least one segment, every duration > 0, every uri set."""
    if not isinstance(manifest, dict):
        return False
    segs = _segments_of(manifest)
    return bool(segs) and all(s.get("uri") and float(s.get("duration") or 0) > 0 for s in segs)


def existing_pool(s3, bucket: str, pool_key: str = POOL_KEY) -> dict | None:
    """The pool manifest currently in R2, or None when it is missing or not JSON."""
    try:
        return _get_json(s3, bucket, pool_key)
    except Exception:
        return None


def segment_keys(manifest) -> list[str]:
    return [s["uri"] for s in _segments_of(manifest)] if isinstance(manifest, dict) else []


def newest_source_ts(manifest) -> str:
    """Newest `bulletins/<ts>/` timestamp a pool manifest loops (from its block ids `pool-<ts>`); "" if none."""
    ids = [str(b.get("id", "")).removeprefix("pool-") for b in (manifest or {}).get("blocks") or []]
    return max((i for i in ids if i), default="")


def verify_pool(s3, bucket: str, manifest) -> str | None:
    """HEAD every segment a pool manifest references: None when all exist with the recorded sizes, else the first
    problem. The Worker does not do this check itself (docs/FAILOVER.md, Limits)."""
    if not pool_usable(manifest):
        return "no playable segments"
    for s in _segments_of(manifest):
        size = _head_size(s3, bucket, s["uri"])
        if size is None:
            return f"missing {s['uri']}"
        if s.get("bytes") is not None and int(s["bytes"]) != size:
            return f"{s['uri']}: size {size} != manifest {s['bytes']}"
    return None


def refresh_decision(existing: dict | None, new: dict, force: bool = False, existing_problem: str | None = None,
                     min_segments: int = 1) -> tuple[bool, str]:
    """Guard for the scheduled refresh: (publish?, reason). A good pool in R2 is never replaced by a manifest with
    nothing playable or fewer than `min_segments` segments, is left alone (no PutObject) when the new one lists
    exactly the same segments, and is not replaced by an older episode while it still verifies in R2
    (`existing_problem` is what verify_pool() returned for it; a problem means it is replaced)."""
    n = len(segment_keys(new))
    if not pool_usable(new):
        return False, "new pool manifest has no playable segments; keeping the existing pool/manifest.json"
    if n < max(1, min_segments):
        return False, f"new pool manifest has {n} segment(s) < --min-segments {max(1, min_segments)}; keeping the existing pool/manifest.json"
    if force:
        return True, "forced"
    if not pool_usable(existing):
        return True, "no usable pool in R2 yet"
    if existing_problem:
        return True, f"existing pool is broken ({existing_problem})"
    if segment_keys(existing) == segment_keys(new):
        return False, f"unchanged: pool already lists these {n} segments (built_at {existing.get('built_at')})"
    new_ts, old_ts = newest_source_ts(new), newest_source_ts(existing)
    if new_ts and old_ts and new_ts < old_ts:
        return False, f"existing pool ({old_ts}) is newer than the candidate ({new_ts}) and still verifies in R2; keeping it"
    return True, "newer episodes available"


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
    ap.add_argument("--key-prefix", default="", help="channel folder in the bucket, e.g. puddle/ (the Worker PREFIX); every key is under it")
    ap.add_argument("--write", default="pool-manifest.json", help="also write the pool manifest to this local path")
    ap.add_argument("--upload", action="store_true", help="publish to R2 (needs R2_* env; otherwise only --write happens)")
    ap.add_argument("--force", action="store_true", help="--upload: rewrite the pool manifest even when it would list the same segments or an older episode")
    ap.add_argument("--min-segments", type=int, default=1, help="--upload: never publish a pool with fewer segments (exit 3, R2 untouched)")
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
            s3, bucket = channel_client(check_key_prefix(a.key_prefix)), r2.bucket()

    blocks, local_blocks, report, epoch, seg_s = [], [], {}, a.epoch, 6
    if a.from_r2 and s3:
        try:
            m, report = pool_from_r2(s3, bucket, a.bulletin_prefix, a.max_blocks, a.epoch)
        except RuntimeError as e:
            # Nothing complete to loop: leave whatever pool/manifest.json is already in R2 untouched.
            print(f"{e}; {a.pool_key} not touched")
            return 3
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
        existing = existing_pool(s3, bucket, a.pool_key)
        problem = verify_pool(s3, bucket, existing) if pool_usable(existing) else None
        if existing is not None:
            print(f"existing {a.pool_key}: {len(segment_keys(existing))} segments, built_at {existing.get('built_at')}, "
                  f"{'verifies in R2' if pool_usable(existing) and not problem else 'unusable: ' + str(problem or 'no playable segments')}")
        go, why = refresh_decision(existing, manifest, a.force, problem, a.min_segments)
        if not go:
            print(f"not uploading: {why}")
            if pool_usable(existing) and not problem:
                Path(a.write).write_text(json.dumps(existing, indent=1))  # what stays live, for the job summary
            return 3 if "min-segments" in why or "no playable" in why else 0
        written = publish(s3, bucket, manifest, local_blocks, a.pool_key)
        print(f"uploaded {len(written)} object(s) ({why}); {a.pool_key} written last")
    return 0


if __name__ == "__main__":
    sys.exit(main())
