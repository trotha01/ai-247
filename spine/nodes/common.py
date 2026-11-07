"""Nodes every channel shares: join clips into a 6 s HLS block, and publish a block through newsbot.publish."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from spine.contract import Job


def check_prefix(prefix: str, channel_prefix: str) -> str:
    """A channel writes only under its own prefix ("" = the bucket root, owned by AI-247)."""
    if ".." in prefix or prefix.startswith("/") or (prefix and not prefix.endswith("/")):
        raise ValueError(f"bad prefix {prefix!r}")
    if not prefix.startswith(channel_prefix):
        raise ValueError(f"prefix {prefix!r} is outside the channel's {channel_prefix!r}")
    if channel_prefix == "" and prefix.split("/")[0] in ("lang", "puddle"):
        raise ValueError(f"prefix {prefix!r} belongs to another channel")
    return prefix


def segment_hls(job: Job):
    """in clip.mp4 (one per item) -> out/episode/{seg_NNN.ts,index.m3u8,manifest.json} (lang.channel_worker.make_block)."""
    from lang.channel_worker import make_block
    clips = job.inputs["clip.mp4"]
    clips = clips if isinstance(clips, list) else [clips]
    out = job.out("out")
    make_block([Path(c).resolve() for c in clips], out)
    n = len(json.loads((out / "episode" / "manifest.json").read_text())["segments"])
    return {"out": out}, f"{len(clips)} clip(s) -> {n} segments"


def publish(job: Job):
    """in out/ (list: one dir per item, each with episode/manifest.json) -> R2 under the channel prefix: segments
    first, root manifest last (newsbot.publish.publish_many). params: max_replays, cap_gb (delete old unreferenced
    blocks under the prefix), prefix (default: the channel's; a folder under it for shadow runs)."""
    outs = job.inputs["out"]
    outs = [Path(o) for o in (outs if isinstance(outs, list) else [outs])]
    outs = [o for o in outs if (o / "episode" / "manifest.json").exists()]
    if not outs:
        raise FileNotFoundError("no episode/manifest.json in any input")
    prefix = check_prefix(job.params.get("prefix", job.channel.get("prefix", "")), job.channel.get("prefix", ""))
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if job.channel.get("dry_run") or os.environ.get("SPINE_DRY_RUN"):
        (job.out("publish.json")).write_text(json.dumps({"dry_run": True, "prefix": prefix, "outs": [str(o) for o in outs]}))
        return {"publish.json": job.out("publish.json")}, f"dry-run: would publish {len(outs)} block(s) to {prefix!r}"
    from lang.channel_worker import PrefixS3, enforce_cap
    from newsbot import publish as pub, r2
    if not r2.r2_configured():
        raise RuntimeError("R2_* environment not set (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET)")
    raw, bucket = r2.client(), r2.bucket()
    s = pub.publish_many(outs, PrefixS3(raw, prefix), bucket, run_ts=ts, max_replays=int(job.params.get("max_replays", pub.MAX_REPLAYS)))
    keep = {k: v for k, v in s.items() if k != "keys"}
    job.out("publish.json").write_text(json.dumps(keep, indent=1))
    line = f"{prefix or '/'}{s['prefix']}: {s['segments']} segs, {s['fresh_minutes']} min fresh, cycle_start_k {s['cycle_start_k']}"
    if job.params.get("cap_gb"):
        try:
            enforce_cap(raw, bucket, prefix, int(float(job.params["cap_gb"]) * 1e9))
        except Exception as e:  # the block is on air; storage cleanup retries next block
            line += f" | cap check failed: {e!r}"[:200]
    return {"publish.json": job.out("publish.json")}, line
