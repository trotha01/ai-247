"""Topic research stage (docs/TOPICS.md): matching, deterministic scoring and repeat blocking, the plan call with a
scripted client, the stage round trip (offline) and the history record. Primary-source reading and the discovery
gate are covered by tests/test_research.py."""
import json
import time
from types import SimpleNamespace

import pytest

import dataclasses

from newsbot import discovery, feeds, llm, research, topics
from tests.fixtures import make_items
from tests.test_day1_units import Scripted

NOW = 1_800_000_000.0


def cfg():
    return topics.load_topics("topics/topics.json")


def item(src, title, summary, url, age_h=2.0, now=NOW):
    ts = now - age_h * 3600
    return feeds.Item(src, title, summary, url, time.strftime("%Y-%m-%d", time.gmtime(ts)), ts)


WORDS = ["sandbox", "memory", "planning", "browser", "terminal", "review", "testing", "deploy", "search", "voice",
         "vision", "pricing", "latency", "safety", "evals", "plugins"]


def _w(k, a, b):
    return f"{WORDS[k % 16]} {WORDS[(k * a + 1) % 16]} {WORDS[(k * b + 2) % 16]}"


def agent_items(n=6, age_h=2.0, start=0):
    # distinct titles (rank.rank removes near-duplicate titles, token Jaccard >= 0.6); ages age_h, age_h+1, ...
    return [item("OpenAI", f"Coding agent {_w(k, 3, 5)}", "The coding agent now runs tool calls in a sandbox. " * 6,
                 f"https://example.com/agents/{k}", age_h + (k - start)) for k in range(start, start + n)]


def vfx_items(n=6, age_h=2.0):
    return [item("Hugging Face", f"Film video generation {_w(k, 5, 7)}", "A text-to-video model for film and VFX work. " * 6,
                 f"https://example.com/vfx/{k}", age_h + k) for k in range(n)]


def history(entries):
    return {"version": 1, "episodes": entries}


def ep(run_id, topic, ts, urls=()):
    return {"run_id": run_id, "ts": ts, "topic": topic, "stories": [{"url": u, "source": "x", "headline": "h"} for u in urls]}


# ---------- files and matching ----------
def test_seed_topics_file_is_valid_and_has_the_two_seed_lanes():
    c = cfg()
    ids = [t["id"] for t in c["topics"]]
    assert ids[:2] == ["agent-harnesses", "ai-vfx"] and all(t["lane"] == "seed" for t in c["topics"][:2])
    assert c["repeat_after_episodes"] >= 1 and c["max_new_topics_per_day"] == 1
    h = json.loads(open("episodes/history.json").read())
    assert isinstance(h["episodes"], list) and all({"run_id", "ts", "topic", "stories"} <= set(e) for e in h["episodes"])


def test_keyword_matching_is_word_bounded_and_own_sources_always_match():
    t = cfg()["topics"][0]
    assert topics.matches(t, item("OpenAI", "New coding agent ships", "x" * 80, "u"))
    assert not topics.matches(t, item("OpenAI", "Agentless release", "x" * 80, "u"))      # 'agent' inside 'agentless'
    assert not topics.matches(t, item("OpenAI", "Weather model update", "x" * 80, "u"))
    assert topics.matches(t, item("OpenAI Codex releases", "v1.2.3", "x" * 80, "u"))      # topic-specific source


def test_topic_items_drop_covered_urls_and_thin_items():
    t = cfg()["topics"][0]
    its = agent_items(4) + [item("OpenAI", "agent tools", "short", "https://example.com/thin")]
    got = topics.topic_items(t, its, {"https://example.com/agents/0"})
    assert [i.url for i in got] == [f"https://example.com/agents/{k}" for k in (1, 2, 3)]


