"""Channel manifest math for the Day 1 uploader: a Python port of the swap reference in worker/src/playlist.js
(`eras`, `tagsBeforeEras`, `nextSwapStart`, `swapDseq`). Contract: docs/MANIFEST-SWAP.md. Pure functions, no I/O.

A root manifest.json carries `epoch` (fixed forever), `segment_seconds`, `blocks`, `cycle_start_k` (global segment
number at which its cycle[0] plays), `cycle_start_dseq` (EXT-X-DISCONTINUITY-SEQUENCE at that point) and `prev`
(the manifest it replaced). The Worker plays `prev` for k < cycle_start_k, so a new manifest only takes effect at a
loop boundary of the old one and sequence numbers never go backwards.
"""
from __future__ import annotations

import math

# Must equal EPOCH in worker/wrangler.toml (the Worker's fallback). Set once; never change it after launch.
EPOCH = 1793000000
SEGMENT_SECONDS = 6
MARGIN = 10  # segments of lead (60 s): Worker manifest cache 10 s + R2 propagation + 5-segment client window


def layout(manifest: dict) -> tuple[list[dict], set[int]]:
    """Flatten blocks -> (segments, block-start indexes). Accepts the Day 0 shape ({segments:[{file,duration}]})."""
    blocks = manifest.get("blocks") or [{"id": "main", "segments": manifest.get("segments", [])}]
    segs, starts = [], set()
    for b in blocks:
        if not b.get("segments"):
            continue
        starts.add(len(segs))
        for s in b["segments"]:
            segs.append({"uri": s.get("uri", s.get("file")), "duration": float(s["duration"])})
    if not segs:
        raise ValueError("manifest has no segments")
    if any(not s["duration"] > 0 for s in segs):
        raise ValueError("bad segment duration")
    return segs, starts


def _tags_up_to(c: int, n: int, starts: set[int]) -> int:
    """Discontinuity-tagged local indexes in [0, c). Same arithmetic as the JS reference for negative c
    (Math.floor for the quotient, truncated `%` for the remainder), so an unanchored era extended backwards
    gives identical numbers to the Worker."""
    return math.floor(c / n) * len(starts) + sum(1 for b in starts if b < math.fmod(c, n))


def _tagged_in(e: dict, lo: int, hi: int) -> int:
    if hi <= lo:
        return 0
    return _tags_up_to(hi - e["start"], e["n"], e["starts"]) - _tags_up_to(lo - e["start"], e["n"], e["starts"])


def eras(manifest: dict) -> list[dict]:
    chain = []
    m = manifest
    while m:
        chain.insert(0, m)
        m = m.get("prev")
    out = []
    for m in chain:
        segs, starts = layout(m)
        start = int(m.get("cycle_start_k", 0))
        if start < 0:
            raise ValueError("bad cycle_start_k")
        anchor = m.get("cycle_start_dseq")
        if anchor is not None and (not isinstance(anchor, int) or anchor < 0):
            raise ValueError("bad cycle_start_dseq")
        out.append({"start": start, "segs": segs, "starts": starts, "n": len(segs), "anchor": anchor})
    for i in range(1, len(out)):
        if out[i]["start"] <= out[i - 1]["start"]:
            raise ValueError("cycle_start_k must increase along prev chain")
    for i, e in enumerate(out):
        if e["anchor"] is not None:
            e["base"] = e["anchor"]
        elif i == 0:
            e["base"] = _tagged_in(e, 1, e["start"])
        else:
            p = out[i - 1]
            e["base"] = p["base"] + _tagged_in(p, max(p["start"], 1), e["start"])
    return out


def _era_for(es: list[dict], k: int) -> dict:
    e = es[0]
    for x in es:
        if x["start"] <= k:
            e = x
    return e


def tags_before_eras(first: int, es: list[dict]) -> int:
    """EXT-X-DISCONTINUITY-SEQUENCE for a window starting at `first` (segment 0 is never tagged)."""
    if first <= 0:
        return 0
    e = _era_for(es, first)
    if first < e["start"]:
        return 0
    return e["base"] + _tagged_in(e, max(e["start"], 1), first)


def live_k(now: float, epoch: int = EPOCH, seg_seconds: int = SEGMENT_SECONDS) -> int:
    return max(0, int(math.floor((now - epoch) / seg_seconds)))


def next_swap_start(cur: dict | None, publish_k: int, margin: int = MARGIN) -> int:
    """`cycle_start_k` for a manifest published while segment `publish_k` is live and `cur` is the manifest in R2."""
    if not cur:
        return publish_k + margin
    e = eras(cur)[-1]
    want = publish_k + margin
    if e["start"] > want:
        return e["start"]  # cur has not started yet: replace it at its own boundary
    return e["start"] + e["n"] * math.ceil((want - e["start"]) / e["n"])


def swap_dseq(cur: dict | None, start: int) -> int:
    return tags_before_eras(start, eras(cur)) if cur else 0


def next_manifest(cur: dict | None, blocks: list[dict], now: float, epoch: int = EPOCH, margin: int = MARGIN) -> dict:
    """The root manifest to publish: `blocks` is the new cycle; continuity fields follow docs/MANIFEST-SWAP.md."""
    epoch = int(cur.get("epoch", epoch)) if cur else epoch  # the published epoch wins: it must never change
    k = live_k(now, epoch)
    start = next_swap_start(cur, k, margin)
    m = {"version": 2, "segment_seconds": SEGMENT_SECONDS, "epoch": epoch, "cycle_start_k": start,
         "cycle_start_dseq": swap_dseq(cur, start), "blocks": blocks}
    if cur:
        if int(cur.get("cycle_start_k", 0)) > k + margin:
            prev = cur.get("prev")  # cur never started: it is replaced, its predecessor stays the live one
        else:
            prev = {k2: v for k2, v in cur.items() if k2 != "prev"}
        if prev:
            m["prev"] = prev
    return m
