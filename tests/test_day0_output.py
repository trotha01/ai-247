"""Day 0 acceptance tests (a)-(d) against a rendered bulletin directory (NEWSBOT_OUT, default out/)."""
import hashlib
import json
import subprocess

from newsbot import script as scriptmod


def ffprobe(args):
    r = subprocess.run(["ffprobe", "-v", "error", "-of", "json", *args], check=True, capture_output=True, text=True)
    return json.loads(r.stdout)


def test_a_codec_params_and_duration(out, manifest):
    segs = sorted(out.glob("seg_*.ts"))
    assert len(segs) == 10
    for p in segs:
        info = ffprobe(["-show_streams", "-show_format", str(p)])
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert v["codec_name"] == "h264" and (v["width"], v["height"]) == (1280, 720), p
        assert v["r_frame_rate"] == "30/1", p
        assert v["pix_fmt"] == "yuv420p"
        assert a["codec_name"] == "aac" and a["sample_rate"] == "48000" and a["channels"] == 1, p
        # video-stream duration is the segment duration (equals EXTINF); AAC packet boundaries make the
        # audio stream (HLS muxer interleave shifts audio packets across the cut) and the container span (earliest start to latest end) differ by a few frames.
        assert abs(float(v["duration"]) - 6.0) <= 0.05, (p, v["duration"])
        assert abs(float(a["duration"]) - 6.0) <= 0.5, (p, a["duration"])
        assert abs(float(info["format"]["duration"]) - 6.0) <= 0.10, (p, info["format"]["duration"])


def test_a_closed_gop_every_2s(out):
    for p in sorted(out.glob("seg_*.ts")):
        frames = ffprobe(["-select_streams", "v", "-show_entries", "frame=key_frame,pts_time",
                          "-show_frames", str(p)])["frames"]
        keys = [float(f["pts_time"]) for f in frames if f["key_frame"] == 1]
        base = float(frames[0]["pts_time"])
        assert len(frames) == 180, (p, len(frames))
        assert len(keys) == 3, (p, keys)
        gaps = [round(b - a, 2) for a, b in zip(keys, keys[1:])]
        assert all(abs(g - 2.0) < 0.05 for g in gaps), (p, gaps)
        assert abs(keys[0] - base) < 1e-3, "segment must start on a keyframe"
        # closed GOP: in decode order nothing after a keyframe is presented before it (no leading pictures)
        for i, f in enumerate(frames):
            if f["key_frame"] == 1:
                assert all(float(g["pts_time"]) >= float(f["pts_time"]) for g in frames[i:i + 60]), (p, i)
    assert b"open_gop=0" in (out / "seg_000.ts").read_bytes(), "x264 SEI does not say closed-GOP"


def test_b_no_unsupported_numbers_or_entities(script):
    assert script["stories"], "no stories"
    assert scriptmod.check_script(script) == {}
    for s in script["stories"]:  # headline/quote must come from the source text itself
        assert scriptmod.missing_terms(s["headline"] + " " + s["quote"].replace("...", " "), s["source_text"]) == []


def test_c_every_claim_has_visible_citation_card(plan, script):
    for i, sc in enumerate(plan):
        if sc["kind"] == "headline":
            nxt = plan[i + 1]
            assert nxt["kind"] == "citation" and nxt["story"] == sc["story"]
            c = nxt["citation"]
            assert c["source"] and c["url"].startswith("http") and c == sc["citation"]
            assert c["url"] == script["stories"][sc["story"]]["url"]
        if sc["kind"] == "chart":
            assert sc["chart"]["source"]  # chart carries its own visible source line
    # ticker entries are source-tagged
    from newsbot.render import ticker_text
    t = ticker_text(script)
    assert all(f"[{s['source']}]" in t for s in script["stories"])


def test_d_manifest(out, manifest):
    segs = manifest["segments"]
    assert len(segs) == 10
    for i, s in enumerate(segs):
        p = out / s["file"]
        assert s["index"] == i
        assert abs(s["duration"] - 6.0) <= 0.05 and abs(s["container_duration"] - 6.0) <= 0.10
        assert s["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()


def test_a_concatenated_segments_are_continuous(out, tmp_path):
    allts = tmp_path / "all.ts"
    allts.write_bytes(b"".join(p.read_bytes() for p in sorted(out.glob("seg_*.ts"))))
    st = {s["codec_type"]: float(s["duration"]) for s in ffprobe(["-show_streams", str(allts)])["streams"]}
    assert abs(st["video"] - 60.0) <= 0.05 and abs(st["audio"] - 60.0) <= 0.3, st
