"""Day 1 R2 publisher with a fake S3 client: upload order (segments first, root manifest.json last), key layout
(docs/R2_LAYOUT.md Layout B), content types, replays taken from the manifest already in R2, continuity fields
(docs/MANIFEST-SWAP.md) equal to the Worker's JS reference (vectors computed with worker/src/playlist.js)."""
import hashlib
import io
import json
from pathlib import Path

import pytest

from newsbot import channel, publish


class NoSuchKey(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    """Records every write in order; get_object serves what was put."""
    def __init__(self):
        self.puts, self.objects = [], {}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        data = Path(filename).read_bytes()
        self.objects[key] = (data, ExtraArgs["ContentType"])
        self.puts.append((key, ExtraArgs["ContentType"], len(data)))

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = (Body, ContentType)
        self.puts.append((Key, ContentType, len(Body)))

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise NoSuchKey()
        return {"Body": io.BytesIO(self.objects[Key][0])}


def fake_render(out: Path, n_ep=4, n_slate=2):
    """A Day 1 output tree with tiny stand-in .ts files and the real manifest fields the publisher reads."""
    def block(d, stem, n):
        d.mkdir(parents=True)
        segs = []
        for i in range(n):
            p = d / f"{stem}_{i:03d}.ts"
            p.write_bytes(f"{stem}{i}".encode() * 10)
            segs.append({"index": i, "file": p.name, "duration": 6.0, "bytes": p.stat().st_size,
                         "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
        (d / "manifest.json").write_text(json.dumps({"version": 1, "segment_seconds": 6, "segments": segs}))
    block(out / "episode", "seg", n_ep)
    block(out / "slate", "slate", n_slate)
    return out


NOW1 = channel.EPOCH + 6 * 1000 + 1  # live segment 1000
NOW2 = NOW1 + 3600


def test_first_publish_layout_order_and_types(tmp_path):
    out = fake_render(tmp_path / "out1")
    s3 = FakeS3()
    summary = publish.publish(out, s3, "bkt", now=NOW1)
    keys = [k for k, _, _ in s3.puts]
    prefix = summary["prefix"]
    assert prefix.startswith("bulletins/") and prefix.endswith("Z")

    # root manifest.json is written last and exactly once; nothing else at the bucket root
    assert keys[-1] == "manifest.json" and keys.count("manifest.json") == 1
    assert all("/" in k for k in keys[:-1])
    # every .ts of a block precedes that block's manifest.json
    for b in (prefix, f"{prefix}/slate"):
        idx = [i for i, k in enumerate(keys) if k.startswith(b + "/") and k.count("/") == b.count("/") + 1]
        ts = [i for i in idx if keys[i].endswith(".ts")]
        assert keys[max(idx)] == f"{b}/manifest.json" and max(ts) < max(idx)
    # content types and sizes
    for k, ct, n in s3.puts:
        assert ct == ("video/mp2t" if k.endswith(".ts") else "application/json") and n > 0
    assert summary["segments"] == 6 and summary["objects"] == 9 and summary["last_key"] == "manifest.json"
    assert all(channel_key in s3.objects for channel_key in [f"{prefix}/seg_000.ts", f"{prefix}/slate/slate_001.ts"])

    root = json.loads(s3.objects["manifest.json"][0])
    assert root["epoch"] == channel.EPOCH and root["segment_seconds"] == 6 and "prev" not in root
    assert root["cycle_start_k"] == 1000 + channel.MARGIN and root["cycle_start_dseq"] == 0
    assert [(b["kind"], len(b["segments"])) for b in root["blocks"]] == [("bulletin", 4), ("slate", 2)]
    # every uri in the root manifest names an uploaded key with the uploaded bytes, and only uploaded keys
    for b in root["blocks"]:
        for s in b["segments"]:
            assert s["uri"] in s3.objects and s3.objects[s["uri"]][1] == "video/mp2t" and s["duration"] == 6.0
    uris = {s["uri"] for b in root["blocks"] for s in b["segments"]}
    assert uris == {k for k in s3.objects if k.endswith(".ts")}
    assert (out / "publish.json").exists()


def test_second_publish_keeps_previous_bulletin_as_replay_and_is_continuous(tmp_path):
    s3 = FakeS3()
    publish.publish(fake_render(tmp_path / "a"), s3, "bkt", now=NOW1)
    first = json.loads(s3.objects["manifest.json"][0])
    first_prefix = first["blocks"][0]["segments"][0]["uri"].rsplit("/", 1)[0]
    n_before = len(s3.puts)

    publish.publish(fake_render(tmp_path / "b", n_ep=3), s3, "bkt", now=NOW2)
    root = json.loads(s3.objects["manifest.json"][0])
    kinds = [(b["kind"], len(b["segments"])) for b in root["blocks"]]
    assert kinds == [("bulletin", 3), ("slate", 2), ("replay", 4)]
    # the replay is the earlier bulletin's keys, not re-uploaded; the earlier slate is not replayed
    assert all(s["uri"].startswith(first_prefix + "/") for s in root["blocks"][2]["segments"])
    assert len(s3.puts) - n_before == 3 + 1 + 2 + 1 + 1
    # continuity: epoch unchanged, start on a loop boundary of the first cycle (N=6), prev = first without prev
    assert root["epoch"] == first["epoch"]
    k = channel.live_k(NOW2, first["epoch"])
    assert root["cycle_start_k"] >= k + channel.MARGIN
    assert (root["cycle_start_k"] - first["cycle_start_k"]) % 6 == 0
    assert root["prev"] == first and "prev" not in root["prev"]
    assert root["cycle_start_dseq"] == channel.swap_dseq(first, root["cycle_start_k"])
    # nothing was overwritten or deleted
    assert all(k in s3.objects for k, _, _ in s3.puts)


def test_published_epoch_wins_over_the_constant(tmp_path):
    s3 = FakeS3()
    s3.put_object(Bucket="bkt", Key="manifest.json", ContentType="application/json", Body=json.dumps(
        {"version": 2, "segment_seconds": 6, "epoch": 1700000000, "cycle_start_k": 5, "cycle_start_dseq": 0,
         "blocks": [{"id": "x", "kind": "bulletin", "segments": [{"uri": "bulletins/x/seg_000.ts", "duration": 6.0}]}]}).encode())
    publish.publish(fake_render(tmp_path / "c"), s3, "bkt", now=1700000000 + 6 * 50)
    root = json.loads(s3.objects["manifest.json"][0])
    assert root["epoch"] == 1700000000 and root["cycle_start_k"] == 60 and root["prev"]["cycle_start_k"] == 5


def test_skips_cleanly_without_secrets(tmp_path, monkeypatch, capsys):
    out = fake_render(tmp_path / "d")
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    assert publish.main([str(out)]) == 0
    assert "skipping R2 upload" in capsys.readouterr().out
    assert publish.main([str(tmp_path / "missing")]) == 2


# ---------- swap math equals the Worker's JS reference (worker/src/playlist.js nextSwapStart / swapDseq) ----------
def _block(bid, n):
    return {"id": bid, "segments": [{"uri": f"{bid}/seg_{i}.ts", "duration": 6} for i in range(n)]}


A = {"segment_seconds": 6, "cycle_start_k": 100, "blocks": [_block("a", 10)]}
B = {"segment_seconds": 6, "cycle_start_k": 120, "cycle_start_dseq": 2, "blocks": [_block("b", 7), _block("s", 2), _block("r", 10)], "prev": A}
C = {"segment_seconds": 6, "blocks": [_block("c", 4), _block("s", 2)]}


@pytest.mark.parametrize("cur,k,start,dseq", [
    (A, 103, 120, 12), (A, 110, 120, 12), (A, 111, 130, 13), (A, 50, 100, 10),      # docs vector: 103 -> 120
    (B, 125, 139, 5), (B, 140, 158, 8), (B, 200, 215, 17), (B, 60, 120, 2),
    (C, 0, 12, 3), (C, 3, 18, 5), (C, 11, 24, 7),
    (None, 7, 17, 0),
])
def test_swap_vectors_match_worker_js(cur, k, start, dseq):
    assert channel.next_swap_start(cur, k, 10) == start
    assert channel.swap_dseq(cur, start) == dseq


def test_next_manifest_replaces_a_pending_manifest():
    pending = {"segment_seconds": 6, "epoch": channel.EPOCH, "cycle_start_k": 500, "cycle_start_dseq": 9,
               "blocks": [_block("p", 10)], "prev": A}
    m = channel.next_manifest(pending, [_block("n", 3)], channel.EPOCH + 6 * 100)
    assert m["cycle_start_k"] == 500 and m["cycle_start_dseq"] == 9 and m["prev"] == A
