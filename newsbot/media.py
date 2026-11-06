"""ffprobe-based segment facts used by the seam checks (parameters, GOP, timestamps, A/V alignment)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _probe(args):
    r = subprocess.run(["ffprobe", "-v", "error", "-of", "json", *args], check=True, capture_output=True, text=True)
    return json.loads(r.stdout)


def probe_segment(path: Path) -> dict:
    """Everything the seam tests need about one .ts file, from one ffprobe call."""
    info = _probe(["-show_streams", "-show_packets", "-show_entries",
                   "stream=index,codec_type,codec_name,profile,width,height,pix_fmt,r_frame_rate,sample_rate,channels,channel_layout,time_base:"
                   "packet=stream_index,pts_time,dts_time,duration_time,flags", str(path)])
    streams = {s["codec_type"]: s for s in info["streams"]}
    v, a = streams["video"], streams["audio"]
    pk = {"video": [], "audio": []}
    for p in info["packets"]:
        kind = "video" if p["stream_index"] == v["index"] else "audio"
        pk[kind].append({"pts": float(p["pts_time"]), "dts": float(p["dts_time"]), "dur": float(p.get("duration_time", 0) or 0),
                         "key": "K" in p.get("flags", "")})
    vp, ap = pk["video"], pk["audio"]

    def span(pp):
        return {"start": min(x["pts"] for x in pp), "end": max(x["pts"] + x["dur"] for x in pp)}
    vs, as_ = span(vp), span(ap)
    sig = {"v_codec": v["codec_name"], "v_profile": v.get("profile"), "w": v["width"], "h": v["height"],
           "pix_fmt": v["pix_fmt"], "fps": v["r_frame_rate"],
           "a_codec": a["codec_name"], "a_profile": a.get("profile"), "a_rate": a["sample_rate"], "a_channels": a["channels"]}
    keys = [x["pts"] for x in vp if x["key"]]
    return {"path": str(path), "sig": sig, "v": vs, "a": as_, "keys": keys, "frames": len(vp),
            "v_dts_strict": all(b["dts"] > x["dts"] for x, b in zip(vp, vp[1:])),
            "a_dts_strict": all(b["dts"] > x["dts"] for x, b in zip(ap, ap[1:])),
            "pts_ge_dts": all(x["pts"] >= x["dts"] - 1e-9 for x in vp + ap),
            "leading_pictures": _leading(vp),
            "sei_closed_gop": b"open_gop=0" in Path(path).read_bytes()[:400_000]}  # x264 writes this SEI once, at stream start


def _leading(vp) -> bool:
    """Closed-GOP check in decode order: no picture after a keyframe is presented before that keyframe."""
    key = None
    for p in vp:
        if p["key"]:
            key = p["pts"]
        elif key is not None and p["pts"] < key - 1e-9:
            return True
    return False


VIDEO_TOL, AUDIO_TOL = 0.002, 0.030


def joins_continuously(prev: dict, nxt: dict) -> bool:
    """True if `nxt` can follow `prev` with NO EXT-X-DISCONTINUITY: identical parameters and the
    timestamps continue where the previous segment ended (video within 2 ms, audio within one AAC frame + slack)."""
    if prev["sig"] != nxt["sig"]:
        return False
    return abs(nxt["v"]["start"] - prev["v"]["end"]) <= VIDEO_TOL and abs(nxt["a"]["start"] - prev["a"]["end"]) <= AUDIO_TOL


def concat_drift(infos: list[dict]) -> dict:
    """A/V alignment of the segments played back to back: offset (audio start - video start) at the start of
    the first segment vs the offset implied at the end of the last. Drift = their difference."""
    first, last = infos[0], infos[-1]
    start_off = first["a"]["start"] - first["v"]["start"]
    end_off = last["a"]["end"] - last["v"]["end"]
    v_len = last["v"]["end"] - first["v"]["start"]
    a_len = last["a"]["end"] - first["a"]["start"]
    return {"start_offset_s": round(start_off, 4), "end_offset_s": round(end_off, 4),
            "drift_s": round(abs(end_off - start_off), 4), "video_seconds": round(v_len, 3), "audio_seconds": round(a_len, 3)}