# ---------- scoring ----------
def test_pick_is_deterministic_and_prefers_fresh_unaired_topic():
    c = cfg()
    its = agent_items(6, age_h=1) + vfx_items(6, age_h=40)
    t, scores, titems = topics.pick(c, its, history([]), NOW)
    t2, _, _ = topics.pick(c, list(reversed(its)), history([]), NOW)
    assert t["id"] == t2["id"] == "agent-harnesses" and len(titems) == 6
    s = {x["id"]: x for x in scores}
    assert s["agent-harnesses"]["novelty"] == 1.0 and s["agent-harnesses"]["score"] > s["ai-vfx"]["score"] > 0
    assert s["agent-harnesses"]["freshness"] <= topics.FRESH_TOP
    # freshness looks at the freshest 12 items, so 70 stale items do not outrank 6 fresh ones
    stale = [item("OpenAI", f"Coding agent {_w(k, 7, 11)} archive", "The coding agent sandbox. " * 6, f"https://example.com/old/{k}", 24 * 10 + k) for k in range(70)]
    _, sc2, _ = topics.pick(c, stale + vfx_items(6, age_h=1), history([]), NOW)
    s2 = {x["id"]: x for x in sc2}
    assert s2["ai-vfx"]["score"] > s2["agent-harnesses"]["score"] > 0


def test_recent_repeat_is_blocked_unless_genuinely_new_news():
    c = cfg()
    last_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 6 * 3600))
    h = history([ep("1", "agent-harnesses", last_ts, [f"https://example.com/agents/{k}" for k in range(3)])])
    # only older agent news (3 covered, 3 uncovered but older than the last episode) -> blocked; vfx wins
    its = agent_items(6, age_h=10) + vfx_items(6)
    t, scores, _ = topics.pick(c, its, h, NOW)
    s = {x["id"]: x for x in scores}
    assert t["id"] == "ai-vfx" and s["agent-harnesses"]["blocked"] and s["agent-harnesses"]["score"] == 0
    # three new uncovered items published after the last episode -> allowed again (lower novelty than vfx though)
    its2 = its + agent_items(3, age_h=1, start=10)
    t2, scores2, _ = topics.pick(c, its2, h, NOW)
    s2 = {x["id"]: x for x in scores2}
    assert s2["agent-harnesses"]["blocked"] is None and 0 < s2["agent-harnesses"]["novelty"] < 1
    assert s2["agent-harnesses"]["new_since_last"] == 3
    # after N episodes it is fully novel again
    eps = [ep("1", "agent-harnesses", last_ts)] + [ep(str(k), "ai-vfx", last_ts[:-1] + "Z") for k in range(2, 2 + c["repeat_after_episodes"])]
    _, scores3, _ = topics.pick(c, agent_items(6), history(eps), NOW)
    assert {x["id"]: x for x in scores3}["agent-harnesses"]["novelty"] == 1.0


def test_unpublished_episode_never_counts_as_covered_or_aired():
    c = cfg()
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 3600))
    e = ep("9", "agent-harnesses", ts, [f"https://example.com/agents/{k}" for k in range(6)])
    e["published"] = False
    t, scores, titems = topics.pick(c, agent_items(6), history([e]), NOW)
    assert t["id"] == "agent-harnesses" and len(titems) == 6 and {x["id"]: x for x in scores}["agent-harnesses"]["novelty"] == 1.0
    assert topics.covered_urls(history([e])) == set() and topics.aired(history([e])) == []


def test_nothing_pickable_falls_back_and_force_overrides():
    c = cfg()
    t, scores, _ = topics.pick(c, make_items(10, NOW), history([]), NOW)   # synthetic items match no topic
    assert t is None and all(s["score"] == 0 for s in scores)
    t, _, titems = topics.pick(c, agent_items(2) + vfx_items(6), history([]), NOW, force="agent-harnesses")
    assert t["id"] == "agent-harnesses" and len(titems) == 2          # forced: even below min_items
    t, _, _ = topics.pick(c, vfx_items(6), history([]), NOW, force="nope")
    assert t["id"] == "ai-vfx"


