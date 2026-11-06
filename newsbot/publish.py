"""Publish rendered episodes to Cloudflare R2 in the layout the Worker reads (docs/R2_LAYOUT.md, Layout B;
continuity fields per docs/MANIFEST-SWAP.md, "Fresh footage first").

    python -m newsbot.publish out1                          # one episode (day1-episode), after its tests passed
    python -m newsbot.publish --run-ts 20261106T152300Z out_s0 out_s1 ... out_s5   # hourly run: several bulletins

Order of writes (the Worker must never see a manifest naming a missing key):
  1. bulletins/<id>/seg_NNN.ts          video/mp2t      (every segment of every bulletin; uploads run in parallel)
  2. bulletins/<id>/manifest.json       application/json (per-bulletin provenance incl. `sources`, after its segments)
  3. bulletins/<id>/slate/slate_NNN.ts  video/mp2t, then bulletins/<id>/slate/manifest.json (first bulletin only)
  4. manifest.json (bucket root)        application/json, ONE PutObject, written LAST

`<id>` is the run timestamp, plus `-NN` (slice number) when a run publishes several bulletins. The root manifest's
blocks are [fresh bulletins of this run in order, slate, up to MAX_REPLAYS earlier bulletins already in R2 (taken
from the manifest that was live, newest first)] with `loop_from` = the number of fresh blocks: the Worker plays the
fresh blocks once, then loops slate + replays until the next publish. If the manifest in R2 has not started playing
yet (two publishes within the swap margin), its fresh blocks are inherited in front of ours, so no fresh footage is
ever dropped. Replays are never re-uploaded; nothing is ever deleted or overwritten. Without the R2_* secrets this
prints one line and exits 0. Secrets are read by boto3 from the environment and are never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import channel, r2

MAX_REPLAYS = 6          # one hour of 10-minute bulletins in the fallback loop
UPLOAD_THREADS = 12      # R2 PUTs take ~1.3 s each sequentially (144 s for 108 objects on run 42235237153)
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


def _block(d: Path, kind: str, block_id: str, key_prefix: str, log: list[dict], s3, bucket: str, threads: int = UPLOAD_THREADS) -> dict:
    """Upload one block's segments in parallel, then its manifest.json, and return its channel entry."""
    m = json.loads((d / "manifest.json").read_text())
    segs = [{"uri": f"{key_prefix}/{s['file']}", "duration": round(float(s["duration"]), 3)} for s in m["segments"]]
    with ThreadPoolExecutor(max_workers=max(1, threads)) as ex:
        list(ex.map(lambda s: _put_file(s3, bucket, d / s["file"], f"{key_prefix}/{s['file']}", log), m["segments"]))
    _put_file(s3, bucket, d / "manifest.json", f"{key_prefix}/manifest.json", log)  # after every segment of the block
    return {"id": block_id, "kind": kind, "segments": segs}


def replay_blocks(cur: dict | None, max_replays: int = MAX_REPLAYS, skip: list[dict] | None = None) -> list[dict]:
    """Earlier bulletins to keep in the fallback loop: the live manifest's bulletins + replays, newest first, minus
    `skip` (fresh blocks of a pending manifest that are inherited instead)."""
    if not cur:
        return []
    skip_ids = {b.get("id") for b in (skip or [])}
    out = [b for b in cur.get("blocks", []) if b.get("kind") in ("bulletin", "replay") and b.get("segments") and b.get("id") not in skip_ids]
    return [{**b, "kind": "replay"} for b in out[:max_replays]]


