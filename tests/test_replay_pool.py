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


def test_refresh_decision_guard():
    good = {"blocks": [{"segments": [{"uri": "bulletins/a/seg_000.ts", "duration": 6.0}]}], "built_at": "t0"}
    same = {"blocks": [{"segments": [{"uri": "bulletins/a/seg_000.ts", "duration": 6.0}]}], "built_at": "t1"}
    newer = {"blocks": [{"segments": [{"uri": "bulletins/b/seg_000.ts", "duration": 6.0}]}]}
    empty = {"kind": "replay-pool", "blocks": []}
    zero = {"blocks": [{"segments": [{"uri": "bulletins/a/seg_000.ts", "duration": 0}]}]}
    assert replay_pool.pool_usable(good) and not replay_pool.pool_usable(empty) and not replay_pool.pool_usable(zero) and not replay_pool.pool_usable(None)
    assert replay_pool.refresh_decision(None, good)[0] is True            # nothing in R2 yet
    assert replay_pool.refresh_decision(empty, good)[0] is True           # broken pool in R2 gets replaced
    assert replay_pool.refresh_decision(good, newer)[0] is True           # newer episodes
    go, why = replay_pool.refresh_decision(good, same)
    assert go is False and why.startswith("unchanged")                    # same segments: no PutObject
    assert replay_pool.refresh_decision(good, same, force=True)[0] is True
    for bad in (empty, zero):
        go, why = replay_pool.refresh_decision(good, bad)
        assert go is False and "no playable segments" in why              # never replace a good pool with an empty one
    assert replay_pool.refresh_decision(None, empty)[0] is False


def test_scheduled_refresh_never_overwrites_a_good_pool_with_nothing(tmp_path, monkeypatch, capsys):
    """The cron path (`--from-r2 --upload`): a good pool/manifest.json in R2 survives a run that finds nothing
    complete, is not rewritten when the newest episodes are the ones it lists, and is replaced by newer ones."""
    s3 = FakeS3()
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "fake")
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(r2, "client", lambda: s3)
    out = str(tmp_path / "pool.json")
    # 1. seed: one complete episode -> published
    r2_bulletin(s3, "20261106T090000Z")
    assert replay_pool.main(["--from-r2", "--write", out, "--upload"]) == 0
    seeded = s3.objects["pool/manifest.json"]
    assert json.loads(seeded)["blocks"][0]["id"] == "pool-20261106T090000Z" and len(s3.puts) == 1
    # 2. the only episodes are now broken (segment gone): nothing complete -> exit 3, pool untouched
    del s3.objects["bulletins/20261106T090000Z/seg_004.ts"]
    assert replay_pool.main(["--from-r2", "--write", out, "--upload"]) == 3
    assert s3.objects["pool/manifest.json"] == seeded and len(s3.puts) == 1
    assert "not touched" in capsys.readouterr().out
    # 3. the episode is complete again and still the newest: unchanged -> no PutObject
    r2_bulletin(s3, "20261106T090000Z")
    assert replay_pool.main(["--from-r2", "--write", out, "--upload"]) == 0
    assert s3.objects["pool/manifest.json"] == seeded and len(s3.puts) == 1
    assert "not uploading: unchanged" in capsys.readouterr().out
    # 3b. --force rewrites it anyway (built_at moves, segments identical)
    assert replay_pool.main(["--from-r2", "--write", out, "--upload", "--force"]) == 0
    assert len(s3.puts) == 2 and json.loads(s3.objects["pool/manifest.json"])["blocks"] == json.loads(seeded)["blocks"]
    # 4. a newer complete episode -> the pool moves to it (max_blocks 1)
    r2_bulletin(s3, "20261106T120000Z")
    assert replay_pool.main(["--from-r2", "--write", out, "--upload"]) == 0
    m = json.loads(s3.objects["pool/manifest.json"])
    assert [b["id"] for b in m["blocks"]] == ["pool-20261106T120000Z"] and s3.puts[-1][0] == "pool/manifest.json"
    worker_shape_ok(m)
    # 5. a corrupt pool object in R2 (not JSON) is replaced, not kept
    s3.objects["pool/manifest.json"] = b"not json"
    assert replay_pool.main(["--from-r2", "--write", out, "--upload"]) == 0
    assert json.loads(s3.objects["pool/manifest.json"])["blocks"][0]["id"] == "pool-20261106T120000Z"