# ---------- LLM calls ----------
def test_plan_call_orders_validates_and_gates_the_intro():
    t = cfg()["topics"][0]
    its = agent_items(6)
    c = Scripted(lambda s, u: json.dumps({"order": [3, 1, 99, 3, 2], "intro": "Today we look at how coding agents are changing software work. Here is what the sources say."}))
    m = llm.Meter()
    p = topics.plan_call(c, m, t, its)
    assert [i.url for i in p["items"]][:3] == [its[2].url, its[0].url, its[1].url] and len(p["items"]) == 6   # <5 valid -> rest appended
    assert p["intro"] and p["intro_rejected"] is None and m.by_kind == {"plan": m.usd}
    # an intro smuggling a name/number not in the sources is rejected (deterministic gate)
    c2 = Scripted(lambda s, u: json.dumps({"order": [1, 2, 3, 4, 5, 6], "intro": "Today Acme Corp raised 40 million for agents."}))
    p2 = topics.plan_call(c2, llm.Meter(), t, its)
    assert p2["intro"] is None and p2["intro_rejected"] and p2["dropped_by_plan"] == 0


def test_plan_call_uses_plan_model_and_sonnet_price(monkeypatch):
    monkeypatch.setattr(topics, "PLAN_MODEL", "claude-sonnet-5-5")
    c = Scripted(lambda s, u: json.dumps({"order": [1], "intro": ""}), tin=1000, tout=100)
    m = llm.Meter()
    topics.plan_call(c, m, cfg()["topics"][0], agent_items(5))
    assert c.calls[0]["model"] == "claude-sonnet-5-5"
    assert round(m.usd, 6) == round((1000 * 2.0 + 100 * 10.0) / 1e6, 6)   # Sonnet 5.5 prices, not Haiku's


# ---------- stage + history ----------
def test_research_stage_writes_pick_and_history_record_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "topics").mkdir(), (tmp_path / "episodes").mkdir(), (tmp_path / "episode").mkdir()
    import shutil, os
    shutil.copy(os.path.join(os.path.dirname(__file__), "..", "topics", "topics.json"), "topics/topics.json")
    monkeypatch.setattr(topics, "TOPICS_PATH", tmp_path / "topics/topics.json")
    monkeypatch.setattr(topics, "HISTORY_PATH", tmp_path / "episodes/history.json")
    monkeypatch.setenv("NEWSBOT_OFFLINE", "1")          # no topic feeds, no web candidates, no page fetches
    monkeypatch.delenv("NEWSBOT_TOPIC", raising=False)
    its = agent_items(6) + make_items(4, NOW)
    reports = []

    def handler(system, user):
        if system == topics.PLAN_SYS:
            return json.dumps({"order": [2, 1, 3, 4, 5, 6], "intro": "This episode is about coding agents. Here is what the sources say."})
        assert system == discovery.DISCOVERY_SYS
        return json.dumps({"topic": {"id": "acme-widgets", "name": "Acme widgets", "description": "Widgets.", "keywords": ["widget", "acme", "widgets"],
                                     "queries": ["acme widget"], "reason": "many widget items"}})
    m = llm.Meter()
    tr = topics.research_stage(its, reports, NOW, Scripted(handler), m, tmp_path / "episode", log=lambda *a: None)
    info = json.loads((tmp_path / "episode/topic_pick.json").read_text())
    assert info["mode"] == "topic" and info["topic"]["id"] == "agent-harnesses"
    # one source only: the per-source cap (4) would leave fewer than min_items, so it is lifted and all 6 air
    assert [i.url for i in tr["ranked"][:2]] == [its[1].url, its[0].url] and len(tr["ranked"]) == 6
    assert tr["script_extra"]["rundown_title"].endswith("coding agents") and tr["script_extra"]["intro"].startswith("This episode")
    assert info["discovery"]["accepted"] and info["discovery"]["entry"]["id"] == "acme-widgets" and "plan" in m.by_kind and m.calls == 2
    # record: the history gets the episode, topics.json gets the discovered lane entry (once per day)
    script = {"topic": info["topic"], "stories": [{"source": "OpenAI", "url": i.url, "headline": i.title,
                                                   "sentences": [{"text": "A sentence."}]} for i in tr["ranked"][:3]]}
    report = {"topic": {"mode": "topic"}, "llm": {"cost_usd_estimate": 0.0123, "model": "claude-haiku-5-5"}}
    (tmp_path / "episode/script.json").write_text(json.dumps(script))
    (tmp_path / "episode/report.json").write_text(json.dumps(report))
    (tmp_path / "publish.json").write_text(json.dumps({"prefix": "bulletins/x", "objects": 108}))
    r = topics.record(tmp_path, run_id="4242", now=NOW)
    h = json.loads((tmp_path / "episodes/history.json").read_text())
    assert r["published"] and r["topic_added"] == "acme-widgets" and len(h["episodes"]) == 1
    e = h["episodes"][0]
    assert e["topic"] == "agent-harnesses" and e["cost_usd"] == 0.0123 and len(e["stories"]) == 3 and len(e["sentence_sha256"]) == 3 and e["r2_prefix"] == "bulletins/x"
    c2 = json.loads((tmp_path / "topics/topics.json").read_text())
    assert c2["topics"][-1]["lane"] == "discovered" and c2["topics"][-1]["added"] == "2027-01-15" and "settings" in c2 and "_rx" not in c2["topics"][0]
    assert "repeat_after_episodes" not in c2   # settings are written once, under "settings"
    # same run recorded twice: one entry; a second proposal the same day is not added
    topics.record(tmp_path, run_id="4242", now=NOW)
    assert len(json.loads((tmp_path / "episodes/history.json").read_text())["episodes"]) == 1 and len(json.loads((tmp_path / "topics/topics.json").read_text())["topics"]) == 3
    # next run: the covered URLs are excluded and the topic is blocked (aired 0 episodes ago, no new items)
    t, scores, _ = topics.pick(topics.load_topics(), its, topics.load_history(), NOW + 60)
    assert {s["id"]: s for s in scores}["agent-harnesses"]["blocked"]


