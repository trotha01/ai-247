"""Research + discovery units: recorded bytes, fake fetchers and a scripted Claude client. No network, no key."""
import json
import time
from types import SimpleNamespace

from newsbot import discovery, feeds, llm, research

PAGE = b"""<html><head><title>Acme Labs ships Widget 2</title><style>body{}</style></head><body>
<nav><a href=/>Home</a> <a href=/blog>Blog</a> Products Pricing Docs Careers</nav>
<header>Acme Labs blog menu items here</header>
<main><article>
<h1>Acme Labs ships Widget 2 with a 40 percent faster planner</h1>
<p>Acme Labs today released Widget 2, the second major version of its coding agent harness.</p>
<p>The planner is 40 percent faster than Widget 1 on the SWE-bench Verified suite, the company said in release notes.</p>
<p>Widget 2 adds a sandbox that runs tool calls in isolated containers and ships a Model Context Protocol client.</p>
<p>&ldquo;Agents need guard rails, not just bigger models,&rdquo; said Jane Doe, head of product at Acme Labs.</p>
<script>var tracking = 1;</script>
<p>The release is available today to all customers on the Team and Enterprise plans at no extra cost per seat.</p>
<p>Acme Labs was founded in 2019 and employs 210 people across three offices in Europe and North America.</p>
</article></main>
<footer>Copyright Acme Labs. Cookie settings. Privacy. Terms of use.</footer>
</body></html>"""