def test_refresh_guard_keeps_a_newer_verified_pool_and_refuses_small_ones(tmp_path, monkeypatch, capsys):
    """Follow-up guard rules: an older candidate never replaces a newer pool that still verifies in R2, a pool that
    points at a deleted/truncated object is replaced, --min-segments refuses too-small pools, and a skipped run
    writes the live pool to --write (what the job summary and scripts/pool_check.py compare against)."""
    s3 = FakeS3()
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "fake")
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(r2, "client", lambda: s3)
    out = tmp_path / "pool.json"
    r2_bulletin(s3, "20261106T120000Z")
    s3.objects["manifest.json"] = json.dumps({"version": 2, "segment_seconds": 6, "epoch": 1793000000, "blocks": []}).encode()
    assert replay_pool.main(["--from-r2", "--write", str(out), "--upload"]) == 0
    first = json.loads(s3.objects["pool/manifest.json"])
    n_puts = len(s3.puts)
    # newest upload truncated -> --from-r2 falls back to an older complete episode, but the live pool is newer and verifies: skipped
    r2_bulletin(s3, "20261106T150000Z", drop="seg_004.ts")
    r2_bulletin(s3, "20261106T090000Z")
    del s3.objects["bulletins/20261106T120000Z/manifest.json"]  # the pool's own episode is no longer a candidate
    assert replay_pool.main(["--from-r2", "--write", str(out), "--upload"]) == 0
    assert json.loads(s3.objects["pool/manifest.json"]) == first and len(s3.puts) == n_puts
    assert json.loads(out.read_text()) == first, "a skipped run writes the pool that stays live"
    assert "is newer than the candidate" in capsys.readouterr().out
    # --force publishes the older one anyway
    assert replay_pool.main(["--from-r2", "--write", str(out), "--upload", "--force"]) == 0
    assert [b["id"] for b in json.loads(s3.objects["pool/manifest.json"])["blocks"]] == ["pool-20261106T090000Z"]
    s3.objects["pool/manifest.json"] = json.dumps(first).encode()
    # the live pool points at a truncated object -> broken -> replaced even by the older episode
    s3.objects["bulletins/20261106T120000Z/seg_003.ts"] = b"short"
    assert replay_pool.main(["--from-r2", "--write", str(out), "--upload"]) == 0
    assert [b["id"] for b in json.loads(s3.objects["pool/manifest.json"])["blocks"]] == ["pool-20261106T090000Z"]
    assert "existing pool is broken" in capsys.readouterr().out
    live = json.loads(s3.objects["pool/manifest.json"])
    # too small for --min-segments: exit 3, R2 untouched, --write shows the live pool
    make_render(tmp_path / "tiny", n=2)
    n_puts = len(s3.puts)
    assert replay_pool.main(["--from-dir", str(tmp_path / "tiny"), "--write", str(out), "--upload", "--min-segments", "10"]) == 3
    assert json.loads(s3.objects["pool/manifest.json"]) == live and len(s3.puts) == n_puts and json.loads(out.read_text()) == live
    # the 15:00 upload completes -> newer -> published
    s3.objects["bulletins/20261106T150000Z/seg_004.ts"] = b"back".ljust(104, b"\0")
    assert replay_pool.main(["--from-r2", "--write", str(out), "--upload"]) == 0
    assert [b["id"] for b in json.loads(s3.objects["pool/manifest.json"])["blocks"]] == ["pool-20261106T150000Z"]


def test_verify_pool_and_decision_table():
    s3 = FakeS3()
    good = {"blocks": [{"id": "pool-20261106T120000Z", "segments": [{"uri": "bulletins/20261106T120000Z/seg_000.ts", "duration": 6.0, "bytes": 4}]}]}
    assert replay_pool.verify_pool(s3, "b", good).startswith("missing")
    s3.objects["bulletins/20261106T120000Z/seg_000.ts"] = b"abcd"
    assert replay_pool.verify_pool(s3, "b", good) is None
    s3.objects["bulletins/20261106T120000Z/seg_000.ts"] = b"abc"
    assert "size" in replay_pool.verify_pool(s3, "b", good)
    assert replay_pool.verify_pool(s3, "b", {"blocks": []}) == "no playable segments"
    newer = {"blocks": [{"id": "pool-20261106T130000Z", "segments": [{"uri": "bulletins/20261106T130000Z/seg_000.ts", "duration": 6.0}]}]}
    older = {"blocks": [{"id": "pool-20261106T110000Z", "segments": [{"uri": "bulletins/20261106T110000Z/seg_000.ts", "duration": 6.0}]}]}
    assert replay_pool.newest_source_ts(good) == "20261106T120000Z" and replay_pool.newest_source_ts({"blocks": []}) == ""
    assert replay_pool.refresh_decision(good, newer)[0] is True
    assert replay_pool.refresh_decision(good, older)[0] is False
    assert replay_pool.refresh_decision(good, older, force=True)[0] is True
    assert replay_pool.refresh_decision(good, older, existing_problem="missing x")[0] is True
    assert replay_pool.refresh_decision(good, newer, min_segments=5)[0] is False
    assert replay_pool.refresh_decision(None, newer, min_segments=5)[0] is False, "too small is refused even over nothing"
    assert replay_pool.refresh_decision(None, newer, min_segments=1)[0] is True


def test_pool_check_healthz_verdict():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pool_check", Path("scripts/pool_check.py"))
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)
    good = {"ok": True, "source": "live-manifest", "pool": {"ok": True, "segments": 100, "built_at": "2026-11-06T13:00:00Z"}}
    assert pc.healthz_verdict(good, "2026-11-06T13:00:00Z") == "match"
    assert pc.healthz_verdict(good, "2026-11-06T12:00:00Z") == "usable"
    assert pc.healthz_verdict(good, None) == "match"
    assert pc.healthz_verdict({"ok": True, "pool": {"ok": False, "problem": "missing: pool/manifest.json is not in the bucket", "segments": 0}}, None) == "bad"
    assert pc.healthz_verdict({"ok": False}, None) == "bad"
    assert "source=live-manifest" in pc.describe(good)


def test_worker_fixture_matches_the_bootstrap_shape():
    """worker/test/fixtures/replay-pool.json is what the Worker tests use as the pool; keep it in the real shape."""
    fx = json.loads(Path("worker/test/fixtures/replay-pool.json").read_text())
    worker_shape_ok(fx)
    assert set(fx) >= {"kind", "built_at", "built_from", "blocks", "segment_seconds"}
