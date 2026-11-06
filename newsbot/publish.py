"""Publish a rendered Day 1 episode to Cloudflare R2 in the layout the Day 2 Worker reads (docs/R2_LAYOUT.md,
Layout B; continuity fields per docs/MANIFEST-SWAP.md).

    python -m newsbot.publish out1        # after the render and its tests passed

Order of writes (the Worker must never see a manifest naming a missing key):
  1. bulletins/<ts>/seg_NNN.ts          video/mp2t      (every episode segment)
  2. bulletins/<ts>/manifest.json       application/json (per-bulletin provenance, after its segments)
  3. bulletins/<ts>/slate/slate_NNN.ts  video/mp2t, then bulletins/<ts>/slate/manifest.json
  4. manifest.json (bucket root)        application/json, ONE PutObject, written LAST

The root manifest's cycle is [this episode, slate, up to MAX_REPLAYS earlier bulletins already in R2 (taken from
the manifest that was live)], so replays never need re-uploading. Nothing is ever deleted or overwritten: every
run has a fresh `bulletins/<ts>/` prefix. Without the R2_* secrets this prints one line and exits 0.
Secrets are read by boto3 from the environment and are never printed.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import channel, r2

MAX_REPLAYS = 3
ROOT_MANIFEST = "manifest.json"
CONTENT_TYPES = {".ts": "video/mp2t", ".json": "application/json", ".m3u8": "application/vnd.apple.mpegurl"}


def _put_file(s3, bucket: str, path: Path, key: str, log: list[dict]) -> None:
    ct = CONTENT_TYPES[path.suffix]
    s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": ct})
    log.append({"key": key, "content_type": ct, "bytes": path.stat().st_size})
    print(f"put {key} ({ct}, {path.stat().st_size} bytes)", flush=True)


def _put_json(s3, bucket: str, obj: dict, key: str, log: list[dict]) -> None:
    body = json.dumps(obj, separators=(",", ":")).encode()
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")  # one atomic PUT
    log.append({"key": key, "content_type": "application/json", "bytes": len(body)})
    print(f"put {key} (application/json, {len(body)} bytes)", flush=True)


def read_current_manifest(s3, bucket: str) -> dict | None:
    """The root manifest now in R2, or None when there is none yet (first publish)."""
    try:
        r = s3.get_object(Bucket=bucket, Key=ROOT_MANIFEST)
    except Exception as e:  # botocore ClientError NoSuchKey / NotFound; a fake client may raise KeyError
        code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
        if code in ("NoSuchKey", "NotFound", "404", "KeyError"):
            return None
        raise
    return json.loads(r["Body"].read())


def _block(d: Path, kind: str, block_id: str, key_prefix: str, log: list[dict], s3, bucket: str) -> dict:
    """Upload one block's segments (manifest.json of the block after them) and return its channel entry."""
    m = json.loads((d / "manifest.json").read_text())
    segs = []
    for s in m["segments"]:
        _put_file(s3, bucket, d / s["file"], f"{key_prefix}/{s['file']}", log)
        segs.append({"uri": f"{key_prefix}/{s['file']}", "duration": round(float(s["duration"]), 3)})
    _put_file(s3, bucket, d / "manifest.json", f"{key_prefix}/manifest.json", log)
    return {"id": block_id, "kind": kind, "segments": segs}


def replay_blocks(cur: dict | None, max_replays: int = MAX_REPLAYS) -> list[dict]:
    """Earlier bulletins to keep in the loop: the live manifest's bulletin + replays, newest first."""
    if not cur:
        return []
    out = [b for b in cur.get("blocks", []) if b.get("kind") in ("bulletin", "replay") and b.get("segments")]
    return [{**b, "kind": "replay"} for b in out[:max_replays]]


def publish(out: Path, s3, bucket: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    prefix = f"bulletins/{ts}"
    log: list[dict] = []
    cur = read_current_manifest(s3, bucket)
    print(f"current root manifest: {'none (first publish)' if cur is None else f'cycle_start_k={cur.get('cycle_start_k', 0)} blocks={len(cur.get('blocks', []))}'}")

    live = _block(out / "episode", "bulletin", ts, prefix, log, s3, bucket)
    blocks = [live]
    if (out / "slate" / "manifest.json").exists():
        blocks.append(_block(out / "slate", "slate", f"{ts}/slate", f"{prefix}/slate", log, s3, bucket))
    blocks += replay_blocks(cur)

    root = channel.next_manifest(cur, blocks, now)
    root["published"] = ts
    _put_json(s3, bucket, root, ROOT_MANIFEST, log)  # last

    summary = {"prefix": prefix, "objects": len(log), "bytes": sum(x["bytes"] for x in log),
               "segments": sum(1 for x in log if x["key"].endswith(".ts")), "last_key": log[-1]["key"],
               "epoch": root["epoch"], "cycle_start_k": root["cycle_start_k"], "cycle_start_dseq": root["cycle_start_dseq"],
               "blocks": [(b["kind"], b["id"], len(b["segments"])) for b in blocks], "had_prev": "prev" in root,
               "keys": log}
    (out / "publish.json").write_text(json.dumps(summary, indent=1))
    print("PUBLISH", json.dumps({k: v for k, v in summary.items() if k != "keys"}))
    return summary


def main(argv=None) -> int:
    out = Path((argv or sys.argv[1:] or ["out1"])[0])
    if not (out / "episode" / "manifest.json").exists():
        print(f"no episode in {out}: nothing to publish", file=sys.stderr)
        return 2
    if not r2.r2_configured():
        print("R2 secrets not set: skipping R2 upload")
        return 0
    t = time.time()
    publish(out, r2.client(), r2.bucket())
    print(f"r2 publish: {time.time() - t:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
