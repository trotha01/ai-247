"""Replay-pool bootstrap (newsbot/replay_pool.py): built from a local render or from what is already in R2,
verified, uploaded with the manifest last, and in the shape the Worker's failover reads (docs/FAILOVER.md)."""
import hashlib
import json
from pathlib import Path

import pytest

from newsbot import playlist, r2, replay_pool


class FakeS3:
    """Enough of boto3's S3 client for replay_pool: objects in a dict, puts recorded in order."""

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        # paginate by 3 to exercise the continuation loop
        start = int(ContinuationToken or 0)
        page = keys[start:start + 3]
        r = {"Contents": [{"Key": k} for k in page], "IsTruncated": start + 3 < len(keys)}
        if r["IsTruncated"]:
            r["NextContinuationToken"] = str(start + 3)
        return r

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        import io
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[Key])}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[key] = Path(filename).read_bytes()
        self.puts.append((key, (ExtraArgs or {}).get("ContentType")))

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body
        self.puts.append((Key, ContentType))


def make_render(d: Path, n: int = 10, seg_s: int = 6, corrupt: int | None = None) -> dict:
    """A render directory like newsbot.manifest.build_manifest writes (Day 0 shape, dummy segment bytes)."""
    d.mkdir(parents=True, exist_ok=True)
    segs = []
    for i in range(n):
        name = f"seg_{i:03d}.ts"
        data = f"{d.name}:{name}".encode().ljust(100 + i, b"\0")
        (d / name).write_bytes(data)
        segs.append({"index": i, "file": name, "duration": float(seg_s), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    if corrupt is not None:
        (d / f"seg_{corrupt:03d}.ts").write_bytes(b"garbage")
    m = {"version": 1, "segment_seconds": seg_s, "generated_by": "test", "segments": segs, "sources": []}
    (d / "manifest.json").write_text(json.dumps(m))
    return m


def r2_bulletin(s3: FakeS3, ts: str, n: int = 10, drop: str | None = None, wrong_size: str | None = None):
    """Upload a bulletin to the fake bucket the way newsbot.r2.upload lays it out (bulletins/<ts>/...)."""
    segs = []
    for i in range(n):
        name = f"seg_{i:03d}.ts"
        data = f"{ts}:{name}".encode().ljust(100 + i, b"\0")
        segs.append({"index": i, "file": name, "duration": 6.0, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        if name != drop:
            s3.objects[f"bulletins/{ts}/{name}"] = data if name != wrong_size else data + b"x"
    s3.objects[f"bulletins/{ts}/manifest.json"] = json.dumps({"version": 1, "segment_seconds": 6, "segments": segs}).encode()


def worker_shape_ok(m: dict):
    """What worker/src/playlist.js layout() needs: blocks with uri + duration > 0; and the channel playlist
    generated from it passes the Python checker (the Worker's logic is a golden-tested port of it)."""
    assert m["kind"] == "replay-pool" and m["version"] == 2 and m["segment_seconds"] == 6
    assert m["blocks"] and all(b["segments"] for b in m["blocks"])
    for b in m["blocks"]:
        for s in b["segments"]:
            assert s["uri"] and "/" in s["uri"] and not s["uri"].startswith("/") and ".." not in s["uri"]
            assert s["duration"] > 0
    assert playlist.check_sequence_over_time(m["blocks"], range(0, 3 * sum(len(b["segments"]) for b in m["blocks"]))) == []


def test_block_from_dir_checks_hashes_and_builds_worker_shape(tmp_path):
    make_render(tmp_path / "day0")
    b = replay_pool.block_from_dir(tmp_path / "day0", "pool-day0", "pool/day0")
    assert len(b["segments"]) == 10 and b["seconds"] == 60.0
    assert b["segments"][3]["uri"] == "pool/day0/seg_003.ts"
    m = replay_pool.build_pool_manifest([b], 1793000000, {"source": "dir"})
    worker_shape_ok(m)
    assert m["epoch"] == 1793000000 and m["built_from"] == {"source": "dir"} and m["built_at"].endswith("Z")


def test_corrupt_or_missing_local_segment_is_refused(tmp_path):
    make_render(tmp_path / "bad", corrupt=4)
    with pytest.raises(ValueError, match="sha256"):
        replay_pool.block_from_dir(tmp_path / "bad", "x", "pool/x")
    make_render(tmp_path / "gone")
    (tmp_path / "gone" / "seg_007.ts").unlink()
    with pytest.raises(FileNotFoundError):
        replay_pool.block_from_dir(tmp_path / "gone", "x", "pool/x")
    with pytest.raises(ValueError, match="empty"):
        replay_pool.build_pool_manifest([], None, {})


def test_from_r2_picks_newest_complete_episode_and_skips_broken_ones():
    s3 = FakeS3()
    r2_bulletin(s3, "20261106T090000Z")                           # complete, oldest
    r2_bulletin(s3, "20261106T120000Z", drop="seg_005.ts")        # newest but a segment is missing
    r2_bulletin(s3, "20261106T100000Z", wrong_size="seg_002.ts")  # truncated upload
    r2_bulletin(s3, "20261106T110000Z")                           # newest complete one -> chosen
    s3.objects["manifest.json"] = json.dumps({"version": 2, "segment_seconds": 6, "epoch": 1793000000, "blocks": []}).encode()
    assert replay_pool.candidate_manifests(s3, "b")[0] == "bulletins/20261106T120000Z/manifest.json"
    m, report = replay_pool.pool_from_r2(s3, "b")
    worker_shape_ok(m)
    assert [b["id"] for b in m["blocks"]] == ["pool-20261106T110000Z"]
    assert m["blocks"][0]["segments"][0]["uri"] == "bulletins/20261106T110000Z/seg_000.ts"
    assert m["epoch"] == 1793000000, "epoch copied from the live manifest so k stays one clock"
    assert [sk["manifest_key"] for sk in report["skipped"]] == ["bulletins/20261106T120000Z/manifest.json"]  # stops at the first good one
    assert "missing bulletins/20261106T120000Z/seg_005.ts" in report["skipped"][0]["problems"]
    # two newest complete episodes when asked: the truncated 10:00 upload is skipped on the way
    m2, report2 = replay_pool.pool_from_r2(s3, "b", max_blocks=2)
    assert [b["id"] for b in m2["blocks"]] == ["pool-20261106T110000Z", "pool-20261106T090000Z"]
    assert [sk["manifest_key"] for sk in report2["skipped"]][1] == "bulletins/20261106T100000Z/manifest.json"
    assert "size" in report2["skipped"][1]["problems"][0]
    worker_shape_ok(m2)


def test_from_r2_with_nothing_usable_raises():
    s3 = FakeS3()
    r2_bulletin(s3, "20261106T120000Z", drop="seg_000.ts")
    with pytest.raises(RuntimeError, match="no complete episode"):
        replay_pool.pool_from_r2(s3, "b")


def test_publish_uploads_segments_first_and_manifest_last(tmp_path):
    make_render(tmp_path / "day0", n=4)
    b = replay_pool.block_from_dir(tmp_path / "day0", "pool-day0", "pool/day0")
    m = replay_pool.build_pool_manifest([b], None, {"source": "dir"})
    s3 = FakeS3()
    written = replay_pool.publish(s3, "b", m, [b])
    assert written[-1] == "pool/manifest.json" and written[:-1] == [s["uri"] for s in b["segments"]]
    assert s3.puts[-1] == ("pool/manifest.json", "application/json")
    assert all(ct == "video/mp2t" for k, ct in s3.puts[:-1])
    stored = json.loads(s3.objects["pool/manifest.json"])
    assert stored["blocks"][0]["segments"][0]["uri"] == "pool/day0/seg_000.ts"
    assert s3.objects["pool/day0/seg_000.ts"] == (tmp_path / "day0" / "seg_000.ts").read_bytes()
    # an R2-built pool uploads nothing but the manifest
    s3b = FakeS3()
    assert replay_pool.publish(s3b, "b", m, []) == ["pool/manifest.json"]


def test_cli_without_r2_secrets_writes_locally_only(tmp_path, monkeypatch, capsys):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    make_render(tmp_path / "episode", n=5)
    out = tmp_path / "pool.json"
    rc = replay_pool.main(["--from-dir", str(tmp_path / "episode"), "--id", "ep1", "--write", str(out), "--upload", "--epoch", "1793000000"])
    assert rc == 0
    m = json.loads(out.read_text())
    worker_shape_ok(m)
    assert m["blocks"][0]["id"] == "pool-ep1" and m["blocks"][0]["segments"][0]["uri"] == "pool/ep1/seg_000.ts"
    assert "skipping upload" in capsys.readouterr().out
    assert replay_pool.main(["--from-r2", "--write", str(out)]) == 2  # cannot read R2 without secrets


def test_cli_from_r2_and_dir_uploads_with_fake_client(tmp_path, monkeypatch):
    s3 = FakeS3()
    r2_bulletin(s3, "20261106T120000Z")
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "fake")
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(r2, "client", lambda: s3)
    make_render(tmp_path / "slate", n=3)
    out = tmp_path / "pool.json"
    assert replay_pool.main(["--from-r2", "--from-dir", str(tmp_path / "slate"), "--write", str(out), "--upload"]) == 0
    m = json.loads(s3.objects["pool/manifest.json"])
    worker_shape_ok(m)
    assert [b["id"] for b in m["blocks"]] == ["pool-20261106T120000Z", "pool-slate"]
    assert s3.puts[-1][0] == "pool/manifest.json" and len(s3.puts) == 4  # 3 slate segments + manifest
    assert m["built_from"]["source"] == "r2+dir"


def test_worker_fixture_matches_the_bootstrap_shape():
    """worker/test/fixtures/replay-pool.json is what the Worker tests use as the pool; keep it in the real shape."""
    fx = json.loads(Path("worker/test/fixtures/replay-pool.json").read_text())
    worker_shape_ok(fx)
    assert set(fx) >= {"kind", "built_at", "built_from", "blocks", "segment_seconds"}
