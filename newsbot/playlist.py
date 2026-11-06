"""Rolling 'fake-live' media playlist generator (prototype of the Day 2 Worker logic) + checker."""
from __future__ import annotations

import math
import re


def rolling_playlist(manifest: dict, now: float, window: int = 5, epoch: float = 0.0, base_url: str = "") -> str:
    """Playlist for wall-clock `now`: the bulletin loops forever; the clock picks the live edge.

    Global segment number k = floor((now - epoch) / seg). Segment k plays manifest[k % n].
    A wrap (k % n == 0, k > 0) is a timestamp reset in the looped media, so it is tagged
    EXT-X-DISCONTINUITY, and EXT-X-DISCONTINUITY-SEQUENCE counts the tagged segments that
    already scrolled out of the window.
    """
    segs, seg = manifest["segments"], manifest["segment_seconds"]
    n = len(segs)
    live = int((now - epoch) // seg)
    first = max(0, live - window + 1)
    disc_seq = (first - 1) // n if first >= 1 else 0
    target = math.ceil(max(s["duration"] for s in segs))
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{target}",
             f"#EXT-X-MEDIA-SEQUENCE:{first}", f"#EXT-X-DISCONTINUITY-SEQUENCE:{disc_seq}"]
    for k in range(first, live + 1):
        s = segs[k % n]
        if k > 0 and k % n == 0:
            lines.append("#EXT-X-DISCONTINUITY")
        lines += [f"#EXTINF:{s['duration']:.3f},", f"{base_url}{s['file']}"]
    return "\n".join(lines) + "\n"


def parse(text: str) -> dict:
    d = {"target": None, "seq": None, "dseq": 0, "segs": [], "endlist": False}
    pending_disc, dur = False, None
    for ln in (l.strip() for l in text.splitlines()):
        if ln.startswith("#EXT-X-TARGETDURATION:"):
            d["target"] = int(ln.split(":")[1])
        elif ln.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            d["seq"] = int(ln.split(":")[1])
        elif ln.startswith("#EXT-X-DISCONTINUITY-SEQUENCE:"):
            d["dseq"] = int(ln.split(":")[1])
        elif ln == "#EXT-X-DISCONTINUITY":
            pending_disc = True
        elif ln == "#EXT-X-ENDLIST":
            d["endlist"] = True
        elif ln.startswith("#EXTINF:"):
            dur = float(ln[8:].split(",")[0])
        elif ln and not ln.startswith("#"):
            d["segs"].append({"uri": ln, "dur": dur, "disc": pending_disc})
            pending_disc, dur = False, None
    return d


def check_media_playlist(text: str, expect_seg_seconds: float | None = 6.0, tol: float = 0.05) -> list[str]:
    """Return a list of problems (empty = valid)."""
    errs = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "#EXTM3U":
        errs.append("missing #EXTM3U first line")
    d = parse(text)
    if d["target"] is None:
        errs.append("missing EXT-X-TARGETDURATION")
    if d["seq"] is None and not d["endlist"]:
        errs.append("missing EXT-X-MEDIA-SEQUENCE")
    if not d["segs"]:
        errs.append("no segments")
    for i, s in enumerate(d["segs"]):
        if s["dur"] is None:
            errs.append(f"segment {i} ({s['uri']}) has no EXTINF")
            continue
        if d["target"] is not None and round(s["dur"]) > d["target"]:
            errs.append(f"segment {i} duration {s['dur']} rounds above TARGETDURATION {d['target']}")
        if expect_seg_seconds and abs(s["dur"] - expect_seg_seconds) > tol:
            errs.append(f"segment {i} duration {s['dur']} not {expect_seg_seconds}+/-{tol}")
    if d["dseq"] < 0 or (d["seq"] is not None and d["seq"] < 0):
        errs.append("negative sequence number")
    return errs


def check_continuity(earlier: str, later: str) -> list[str]:
    """Two fetches of a live playlist must keep media/discontinuity sequence numbers consistent."""
    a, b = parse(earlier), parse(later)
    errs = []
    if b["seq"] < a["seq"]:
        errs.append("MEDIA-SEQUENCE went backwards")
    if b["dseq"] < a["dseq"]:
        errs.append("DISCONTINUITY-SEQUENCE went backwards")
    # same absolute segment number must have same uri
    ua = {a["seq"] + i: s["uri"] for i, s in enumerate(a["segs"])}
    ub = {b["seq"] + i: s["uri"] for i, s in enumerate(b["segs"])}
    for k in ua.keys() & ub.keys():
        if ua[k] != ub[k]:
            errs.append(f"segment {k} changed uri")
    # discontinuities seen in `a` that scrolled out must be reflected in b's DISCONTINUITY-SEQUENCE
    removed_disc = sum(1 for i, s in enumerate(a["segs"]) if s["disc"] and a["seq"] + i < b["seq"])
    if b["dseq"] != a["dseq"] + removed_disc:
        errs.append(f"DISCONTINUITY-SEQUENCE {b['dseq']} != {a['dseq']} + {removed_disc} removed")
    return errs
