"""Replay pool builder: keeps the most recent rendered episodes so the channel can replay them, and always
offers the slate as the last resort. `channel_blocks` never returns an empty list (the stream cannot go dark)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MAX_REPLAYS = 3


def _seg_list(d: Path, prefix: str):
    """uri is namespaced by the block id so segments of different episodes never collide in one playlist."""
    m = json.loads((d / "manifest.json").read_text())
    return [{"file": s["file"], "uri": f"{prefix}/{s['file']}", "duration": s["duration"], "sha256": s["sha256"]} for s in m["segments"]]


def build_pool(episode_dirs: list[Path], slate_dir: Path | None, max_replays: int = MAX_REPLAYS) -> dict:
    """episode_dirs: directories containing a manifest.json (newest first). Invalid/missing ones are skipped
    and the reason is recorded; segments are verified against their sha256 so a corrupt replay cannot air."""
    pool = {"episodes": [], "skipped": [], "slate": None}
    for d in episode_dirs:
        d = Path(d)
        try:
            segs = _seg_list(d, d.name)
            for s in segs:
                if hashlib.sha256((d / s["file"]).read_bytes()).hexdigest() != s["sha256"]:
                    raise ValueError(f"hash mismatch {s['uri']}")
            pool["episodes"].append({"id": d.name, "dir": str(d), "segments": segs,
                                     "seconds": round(sum(s["duration"] for s in segs), 3)})
        except Exception as e:
            pool["skipped"].append({"dir": str(d), "reason": f"{type(e).__name__}: {str(e)[:100]}"})
        if len(pool["episodes"]) >= max_replays + 1:
            break
    if slate_dir is not None and (Path(slate_dir) / "manifest.json").exists():
        sd = Path(slate_dir)
        pool["slate"] = {"id": "slate", "dir": str(sd), "segments": _seg_list(sd, "slate")}
    return pool


def channel_blocks(pool: dict, live_episode_id: str | None = None) -> list[dict]:
    """One loop of the channel: [live episode, slate, replay 1, replay 2, ...]. Falls back to slate-only,
    and raises only if there is neither an episode nor a slate (a build error, caught by tests)."""
    eps, slate = pool["episodes"], pool.get("slate")
    blocks = []
    if eps:
        first = next((e for e in eps if e["id"] == live_episode_id), eps[0])
        blocks.append({"kind": "bulletin", **first})
        if slate:
            blocks.append({"kind": "slate", **slate})
        blocks += [{"kind": "replay", **e} for e in eps if e is not first]
    elif slate:
        blocks.append({"kind": "slate", **slate})
    if not blocks:
        raise RuntimeError("no episode and no slate: the channel would go dark")
    return blocks
