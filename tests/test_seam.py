"""SEAM TEST: bulletin -> slate/replay -> loop joins are glitch-free in media terms.

Part 1 renders small real HLS block sets with the production encode settings (no TTS/skia needed) and checks
parameters, closed GOPs, timestamps and the generated channel playlist (RFC 8216 sections 4.3.2.3, 4.3.3.1,
4.3.3.2, 6.2.1, 6.2.2 as implemented in newsbot/playlist.py). Part 2 repeats the checks on the real Day 1 episode.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import m3u8
import pytest

from newsbot import episode, media, playlist, pool as poolmod

DAY1 = Path(os.environ.get("NEWSBOT_DAY1_OUT", "out1"))


def make_block(d: Path, seconds: float, prefix: str, tone: int):
    d.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={seconds}",
           *episode.encode_args(seconds), "-hls_segment_filename", str(d / f"{prefix}_%03d.ts"), str(d / "index.m3u8")]
    subprocess.run(cmd, check=True, capture_output=True)
    segs = []
    for i, p in enumerate(sorted(d.glob(f"{prefix}_*.ts"))):
        segs.append({"index": i, "file": p.name, "duration": 6.0, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    (d / "manifest.json").write_text(json.dumps({"segment_seconds": 6, "segments": segs}))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("seam")
    make_block(root / "ep_new", 24, "seg", 440)       # the bulletin
    make_block(root / "ep_old", 18, "seg", 330)       # a replay
    make_block(root / "slate", 12, "slate", 220)
    p = poolmod.build_pool([root / "ep_new", root / "ep_old"], root / "slate")
    blocks = poolmod.channel_blocks(p, "ep_new")
    infos = {}
    for b in blocks:
        for s in b["segments"]:
            infos[s["uri"]] = media.probe_segment(Path(b["dir"]) / s["file"])
    return {"blocks": blocks, "infos": infos, "pool": p, "root": root}


def seg_infos(blocks, infos):
    return [infos[s["uri"]] for b in blocks for s in b["segments"]]


def test_block_order_bulletin_slate_replay(world):
    assert [b["kind"] for b in world["blocks"]] == ["bulletin", "slate", "replay"]


def test_identical_codec_and_audio_params_across_all_blocks(world):
    sigs = {json.dumps(i["sig"], sort_keys=True) for i in world["infos"].values()}
    assert len(sigs) == 1, sigs
    sig = json.loads(next(iter(sigs)))
    assert (sig["v_codec"], sig["w"], sig["h"], sig["fps"], sig["pix_fmt"]) == ("h264", 1280, 720, "30/1", "yuv420p")
    assert (sig["a_codec"], sig["a_rate"], sig["a_channels"]) == ("aac", "48000", 1)


def test_closed_2s_gop_in_every_segment(world):
    for uri, i in world["infos"].items():
        assert i["frames"] == 180, uri
        assert len(i["keys"]) == 3 and abs(i["keys"][0] - i["v"]["start"]) < 1e-3, (uri, i["keys"])
        assert all(abs(b - a - 2.0) < 0.01 for a, b in zip(i["keys"], i["keys"][1:])), (uri, i["keys"])
        assert not i["leading_pictures"], uri


def test_first_segment_of_each_block_declares_closed_gop(world):
    for b in world["blocks"]:
        assert world["infos"][b["segments"][0]["uri"]]["sei_closed_gop"], b["id"]


def test_timestamps_monotonic_within_each_segment(world):
    for uri, i in world["infos"].items():
        assert i["v_dts_strict"] and i["a_dts_strict"] and i["pts_ge_dts"], uri


def test_inside_a_block_segments_join_without_discontinuity_needed(world):
    for b in world["blocks"]:
        infos = [world["infos"][s["uri"]] for s in b["segments"]]
        for x, y in zip(infos, infos[1:]):
            assert media.joins_continuously(x, y), (x["path"], y["path"])


def test_block_boundaries_do_need_a_discontinuity(world):
    """Each block restarts its own timestamp sequence, so the join (incl. the loop wrap) is NOT continuous."""
    bl = world["blocks"]
    for a, b in zip(bl, bl[1:] + bl[:1]):
        assert not media.joins_continuously(world["infos"][a["segments"][-1]["uri"]], world["infos"][b["segments"][0]["uri"]])


def test_playlist_tags_discontinuity_wherever_media_requires_it(world):
    n = sum(len(b["segments"]) for b in world["blocks"])
    for live in range(0, 3 * n + 4):          # three full loops
        txt = playlist.channel_playlist(world["blocks"], live)
        assert playlist.check_discontinuities_against_media(txt, world["infos"], media.joins_continuously) == [], live


def test_media_sequence_never_decreases_across_loops_and_playlists_stay_valid(world):
    n = sum(len(b["segments"]) for b in world["blocks"])
    assert playlist.check_sequence_over_time(world["blocks"], range(0, 4 * n + 6)) == []


def test_discontinuity_sequence_counts_departed_tags(world):
    segs, starts = playlist.cycle_layout(world["blocks"])
    n = len(segs)
    for first in range(0, 5 * n):
        brute = sum(1 for j in range(1, first) if (j % n) in starts)
        assert playlist.tags_before(first, n, starts) == brute, first
    # explicit RFC 8216 4.3.3.3 example: wrap tag leaves the 5-segment window one reload later
    live = n + 4   # window first = n, which is the wrap segment itself (still tagged, dseq counts earlier ones)
    p = playlist.parse(playlist.channel_playlist(world["blocks"], live))
    assert p["seg" if False else "seq"] == n and p["segs"][0]["disc"] and p["dseq"] == len(starts) - 1


def test_independent_parser_agrees_with_our_playlist(world):
    n = sum(len(b["segments"]) for b in world["blocks"])
    for live in (3, n - 1, n, n + 2, 2 * n + 1):
        txt = playlist.channel_playlist(world["blocks"], live)
        ours, lib = playlist.parse(txt), m3u8.loads(txt)
        assert lib.media_sequence == ours["seq"] and lib.discontinuity_sequence == ours["dseq"]
        assert [s.uri for s in lib.segments] == [s["uri"] for s in ours["segs"]]
        assert [bool(s.discontinuity) for s in lib.segments] == [s["disc"] for s in ours["segs"]]
        assert lib.target_duration == ours["target"]


def test_checker_flags_a_missing_discontinuity(world):
    n = sum(len(b["segments"]) for b in world["blocks"])
    live = len(world["blocks"][0]["segments"]) + 1      # window covers bulletin -> slate boundary
    txt = playlist.channel_playlist(world["blocks"], live).replace("#EXT-X-DISCONTINUITY\n", "")
    assert playlist.check_discontinuities_against_media(txt, world["infos"], media.joins_continuously)


def test_stream_cannot_go_dark(world, tmp_path):
    p = world["pool"]
    only_slate = {"episodes": [], "skipped": [], "slate": p["slate"]}
    assert [b["kind"] for b in poolmod.channel_blocks(only_slate)] == ["slate"]
    assert playlist.check_media_playlist(playlist.channel_playlist(poolmod.channel_blocks(only_slate), 40), expect_seg_seconds=None) == []
    with pytest.raises(RuntimeError):
        poolmod.channel_blocks({"episodes": [], "skipped": [], "slate": None})
    # a corrupt replay is skipped, not aired
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text(json.dumps({"segments": [{"file": "seg_000.ts", "duration": 6, "sha256": "0"}]}))
    (bad / "seg_000.ts").write_bytes(b"x")
    pl = poolmod.build_pool([world["root"] / "ep_new", bad], world["root"] / "slate")
    assert len(pl["episodes"]) == 1 and pl["skipped"] and "hash mismatch" in pl["skipped"][0]["reason"]


# ----------------------------- Part 2: the real Day 1 episode -------------------------------------------
@pytest.fixture(scope="module")
def real():
    ep, sl = DAY1 / "episode", DAY1 / "slate"
    if not (ep / "manifest.json").exists() or not (sl / "manifest.json").exists():
        pytest.skip(f"no Day 1 render in {DAY1}")
    segs = sorted(ep.glob("seg_*.ts"))
    sls = sorted(sl.glob("slate_*.ts"))
    return {"ep": ep, "ep_infos": [media.probe_segment(p) for p in segs], "sl_infos": [media.probe_segment(p) for p in sls]}


def test_real_params_identical_between_episode_and_slate(real):
    sigs = {json.dumps(i["sig"], sort_keys=True) for i in real["ep_infos"] + real["sl_infos"]}
    assert len(sigs) == 1, sigs


def test_real_gop_and_timestamps(real):
    for i in real["ep_infos"] + real["sl_infos"]:
        assert i["frames"] == 180 and len(i["keys"]) == 3 and not i["leading_pictures"], i["path"]
        assert all(abs(b - a - 2.0) < 0.01 for a, b in zip(i["keys"], i["keys"][1:])), i["path"]
        assert i["v_dts_strict"] and i["a_dts_strict"] and i["pts_ge_dts"], i["path"]


def test_real_av_drift_under_40ms_across_10_minute_concat(real):
    d = media.concat_drift(real["ep_infos"])
    print("concat drift:", d)
    assert abs(d["video_seconds"] - 600) <= 0.1
    assert d["drift_s"] < 0.040, d


def test_real_episode_segments_continuous_and_seams_tagged(real):
    for x, y in zip(real["ep_infos"], real["ep_infos"][1:]):
        assert media.joins_continuously(x, y), (x["path"], y["path"])
    assert not media.joins_continuously(real["ep_infos"][-1], real["sl_infos"][0])
    assert not media.joins_continuously(real["sl_infos"][-1], real["ep_infos"][0])


def test_real_episode_length_600s_plus_minus_15(real):
    total = sum(i["v"]["end"] - i["v"]["start"] for i in real["ep_infos"])
    assert abs(total - 600) <= 15, total
    assert len(real["ep_infos"]) == 100