ARXIV = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>ArXiv Query</title>
<entry><id>http://arxiv.org/abs/2611.01234v1</id><updated>2026-11-05T17:00:00Z</updated><published>2026-11-05T17:00:00Z</published>
<title>HarnessBench: Measuring Coding Agent Harnesses</title>
<summary>We introduce HarnessBench, a benchmark of 500 tasks that isolates the harness from the model.</summary>
<author><name>A. Author</name></author><author><name>B. Author</name></author>
<link href="http://arxiv.org/abs/2611.01234v1" rel="alternate" type="text/html"/>
<link title="pdf" href="http://arxiv.org/pdf/2611.01234v1" rel="related" type="application/pdf"/>
</entry></feed>"""

GH = json.dumps({"items": [
    {"full_name": "acme/widget", "description": "Coding agent harness with sandboxed tool calls", "html_url": "https://github.com/acme/widget",
     "stargazers_count": 4321, "pushed_at": "2026-11-05T10:00:00Z", "archived": False, "fork": False},
    {"full_name": "someone/fork", "description": "fork", "html_url": "https://github.com/someone/fork", "stargazers_count": 9,
     "pushed_at": "2026-11-05T10:00:00Z", "archived": False, "fork": True},
]}).encode()

HN = json.dumps({"hits": [
    {"title": "Acme Labs ships Widget 2", "url": "https://acme.example/blog/widget-2", "points": 180, "created_at_i": 1793000000},
    {"title": "Ask HN: agents?", "url": None, "points": 50, "created_at_i": 1793000000},
    {"title": "Thread only", "url": "https://news.ycombinator.com/item?id=1", "points": 70, "created_at_i": 1793000000},
]}).encode()


def item(url="https://acme.example/blog/widget-2", summary="Acme Labs today released Widget 2."):
    return feeds.Item("Acme Labs", "Acme Labs ships Widget 2", summary, url, "2026-11-05", 1793000000.0)


# ---------------------------------------------------------------- primary pages
def test_extract_text_keeps_article_prose_and_drops_chrome():
    text = research.extract_text(PAGE.decode())
    assert "40 percent faster" in text and "Model Context Protocol" in text and "Jane Doe" in text
    assert "Cookie settings" not in text and "Careers" not in text and "tracking" not in text
    assert "“Agents need guard rails" in text  # entities unescaped


def test_clip_cuts_at_sentence_boundary():
    text = "One sentence here. Two sentence here. " * 100
    c = research.clip(text, 500)
    assert len(c) <= 500 and c.endswith(".")


def test_enrich_swaps_in_primary_text_and_reports_without_network():
    calls = []

    def fetch(url):
        calls.append(url)
        return (research.extract_text(PAGE.decode()), "") if "acme" in url else ("", "HTTP 404")

    items = [item(), feeds.Item("Other", "Other story", "short summary only", "https://other.example/x", "2026-11-05", 1.0)]
    out, rep = research.enrich(items, fetch=fetch, log=lambda *a: None)
    assert calls == ["https://acme.example/blog/widget-2", "https://other.example/x"]
    assert out[0].summary.startswith("Acme Labs ships Widget 2") and "SWE-bench" in out[0].summary
    assert rep[0]["fetched"] is True and rep[0]["chars_after"] > rep[0]["chars_before"]
    assert out[1].summary == "short summary only" and rep[1]["fetched"] is False and rep[1]["note"] == "HTTP 404"
    assert items[0].summary == "Acme Labs today released Widget 2."  # inputs untouched (copies)


def test_enrich_respects_fetch_budget_and_min_gain():
    long_page = ("Long primary text sentence number one. " * 200)
    items = [item(summary="x" * 50, url=f"https://acme.example/{i}") for i in range(4)]
    out, rep = research.enrich(items, max_fetch=2, max_chars=800, fetch=lambda u: (long_page, ""), log=lambda *a: None)
    assert [r["fetched"] for r in rep] == [True, True, False, False]
    assert rep[2]["note"] == "fetch budget used"
    assert len(out[0].summary) <= 800
    # a page that adds under MIN_GAIN_CHARS keeps the feed summary
    out2, rep2 = research.enrich([item(summary="a" * 100)], fetch=lambda u: ("b" * 200, ""), log=lambda *a: None)
    assert out2[0].summary == "a" * 100 and rep2[0]["fetched"] is False


def test_fetch_page_skips_pdfs_without_touching_network():
    assert research.fetch_page("https://arxiv.org/pdf/2611.01234v1.pdf") == ("", "skipped: not an HTML page")


# ---------------------------------------------------------------- keyless web APIs
def test_parse_arxiv_cites_abstract_page_not_pdf():
    its = research.parse_arxiv(ARXIV)
    assert len(its) == 1 and its[0].url == "https://arxiv.org/abs/2611.01234v1" and its[0].source == "arXiv search"
    assert its[0].summary.startswith("By A. Author, B. Author. We introduce HarnessBench") and its[0].published == "2026-11-05"


def test_parse_github_search_skips_forks_and_states_stars_in_summary():
    its = research.parse_github_search(GH)
    assert [i.url for i in its] == ["https://github.com/acme/widget"]
    assert "4321 stars" in its[0].summary and its[0].published == "2026-11-05"


def test_hn_hits_are_leads_to_the_primary_url_only():
    its = research.parse_hn_leads(HN)
    assert len(its) == 1 and its[0].url == "https://acme.example/blog/widget-2" and its[0].source == "acme.example"
    assert its[0].summary == ""  # must be enriched before it can be written about


def test_web_candidates_uses_topic_queries_dedupes_and_reports_failures():
    topic = {"name": "Agent harnesses", "queries": ["coding agent harness"]}
    seen = []

    def get(url, hdr):
        seen.append((url, hdr))
        if "arxiv" in url:
            return ARXIV
        if "api.github.com" in url:
            assert hdr.get("Authorization") == "Bearer t0k"
            return GH
        raise OSError("boom")

    items, rep = research.web_candidates(topic, token="t0k", get=get, log=lambda *a: None, now=1793000000.0)
    assert [r["api"] for r in rep] == ["arXiv search", "GitHub search", "HN lead"]
    assert [r["items"] for r in rep] == [1, 1, 0] and rep[2]["note"].startswith("OSError")
    since = time.strftime("%Y-%m-%d", time.gmtime(1793000000.0 - 7 * 86400))
    assert f"pushed%3A%3E{since}" in seen[1][0] and "sortBy=submittedDate" in seen[0][0]
    assert {i.source for i in items} == {"arXiv search", "GitHub search"}


# ---------------------------------------------------------------- discovery lane (web search, Fable, no daily cap)
class Scripted:
    """Fake client: `reply` is the text block; `results` become a web_search_tool_result block (list of results)."""
    def __init__(self, reply, results=None, searches=0, stop="end_turn", fail_first=None):
        self.reply, self.results, self.searches, self.stop, self.fail_first = reply, results or [], searches, stop, fail_first
        self.calls, self.messages = [], self

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail_first and len(self.calls) == 1:
            raise self.fail_first
        content = []
        if self.results:
            content.append(SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(type="web_search_result", url=u, title=t) for u, t in self.results]))
        content.append(SimpleNamespace(type="text", text=self.reply))
        return SimpleNamespace(content=content, stop_reason=self.stop,
                               usage=SimpleNamespace(input_tokens=900, output_tokens=150, server_tool_use=SimpleNamespace(web_search_requests=self.searches)))


class BadRequestError(Exception):
    pass


TOPICS = {"settings": {},
          "topics": [{"id": "agent-harnesses", "name": "AI agent harnesses and coding agents", "lane": "seed",
                      "keywords": ["agent", "coding agent", "harness", "mcp"], "added": "2026-11-01"}]}
ITEMS = [feeds.Item("S", "World models for robots: a new wave of simulators", "robot world model training", "https://a/1", "2026-11-06", 1.0),
         feeds.Item("S", "Open world-model release lets robots plan in simulation", "", "https://a/2", "2026-11-06", 1.0),
         feeds.Item("S", "Widget 2 coding agent harness", "", "https://a/3", "2026-11-06", 1.0)]
LINKS = ["https://arxiv.org/abs/2611.02222", "https://github.com/acme/world-sim", "https://news.ycombinator.com/item?id=5", "https://made.up/x"]
RESULTS = [("https://arxiv.org/abs/2611.02222", "Learned world models for robot planning"), ("https://github.com/acme/world-sim", "acme/world-sim: robot simulator")]
PROPOSAL = {"topic": {"id": "robot-world-models", "name": "World models for robotics", "description": "Simulators learned from video that robots plan in.",
                      "keywords": ["world model", "world-model", "robots", "simulation", "simulator", "robot"],
                      "queries": ["robot world model"], "links": LINKS, "reason": "Two items today are about learned simulators for robots."}}


def test_discovery_uses_fable_with_web_search_and_keeps_only_seen_primary_links():
    c, meter = Scripted(json.dumps(PROPOSAL), RESULTS, searches=2), llm.Meter()
    e = discovery.propose(c, meter, ITEMS, TOPICS, "2026-11-06", log=lambda *a: None)
    assert e and e["id"] == "robot-world-models" and e["lane"] == "discovered" and e["added"] == "2026-11-06"
    assert e["seed_urls"] == ["https://arxiv.org/abs/2611.02222", "https://github.com/acme/world-sim"]   # HN thread + unseen URL dropped
    assert "4 matching items/links" in e["reason"]   # 2 feed items + 2 primary links
    kw = c.calls[0]
    assert kw["model"] == "claude-fable-5-1" and kw["output_config"] == {"effort": "low"} and "thinking" not in kw
    assert kw["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": discovery.MAX_SEARCHES}]
    assert meter.calls == 1 and meter.searches == 2 and round(meter.usd, 6) == round((900 * 10 + 150 * 50) / 1e6 + 0.02, 6)
    assert kw["system"] == discovery.DISCOVERY_SYS and "CURRENT TOPICS" in kw["messages"][0]["content"]


def test_discovery_falls_back_to_basic_search_tool_on_400_and_handles_refusal_and_garbage():
    c = Scripted(json.dumps(PROPOSAL), RESULTS, fail_first=BadRequestError("tools.0: web_search_20260209 is not supported"))
    e = discovery.propose(c, llm.Meter(), ITEMS, TOPICS, "2026-11-06", log=lambda *a: None)
    assert e and len(c.calls) == 2 and c.calls[1]["tools"][0]["type"] == "web_search_20250305"
    assert discovery.propose(Scripted("", stop="refusal"), llm.Meter(), ITEMS, TOPICS, "2026-11-06", log=lambda *a: None) is None
    assert discovery.propose(Scripted('{"topic": null}'), llm.Meter(), ITEMS, TOPICS, "2026-11-06", log=lambda *a: None) is None
    assert discovery.propose(Scripted("not json at all"), llm.Meter(), ITEMS, TOPICS, "2026-11-06", log=lambda *a: None) is None


def test_discovery_gates_similar_unmatched_malformed_and_has_no_daily_cap():
    today, found = "2026-11-06", dict(RESULTS)
    assert discovery.validate(None, ITEMS, TOPICS, today, found) == (None, "no proposal")
    dup = {**PROPOSAL["topic"], "id": "agent-harness-tools", "name": "Agent harness tooling", "keywords": ["agent", "harness", "mcp", "tools"]}
    assert discovery.validate(dup, ITEMS, TOPICS, today, found)[1].startswith("similar to existing topic")
    ghost = {**PROPOSAL["topic"], "id": "quantum-llms", "name": "Quantum LLMs", "keywords": ["quantum", "qubit", "annealing"], "links": []}
    assert discovery.validate(ghost, ITEMS, TOPICS, today, found)[1].startswith("only 0 matching")
    bad = {**PROPOSAL["topic"], "id": "Not A Slug!"}
    assert discovery.validate(bad, ITEMS, TOPICS, today, found) == (None, "bad id or name")
    # web-only evidence: no feed item matches, but two seen primary links do -> accepted
    webonly = {**PROPOSAL["topic"], "id": "robot-sim-x", "name": "Robot sim x", "keywords": ["world-sim", "robot planning", "simulator"]}
    e, why = discovery.validate(webonly, [], TOPICS, today, found)
    assert e and why == "ok" and len(e["seed_urls"]) == 2
    # two discovered topics already added today: still accepted (no per-day cap)
    many = {**TOPICS, "topics": TOPICS["topics"] + [{"id": f"x{i}", "name": f"X{i}", "lane": "discovered", "added": today, "keywords": ["zz"]} for i in range(2)]}
    assert discovery.added_today(many, today) == 2
    assert discovery.validate(PROPOSAL["topic"], ITEMS, many, today, found)[1] == "ok"
    assert not discovery.primary_link("https://www.reddit.com/r/x") and discovery.primary_link("https://openai.com/index/x")