def publish_many(outs: list[Path], s3, bucket: str, now: float | None = None, run_ts: str | None = None,
                 max_replays: int = MAX_REPLAYS, threads: int = UPLOAD_THREADS) -> dict:
    """Upload the episodes in `outs` (slice order) as this run's fresh blocks and publish the root manifest last."""
    now = time.time() if now is None else now
    ts = run_ts or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    multi = len(outs) > 1
    log: list[dict] = []
    cur = read_current_manifest(s3, bucket)
    print(f"current root manifest: {'none (first publish)' if cur is None else f'cycle_start_k={cur.get('cycle_start_k', 0)} loop_from={cur.get('loop_from', 0)} blocks={len(cur.get('blocks', []))}'}")

    fresh = []
    for i, out in enumerate(outs):
        bid = f"{ts}-{i:02d}" if multi else ts
        fresh.append(_block(Path(out) / "episode", "bulletin", bid, f"bulletins/{bid}", log, s3, bucket, threads))
    first = fresh[0]["id"]
    blocks = list(fresh)
    if (Path(outs[0]) / "slate" / "manifest.json").exists():
        blocks.append(_block(Path(outs[0]) / "slate", "slate", f"{first}/slate", f"bulletins/{first}/slate", log, s3, bucket, threads))

    inherited = [b for b in channel.fresh_blocks(cur) if b.get("kind") == "bulletin"] if channel.pending(cur, now) else []
    if inherited:
        print(f"manifest in R2 has not started yet: inheriting its {len(inherited)} fresh block(s) in front of ours")
    blocks = inherited + blocks + replay_blocks(cur, max_replays, skip=inherited)
    loop_from = len(inherited) + len(fresh)
    if loop_from >= len(blocks):  # no slate and nothing to replay (a first publish without a slate): loop the fresh blocks
        print("no slate and no replays: the fresh blocks loop (loop_from 0)")
        loop_from = 0

    root = channel.next_manifest(cur, blocks, now, loop_from=loop_from)
    root["published"] = ts
    _put_json(s3, bucket, root, ROOT_MANIFEST, log)  # last

    rendered_s = sum(s["duration"] for b in fresh for s in b["segments"])
    fresh_s = rendered_s + sum(s["duration"] for b in inherited for s in b["segments"])  # also right when loop_from fell back to 0
    summary = {"prefix": f"bulletins/{first}", "run_ts": ts, "objects": len(log), "bytes": sum(x["bytes"] for x in log),
               "segments": sum(1 for x in log if x["key"].endswith(".ts")), "last_key": log[-1]["key"],
               "epoch": root["epoch"], "cycle_start_k": root["cycle_start_k"], "cycle_start_dseq": root["cycle_start_dseq"],
               "loop_from": loop_from, "fresh_blocks": loop_from, "inherited_blocks": len(inherited),
               "fresh_seconds": round(fresh_s, 3), "fresh_minutes": round(fresh_s / 60, 2),
               "rendered_minutes": round(rendered_s / 60, 2),  # this run's bulletins only (fresh_minutes adds inherited ones)
               "blocks": [(b["kind"], b["id"], len(b["segments"])) for b in blocks], "had_prev": "prev" in root,
               "keys": log}
    for out in outs:
        (Path(out) / "publish.json").write_text(json.dumps(summary, indent=1))
    print("PUBLISH", json.dumps({k: v for k, v in summary.items() if k != "keys"}))
    return summary


def publish(out: Path, s3, bucket: str, now: float | None = None) -> dict:
    """One episode (the day1-episode path): bulletins/<ts>/, blocks [bulletin, slate, replays], loop_from 1."""
    return publish_many([Path(out)], s3, bucket, now)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("outs", nargs="*", default=["out1"], help="render output dir(s) in airing order (each holds episode/manifest.json)")
    ap.add_argument("--run-ts", default=None, help="shared id for a multi-bulletin run (default: publish time)")
    ap.add_argument("--max-replays", type=int, default=MAX_REPLAYS)
    ap.add_argument("--threads", type=int, default=UPLOAD_THREADS)
    a = ap.parse_args(argv)
    outs = []
    for o in a.outs:
        if (Path(o) / "episode" / "manifest.json").exists():
            outs.append(Path(o))
        else:
            print(f"no episode in {o}: skipped", file=sys.stderr)
    if not outs:
        print("nothing to publish", file=sys.stderr)
        return 2
    if not r2.r2_configured():
        print("R2 secrets not set: skipping R2 upload")
        return 0
    t = time.time()
    publish_many(outs, r2.client(), r2.bucket(), run_ts=a.run_ts, max_replays=a.max_replays, threads=a.threads)
    print(f"r2 publish: {time.time() - t:.1f} s ({len(outs)} bulletin(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
