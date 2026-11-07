"""Day 1 acceptance tests against the real render (NEWSBOT_DAY1_OUT, default out1/)."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from newsbot import script as sm

DAY1 = Path(os.environ.get("NEWSBOT_DAY1_OUT", "out1"))
EP = DAY1 / "episode"
# Rundown floor. 10 fits the Day 1 feed mix (short feed summaries, 12 ranked items). The hourly slices
# (hourly.yml) carry longer source texts (arXiv abstracts, release notes), so 8-9 stories fill the 10 minutes;
# that workflow sets NEWSBOT_MIN_STORIES=6 (the pipeline itself refuses fewer than 6 rankable items).
MIN_STORIES = int(os.environ.get("NEWSBOT_MIN_STORIES") or "10")
# Distinct-source floor for a non-topic episode. 4 for a standalone Day 1 episode. An hourly slice (hourly.yml) is
# dealt 14 items from 5-7 sources, rank keeps 12 from ~5, and the 600 s time budget then keeps 8-9 stories, cutting
# the single-item sources first: scheduled run 42298386727 lost slices 0 and 2 (9 stories, 3 sources each) to the
# floor of 4 while the run as a whole covered 11 sources. That workflow sets NEWSBOT_MIN_SOURCES=3.
MIN_SOURCES = int(os.environ.get("NEWSBOT_MIN_SOURCES") or "4")


@pytest.fixture(scope="module")
def d():
    if not (EP / "manifest.json").exists():
        pytest.skip(f"no Day 1 render in {DAY1}")
    return {"manifest": json.loads((EP / "manifest.json").read_text()), "script": json.loads((EP / "script.json").read_text()),
            "plan": json.loads((EP / "plan.json").read_text()), "report": json.loads((EP / "report.json").read_text())}


def test_episode_is_10_minutes_plus_minus_15s(d):
    segs = d["manifest"]["segments"]
    total = sum(s["duration"] for s in segs)
    assert abs(total - 600) <= 15, total
    assert abs(d["plan"][-1]["end"] - 600) <= 15


def test_manifest_hashes_and_segment_durations(d):
    for i, s in enumerate(d["manifest"]["segments"]):
        assert s["index"] == i and abs(s["duration"] - 6.0) <= 0.05
        assert s["sha256"] == hashlib.sha256((EP / s["file"]).read_bytes()).hexdigest()


def test_rundown_story_count_within_floor_and_12_from_multiple_sources(d):
    n = len(d["script"]["stories"])
    if d["script"].get("topic"):   # topic episode: one subject, fewer and deeper stories (docs/TOPICS.md)
        assert 5 <= n <= 12, n
        assert len({s["source"] for s in d["script"]["stories"]}) >= 2
    else:
        assert MIN_STORIES <= n <= 12, n
        assert len({s["source"] for s in d["script"]["stories"]}) >= MIN_SOURCES


def test_topic_episode_is_on_topic_and_not_a_repeat(d):
    t = d["script"].get("topic")
    if not t:
        pytest.skip("not a topic episode")
    pick = json.loads((EP / "topic_pick.json").read_text())
    assert pick["topic"]["id"] == t["id"] and pick["mode"] == "topic"
    sc = next(s for s in pick["scores"] if s["id"] == t["id"])
    assert sc["blocked"] is None and sc["score"] > 0
    assert d["report"]["topic"]["id"] == t["id"]


def test_zero_unsourced_items_and_every_claim_scene_has_citation(d):
    assert d["report"]["audit"]["unsourced_items"] == 0
    for st in d["script"]["stories"]:
        assert st["source"] and st["url"].startswith("http") and st["published"] is not None
    for sc in d["plan"]:
        if sc["claims"]:
            c = sc["citation"]
            assert c["source"] and c["url"].startswith("http"), sc["kind"]


def test_at_least_95_percent_of_aired_sentences_supported(d, capsys):
    a = d["report"]["audit"]
    print("AUDIT", a)
    assert a["aired_sentences"] >= 20
    assert a["supported_pct"] >= 95.0 and a["grounded_pct"] >= 95.0


def test_every_aired_sentence_is_marked_supported_and_grounded(d):
    aired = 0
    for st in d["script"]["stories"]:
        assert sm.story_problems(st) == {}, st["source"]
        for x in st["sentences"]:
            aired += 1
            assert x["supported"] is True and x["method"] in ("verbatim", "claude", "claude-rewrite")
    # what is narrated is exactly what was checked
    narrated = {sc["claims"][0] for sc in d["plan"] if sc["kind"] == "sentence"}
    checked = {x["text"] for st in d["script"]["stories"] for x in st["sentences"]}
    assert narrated == checked and aired == len([1 for sc in d["plan"] if sc["kind"] == "sentence"])


def test_render_under_25_minutes_and_cost_cap(d):
    assert d["report"]["total_seconds"] < 25 * 60
    llm = d["report"]["llm"]
    if llm.get("used"):
        assert llm["cost_usd_estimate"] <= llm["max_run_usd"] <= 0.75
