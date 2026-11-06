"""Fetch primary-source feeds politely (robots.txt, UA, timeouts) and normalise items."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from html import unescape
from urllib.parse import urlsplit

import feedparser

UA = "ai-247-newsbot/0.1 (+https://github.com/trotha01/ai-247)"

# Candidate list (more than 8: some hosts block bots or lack feeds; the first 8 that
# pass robots.txt and return items are used; the hourly planner uses every working one). kind: "feed" | "github".
# `limit`: items read per feed (default 15); arXiv lists a whole day of submissions, each with an abstract.
CANDIDATES = [
    {"name": "OpenAI", "kind": "feed", "url": "https://openai.com/news/rss.xml"},
    {"name": "Google DeepMind", "kind": "feed", "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "Google AI", "kind": "feed", "url": "https://blog.google/technology/ai/rss/"},
    {"name": "Hugging Face", "kind": "feed", "url": "https://huggingface.co/blog/feed.xml"},
    {"name": "NVIDIA Developer", "kind": "feed", "url": "https://developer.nvidia.com/blog/feed"},
    {"name": "Microsoft Research", "kind": "feed", "url": "https://www.microsoft.com/en-us/research/feed/"},
    {"name": "arXiv cs.AI", "kind": "feed", "url": "https://rss.arxiv.org/rss/cs.AI", "limit": 60},
    {"name": "Claude Code releases", "kind": "github", "repo": "anthropics/claude-code"},
    {"name": "Anthropic Python SDK", "kind": "github", "repo": "anthropics/anthropic-sdk-python"},
    {"name": "Ollama releases", "kind": "github", "repo": "ollama/ollama"},
    {"name": "llama.cpp releases", "kind": "github", "repo": "ggml-org/llama.cpp"},
    {"name": "Transformers releases", "kind": "github", "repo": "huggingface/transformers"},
    {"name": "PyPI anthropic", "kind": "feed", "url": "https://pypi.org/rss/project/anthropic/releases.xml"},
    {"name": "PyPI openai", "kind": "feed", "url": "https://pypi.org/rss/project/openai/releases.xml"},
]
MAX_FEEDS = 8
MIN_FEEDS = 5


@dataclass
class Item:
    source: str
    title: str
    summary: str
    url: str
    published: str  # ISO date (UTC) or ""
    ts: float = 0.0


@dataclass
class FeedReport:
    name: str
    url: str
    ok: bool
    robots: str  # allowed | disallowed | unknown
    items: int = 0
    note: str = ""
    seconds: float = 0.0


def strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    s = re.sub(r"[#*`_>]+", " ", s)  # light markdown cleanup (GitHub release bodies)
    return re.sub(r"\s+", " ", s).strip()


def robots_allows(url: str, timeout: float = 10.0) -> str:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read(500_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # RFC 9309: 4xx on robots.txt means "no restrictions"
        return "allowed" if 400 <= e.code < 500 else "unknown"
    except Exception:
        return "unknown"
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    return "allowed" if rp.can_fetch(UA, url) else "disallowed"


def _get(url: str, headers: dict | None = None, timeout: float = 20.0) -> bytes:
    h = {"User-Agent": UA, "Accept": "application/atom+xml, application/rss+xml, application/xml, application/json, */*"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read(5_000_000)


def _iso(struct) -> tuple[str, float]:
    if not struct:
        return "", 0.0
    ts = time.mktime(struct) - time.timezone  # struct is UTC
    return time.strftime("%Y-%m-%d", struct), ts


def parse_feed_bytes(name: str, data: bytes, limit: int = 15) -> list[Item]:
    d = feedparser.parse(data)
    m = re.match(r"PyPI recent updates for (\S+)", d.feed.get("title", ""))
    pkg = m.group(1) if m else ""
    out = []
    for e in d.entries[:limit]:
        title = strip_html(e.get("title", ""))
        if pkg and re.match(r"\d", title):
            title = f"{pkg} {title} released"
        body = e.get("summary", "") or (e.get("content") or [{}])[0].get("value", "")
        iso, ts = _iso(e.get("published_parsed") or e.get("updated_parsed"))
        if title and e.get("link"):
            out.append(Item(name, title, strip_html(body), e["link"], iso, ts))
    return out


def parse_github_releases(name: str, repo: str, data: bytes, limit: int = 10) -> list[Item]:
    out = []
    for r in json.loads(data)[:limit]:
        if r.get("draft") or r.get("prerelease"):
            continue
        title = strip_html(r.get("name") or r.get("tag_name") or "")
        tag = r.get("tag_name", "")
        if tag and tag not in title:
            title = f"{repo.split('/')[1]} {tag}" if not title else f"{title} ({tag})"
        iso = (r.get("published_at") or "")[:10]
        ts = time.mktime(time.strptime(iso, "%Y-%m-%d")) if iso else 0.0
        out.append(Item(name, title, strip_html(r.get("body") or ""), r["html_url"], iso, ts))
    return out


def fetch_all(candidates=CANDIDATES, max_feeds: int = MAX_FEEDS, log=print):
    """Return (items, reports). Stops once max_feeds work; skips robots-disallowed hosts."""
    items: list[Item] = []
    reports: list[FeedReport] = []
    working = 0
    token = os.environ.get("GITHUB_TOKEN", "")
    for c in candidates:
        if working >= max_feeds:
            break
        t0 = time.time()
        if c["kind"] == "github":
            url = f"https://api.github.com/repos/{c['repo']}/releases?per_page=10"
            robots = "n/a (API)"
        else:
            url = c["url"]
            robots = robots_allows(url)
        rep = FeedReport(c["name"], url, False, robots)
        if robots == "disallowed":
            rep.note = "robots.txt disallows"
        else:
            try:
                hdr = {"Authorization": f"Bearer {token}"} if (c["kind"] == "github" and token) else {}
                data = _get(url, hdr)
                got = (parse_github_releases(c["name"], c["repo"], data) if c["kind"] == "github"
                       else parse_feed_bytes(c["name"], data, int(c.get("limit", 15))))
                rep.items, rep.ok = len(got), bool(got)
                if got:
                    items += got
                    working += 1
                else:
                    rep.note = "no items"
            except Exception as e:  # network/parse errors are expected for some hosts
                rep.note = f"{type(e).__name__}: {str(e)[:80]}"
        rep.seconds = round(time.time() - t0, 2)
        reports.append(rep)
        log(f"feed {rep.name}: ok={rep.ok} robots={rep.robots} items={rep.items} {rep.note}")
    return items, reports


def reports_json(reports):
    return [asdict(r) for r in reports]
