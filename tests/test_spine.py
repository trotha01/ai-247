"""spine/: node contract, channel YAML checks, runner loop (queue ahead, partial flush, skip failures, resume)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml

from spine import contract
from spine.nodes.common import check_prefix
from spine.runner import Runner, load_channel

ROOT = Path(__file__).resolve().parents[1]


def chan(tmp_path, **over):
    ch = {"channel": "t", "prefix": "lang/spine-test/",
          "cadence": {"queue_ahead": 3, "block_items": 2, "max_wait": 60, "poll": 0.05},
          "producer": [{"node": "make", "run": "tests.spine_fake_nodes:make", "out": ["script.json"]}],
          "item": [{"node": "render", "run": "tests.spine_fake_nodes:render", "in": ["script.json"], "out": ["clip.mp4"],
                    "params": over.pop("render_params", {})}],
          "block": [{"node": "join", "run": "tests.spine_fake_nodes:join", "in": ["clip.mp4"], "out": ["out"]},
                    {"node": "publish", "run": "spine.nodes.common:publish", "in": ["out"]}]}
    ch.update(over)
    p = tmp_path / "t.yaml"
    p.write_text(yaml.safe_dump(ch))
    return load_channel(str(p))


def test_result_written_last_and_atomically(tmp_path):
    contract.write_node_yaml(tmp_path, {"name": "x", "params": {"a": 1}})
    r = contract.call(lambda job: ({"o": job.out("o.txt")} if job.out("o.txt").write_text("hi") else {}), tmp_path)
    assert r["status"] == "ok" and r["outputs"] == {"o": "o.txt"}
    assert json.loads((tmp_path / "result.json").read_text())["status"] == "ok"
    assert not list(tmp_path.glob(".*.tmp"))


def test_missing_output_is_fail(tmp_path):
    contract.write_node_yaml(tmp_path, {"name": "x"})
    assert contract.call(lambda job: {"o": "nope.txt"}, tmp_path)["status"] == "fail"


def test_bad_result_is_fail(tmp_path):
    (tmp_path / "result.json").write_text('{"status": "great"}')
    assert contract.read_result(tmp_path)["status"] == "fail"


def test_every_channel_yaml_is_valid():
    names = {load_channel(str(p))["channel"] for p in (ROOT / "channels").glob("*.yaml")}
    assert "lang" in names


def test_yaml_rejects_unknown_input_and_missing_publish(tmp_path):
    with pytest.raises(ValueError, match="no earlier node"):
        chan(tmp_path, item=[{"node": "r", "run": "m:f", "in": ["nope"]}])
    with pytest.raises(ValueError, match="publish"):
        chan(tmp_path, block=[{"node": "join", "run": "m:f", "in": ["clip.mp4"]}])


def test_prefix_guard():
    assert check_prefix("lang/spine-test/", "lang/") == "lang/spine-test/"
    for bad, own in (("puddle/", "lang/"), ("lang/../x/", "lang/"), ("lang", "lang/"), ("lang/", "")):
        with pytest.raises(ValueError):
            check_prefix(bad, own)


def test_loop_blocks_skips_failures_and_resumes(tmp_path):
    ch = chan(tmp_path, render_params={"fail": [1], "voice": "a"})
    r = Runner(ch, tmp_path / "root", dry_run=True, max_blocks=2)
    assert r.run() == 0
    root = tmp_path / "root"
    st = json.loads((root / "status.json").read_text())
    assert st["blocks"] == 2 and st["failed_items"] >= 1
    assert any(p.name.endswith("-00002") for p in (root / "failed").iterdir())  # item n=1 failed and was skipped
    assert len(list((root / "done").glob("*.json"))) >= 3
    ev = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()]
    assert sum(e["ev"] == "published" for e in ev) == 2


def test_partial_flush_after_max_wait(tmp_path):
    ch = chan(tmp_path)
    r = Runner(ch, tmp_path / "root", dry_run=True)
    assert r.produce_one()
    assert r.take_batch() == []                       # 1 of 2: wait
    assert len(r.take_batch(now=time.time() + 61)) == 1  # oldest waited past max_wait: partial block


def test_node_without_result_fails_and_ok_steps_are_not_rerun(tmp_path):
    ch = chan(tmp_path, item=[{"node": "bad", "run": "tests.spine_fake_nodes:no_result", "in": ["script.json"], "out": ["clip.mp4"]}])
    r = Runner(ch, tmp_path / "root", dry_run=True)
    assert r.produce_one()
    item = next((tmp_path / "root" / "inbox").iterdir())
    first = contract.read_result(item / "p00-make")
    # a restart reuses the ok producer step instead of making a new lesson number
    assert r.run_stage("producer", item, {})[0] == "ok"
    assert (r.root / "state" / "make" / "n").read_text() == "1" and first["status"] == "ok"
    assert r.work_block(r.take_batch(now=time.time() + 999)) is False
    assert (tmp_path / "root" / "failed" / item.name).exists()


def test_recover_moves_working_back(tmp_path):
    r = Runner(chan(tmp_path), tmp_path / "root", dry_run=True)
    (r.root / "working" / "x").mkdir()
    r.recover()
    assert (r.root / "inbox" / "x").exists()


def test_yaml_param_swap_reaches_node_after_restart(tmp_path):
    for voice in ("a", "b"):
        ch = chan(tmp_path, render_params={"voice": voice}, cadence={"queue_ahead": 1, "block_items": 1, "poll": 0.05})
        root = tmp_path / f"root-{voice}"
        Runner(ch, root, dry_run=True, max_blocks=1).run()
        done = json.loads(next((root / "done").glob("*.json")).read_text())
        assert done["outputs"]["clip.mp4"].endswith("clip.txt")
    log = [json.loads(l) for l in (tmp_path / "root-b" / "events.jsonl").read_text().splitlines()]
    assert any(e["ev"] == "published" for e in log)
