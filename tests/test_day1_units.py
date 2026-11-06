"""Day 1 unit tests: ranker, Haiku writer + fact-check with a recorded/mock client (no key needed), fallback."""
import json
import time
from types import SimpleNamespace

import pytest

from newsbot import episode, feeds, llm, rank, script as sm
from tests.fixtures import make_items


# ---------- ranker ----------
def test_rank_is_rule_based_and_deterministic():
    now = time.time()
    items = make_items(18, now)
    a, b = rank.rank(items, 12, now), rank.rank(list(reversed(items)), 12, now)
    assert [i.url for i in a] == [i.url for i in b] and len(a) == 12


def test_rank_recency_and_source_weight():
    now = time.time()
    new = feeds.Item("arXiv cs.AI", "Paper about things", "x" * 200, "https://a/1", "", now - 3600)
    old = feeds.Item("OpenAI", "Announcement of stuff", "x" * 200, "https://a/2", "", now - 3600 * 24 * 10)
    assert rank.score(new, now) > rank.score(old, now)          # recency dominates
    same_age = feeds.Item("OpenAI", "Announcement of stuff", "x" * 200, "https://a/3", "", now - 3600)
    assert rank.score(same_age, now) > rank.score(new, now)     # at equal age, source weight wins


def test_rank_dedupes_and_caps_per_source():
    now = time.time()
    mk = lambda src, title, url: feeds.Item(src, title, "y" * 200, url, "", now - 100)
    items = [mk("OpenAI", "GPT six released today with tools", "https://a/1"),
             mk("Google AI", "GPT six released today with tools!", "https://a/2"),   # near-duplicate title
             mk("OpenAI", "Different story one", "https://a/3"), mk("OpenAI", "Another story two", "https://a/4"),
             mk("OpenAI", "Third separate item", "https://a/5")]
    got = rank.rank(items, 10, now)
    assert len([i for i in got if i.source == "OpenAI"]) <= rank.PER_SOURCE_CAP
    assert not ({"https://a/1", "https://a/2"} <= {i.url for i in got})
    assert rank.rank([mk("OpenAI", "thin", "u")] and [feeds.Item("OpenAI", "t", "short", "u", "", now)], 5, now) == []


# ---------- LLM path with a scripted client ----------
class Scripted:
    """Minimal stand-in for anthropic.Anthropic(): handler(system, user) -> reply text (recorded behaviour)."""
    def __init__(self, handler, tin=700, tout=120):
        self.handler, self.calls, self.messages = handler, [], self
        self.tin, self.tout = tin, tout

    def create(self, **kw):
        self.calls.append(kw)
        txt = self.handler(kw["system"], kw["messages"][0]["content"])
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=txt)],
                               usage=SimpleNamespace(input_tokens=self.tin, output_tokens=self.tout))


def good_handler(system, user):
    if system == llm.WRITER_SYS:
        return json.dumps({"headline": "Acme Labs released Widget 1.0", "sentences": [
            "Acme Labs released Widget 1.0 today.", "The release includes 3 new tools and a faster tokenizer.",
            "Widget 1.0 is available in the Acme Console starting Monday."]})
    if system == llm.CHECKER_SYS:
        n = user.count("\n") and len([l for l in user.split("SENTENCES:")[1].splitlines() if l.strip()])
        return json.dumps({"verdicts": [{"i": i, "supported": True, "reason": "stated"} for i in range(n)]})
    raise AssertionError("unexpected call")


def test_llm_skipped_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.write_episode_script(make_items(3), [])[0] is None


def test_llm_episode_path_fresh_context_checker():
    c = Scripted(good_handler)
    items = [make_items(8)[1]]
    s, st = llm.write_episode_script(items, [], client=c)
    assert st["llm_stories"] == 1 and s["generated_by"].endswith("+factcheck")
    # the checker call is a fresh context: only SOURCE + SENTENCES, never the writer's prompt/instructions
    chk = [k for k in c.calls if k["system"] == llm.CHECKER_SYS][0]
    assert len(chk["messages"]) == 1 and "headline" not in chk["messages"][0]["content"].lower().split("sentences:")[0]
    for story in s["stories"]:
        assert all(x["supported"] for x in story["sentences"]) and sm.story_problems(story) == {}


def test_unsupported_sentence_is_rewritten_or_dropped_never_aired():
    item = make_items(8)[1]
    ungrounded = "Acme Labs said Widget 1.0 beats Google by 40 percent."

    def handler(system, user):
        if system == llm.WRITER_SYS:
            return json.dumps({"headline": "Acme Labs released Widget 1.0", "sentences": [
                "Acme Labs released Widget 1.0 today.", ungrounded, "The release includes 3 new tools and a faster tokenizer."]})
        if system == llm.CHECKER_SYS:   # a sloppy LLM checker that approves everything...
            n = len([l for l in user.split("SENTENCES:")[1].splitlines() if l.strip()])
            return json.dumps({"verdicts": [{"i": i, "supported": True, "reason": "ok"} for i in range(n)]})
        return json.dumps({"rewrites": [None]})   # repair: cannot be supported
    s, st = llm.write_episode_script([item], [], client=Scripted(handler))
    texts = [x["text"] for x in s["stories"][0]["sentences"]]
    assert ungrounded not in texts and len(texts) == 2          # ...but the deterministic gate still drops it
    assert st["dropped"] >= 1