def test_deepen_reads_leads_first_and_keeps_only_items_with_text(monkeypatch):
    t = cfg()["topics"][0]
    web = [feeds.Item("acme.example", "Lead one", "", "https://acme.example/1", "2026-11-06", NOW - 100),
           feeds.Item("arXiv search", "Paper", "An abstract about agent harnesses. " * 5, "https://arxiv.org/abs/1", "2026-11-06", NOW - 100),
           feeds.Item("acme.example", "Covered lead", "", "https://example.com/agents/0", "2026-11-06", NOW - 100)]
    monkeypatch.setattr(research, "web_candidates", lambda topic, token="", log=print, now=None: (web, [{"api": "x"}]))
    fetched = []

    def fake_enrich(items, max_fetch, max_chars, log):
        fetched.extend(i.url for i in items)
        return [dataclasses.replace(i, summary="Lead text. " * 60) for i in items], [{"url": i.url, "fetched": True, "seconds": 0.1} for i in items]
    monkeypatch.setattr(research, "enrich", fake_enrich)
    pool, rep = topics.deepen(t, agent_items(2), {"https://example.com/agents/0"}, NOW)
    assert fetched == ["https://acme.example/1"]                      # only the uncovered lead without text
    assert [i.url for i in pool] == ["https://example.com/agents/0", "https://example.com/agents/1", "https://arxiv.org/abs/1", "https://acme.example/1"]
    assert rep["web"] == [{"api": "x"}] and len(rep["leads"]) == 1


def test_merge_history_unions_by_run_id():
    a = history([ep("1", "a", "2026-01-01T00:00:00Z"), ep("2", "b", "2026-01-02T00:00:00Z")])
    b = history([ep("2", "b", "2026-01-02T00:00:00Z"), ep("3", "c", "2026-01-03T00:00:00Z")])
    assert [e["run_id"] for e in topics.merge_history(a, b)["episodes"]] == ["1", "2", "3"]


def test_meter_cost_by_kind_feeds_the_shared_budget():
    m = llm.Meter()
    m.add(SimpleNamespace(input_tokens=10_000, output_tokens=1000), kind="plan")
    m.add(SimpleNamespace(input_tokens=10_000, output_tokens=1000), kind="write")
    assert set(m.by_kind) == {"plan", "write"} and round(sum(m.by_kind.values()), 6) == round(m.usd, 6)