def test_checker_rejection_is_repaired_and_rechecked():
    item = make_items(8)[1]
    state = {"n": 0}

    def handler(system, user):
        if system == llm.WRITER_SYS:
            return json.dumps({"headline": "Acme Labs released Widget 1.0", "sentences": [
                "Acme Labs released Widget 1.0 today.", "Widget 1.0 will change everything.", "The release includes 3 new tools."]})
        if system == llm.CHECKER_SYS:
            lines = [l for l in user.split("SENTENCES:")[1].splitlines() if l.strip()]
            return json.dumps({"verdicts": [{"i": i, "supported": "change everything" not in l, "reason": "hype"} for i, l in enumerate(lines)]})
        return json.dumps({"rewrites": ["Widget 1.0 is available in the Acme Console starting Monday."]})
    s, st = llm.write_episode_script([item], [], client=Scripted(handler))
    texts = [x["text"] for x in s["stories"][0]["sentences"]]
    assert "Widget 1.0 will change everything." not in texts
    assert "Widget 1.0 is available in the Acme Console starting Monday." in texts
    assert st["rewritten"] == 1 and st["rewritten_supported"] == 1


def test_story_falls_back_to_extractive_when_llm_returns_garbage():
    s, st = llm.write_episode_script([make_items(8)[1]], [], client=Scripted(lambda sys_, u: "not json"))
    story = s["stories"][0]
    assert st["fallback_stories"] == 1 and s["generated_by"] == "extractive"
    assert all(x["method"] == "verbatim" for x in story["sentences"]) and sm.story_problems(story) == {}


def test_budget_abort_at_cap_uses_current_prices(monkeypatch):
    assert llm.PRICES["claude-haiku-5-5"] == (0.10, 0.50) and llm.PRICES["claude-sonnet-5-5"] == (2.0, 10.0)
    assert llm.MAX_RUN_USD == 0.75   # topic stage on Fable 5.1 (docs/TOPICS.md); the Haiku digest alone stays far under 0.05
    m = llm.Meter()
    m.add(SimpleNamespace(input_tokens=100_000, output_tokens=0))
    assert round(m.usd, 6) == round(0.1 * llm.PRICE_IN, 6)
    # a huge-output client: spend must stop before the cap is crossed, remaining stories go extractive
    monkeypatch.setattr(llm, "MAX_RUN_USD", 0.004)
    c = Scripted(good_handler, tin=3000, tout=2000)
    s, st = llm.write_episode_script(make_items(6)[:4], [], client=c)
    assert st["budget_abort"] and st["cost_usd_estimate"] <= 0.004 + 1e-9
    assert st["fallback_stories"] >= 1 and len(s["stories"]) == 4


def test_preflight_blocks_call_that_could_cross_cap(monkeypatch):
    monkeypatch.setattr(llm, "MAX_RUN_USD", 0.0001)
    c = Scripted(good_handler)
    s, st = llm.write_episode_script(make_items(3)[:1], [], client=c)
    assert c.calls == [] and st["budget_abort"]


# ---------- extractive + sentence helpers ----------
def test_extractive_story_is_verbatim_and_sourced():
    it = make_items(3)[2]
    st = sm.extractive_story(it)
    assert 2 <= len(st["sentences"]) <= sm.MAX_STORY_SENTENCES and st["url"].startswith("http")
    for x in st["sentences"]:
        assert x["text"].rstrip(".") .replace("...", "") in it.summary or x["text"].rstrip(".") in it.summary
    assert sm.story_problems(st) == {}


def test_split_sentences_handles_abbreviations():
    got = sm.split_sentences("Dr. Smith of Acme Inc. said the model scored 3.5 on the test. It launches Monday.")
    assert len(got) == 2


# ---------- episode planning ----------
def test_story_scenes_every_claim_scene_has_citation():
    story = sm.extractive_story(make_items(3)[2])
    scenes = episode.story_scenes(0, story)
    assert scenes[0]["kind"] == "headline" and scenes[-1]["kind"] == "source"
    for sc in scenes:
        assert sc["citation"]["url"].startswith("http") and sc["citation"]["source"]
    assert sum(1 for s in scenes if s["kind"] == "sentence") == len(story["sentences"])


def test_scene_durations_are_whole_frames_and_samples():
    for secs in (0.2, 3.77, 4.01, 9.99):
        d = episode.frame_dur(secs)
        assert d >= episode.MIN_SCENE and (d * 30) == int(d * 30) and (d * 48000) == int(d * 48000)


class FakeTts:
    """Writes silence whose length follows the word count (about 2.6 words/s), like a real voice."""
    speed = 1.0

    def synth(self, text, path):
        import subprocess
        secs = max(0.6, len(text.split()) / 2.6)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{secs:.2f}", path],
                       check=True, capture_output=True)


def test_build_episode_hits_exactly_600s_with_chart_scene_and_pad(tmp_path):
    stories = [sm.extractive_story(i) for i in make_items(18)[:12]]
    script = sm.build_episode_script(stories, [("OpenAI", 15), ("Google AI", 10)], "extractive")
    scenes, chosen, info = episode.build_episode(script, FakeTts(), tmp_path)
    assert abs(sum(s["duration"] for s in scenes) - 600.0) < 1e-6
    assert scenes[0]["kind"] == "rundown" and scenes[1]["kind"] == "chart" and scenes[-2]["kind"] == "outro"
    assert scenes[-1]["kind"] == "standby" and info["pad_seconds"] >= 0  # pad is large only because all 12 stories were used
    assert 1 <= len(chosen) <= 12 and all(s["claims"] == [] for s in scenes if s["kind"] in ("chart", "standby", "rundown"))
