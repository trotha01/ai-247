"""Topic research: deepen the picked topic's items with primary sources and keyless web APIs.

Two jobs, both pure apart from the injected fetch function (tests use recorded bytes, no network):

  enrich(items, ...)          -> (items, report): fetch each item's primary page politely (robots.txt with our UA,
                                 20 s timeout, 1 MB cap, text/html only, at most MAX_FETCH pages) and replace the
                                 short feed summary with up to MAX_CHARS characters of the page's text. The writer and
                                 the fresh-context fact check then work from the primary text, not a two-line blurb.
  web_candidates(topic, ...)  -> (items, report): extra candidates for a topic from public APIs that need no key:
                                 arXiv API (abstract pages), GitHub REST repository search (recently pushed, most
                                 stars) and Hacker News Algolia (stories with >= HN_MIN_POINTS points) used only as
                                 LEADS: the story's target URL becomes the item, never the HN thread.

Nothing here writes claims. Every returned Item keeps a real primary URL so the citation card stays honest.
"""
from __future__ import annotations

import dataclasses
import html as _html
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote_plus, urlsplit

import feedparser

from . import feeds

MAX_FETCH = 8          # primary pages per run
MAX_CHARS = 6000       # characters of primary text per story
MIN_GAIN_CHARS = 400   # a page must add at least this much over the feed summary to be worth swapping in
MAX_BYTES = 1_000_000
TIMEOUT = 20.0
HN_MIN_POINTS = 20
GITHUB_PUSHED_DAYS = 7
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
SKIP_SUFFIXES = (".pdf", ".zip", ".tar", ".gz", ".mp4", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webm")

_DROP = re.compile(r"<(script|style|nav|header|footer|aside|noscript|svg|form|iframe)[^>]*>.*?</\1>", re.S | re.I)
_MAIN = re.compile(r"<(article|main)[^>]*>(.*?)</\1>", re.S | re.I)
_BLOCK = re.compile(r"</?(p|div|br|li|h[1-6]|tr|section|blockquote|pre)[^>]*>", re.I)


# ----------------------------------------------------------------------------------------------- primary pages
def extract_text(page: str) -> str:
    """Readable text of an HTML page: <article>/<main> if present, boilerplate tags dropped, paragraphs joined."""
    page = _DROP.sub(" ", page)
    m = _MAIN.search(page)
    body = m.group(2) if m and len(feeds.strip_html(m.group(2))) >= MIN_GAIN_CHARS else page
    body = _BLOCK.sub("\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = _html.unescape(body)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in body.split("\n")]
    # keep lines that read like prose (drop menus, cookie banners, single words)
    kept = [ln for ln in lines if len(ln.split()) >= 4]
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def clip(text: str, max_chars: int = MAX_CHARS) -> str:
    """Clip at a sentence boundary at or before max_chars (word boundary as a fallback)."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    m = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if m >= max_chars // 2:
        return cut[: m + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "..."


def fetch_page(url: str, timeout: float = TIMEOUT, max_bytes: int = MAX_BYTES) -> tuple[str, str]:
    """Return (text, note). note is '' on success, otherwise why nothing was fetched. Never raises."""
    if url.lower().split("?")[0].endswith(SKIP_SUFFIXES):
        return "", "skipped: not an HTML page"
    robots = feeds.robots_allows(url, timeout=min(timeout, 10.0))
    if robots == "disallowed":
        return "", "robots.txt disallows"
    req = urllib.request.Request(url, headers={"User-Agent": feeds.UA, "Accept": "text/html, application/xhtml+xml, text/plain;q=0.8, */*;q=0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if not any(t in ctype for t in TEXT_TYPES):
                return "", f"skipped: content type {ctype.split(';')[0] or 'unknown'}"
            data = r.read(max_bytes)
    except urllib.error.HTTPError as e:
        return "", f"HTTP {e.code}"
    except Exception as e:  # timeouts, DNS, TLS: expected for some hosts
        return "", f"{type(e).__name__}"
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype)
    if m:
        charset = m.group(1)
    try:
        page = data.decode(charset, "replace")
    except LookupError:
        page = data.decode("utf-8", "replace")
    return (page if "text/plain" in ctype else extract_text(page)), ""


def enrich(items, max_fetch: int = MAX_FETCH, max_chars: int = MAX_CHARS, fetch=fetch_page, log=print, skip_urls=()):
    """Replace short feed summaries with primary-page text for the first max_fetch items (rank order).

    Returns (new_items, report). Items are copies; an item whose page gives no gain keeps its feed summary.
    The source_text the writer and checker see is title + summary (newsbot.script.make_story), so a longer summary
    is exactly what lets Haiku say more while every sentence stays checkable against one source."""
    out, report, fetched = [], [], 0
    for it in items:
        rec = {"source": it.source, "url": it.url, "fetched": False, "chars_before": len(it.summary or ""), "chars_after": len(it.summary or ""), "note": ""}
        if it.url in skip_urls:
            rec["note"] = "already read this run"
        elif fetched < max_fetch and it.url.startswith("http"):
            t0 = time.time()
            text, note = fetch(it.url)
            fetched += 1
            rec["seconds"] = round(time.time() - t0, 2)
            if text and len(text) >= len(it.summary or "") + MIN_GAIN_CHARS:
                body = clip(text, max_chars)
                it = dataclasses.replace(it, summary=body)
                rec.update(fetched=True, chars_after=len(body))
            else:
                rec["note"] = note or f"page text not longer than the feed summary ({len(text)} chars)"
        elif fetched >= max_fetch:
            rec["note"] = "fetch budget used"
        out.append(it)
        report.append(rec)
        log(f"research {it.source}: fetched={rec['fetched']} chars {rec['chars_before']}->{rec['chars_after']} {rec['note']}")
    return out, report


# ----------------------------------------------------------------------------------------------- keyless web APIs
def _queries(topic: dict) -> list[str]:
    q = [s for s in topic.get("queries", []) if isinstance(s, str) and s.strip()]
    return q[:4] or [topic.get("name", "")]


def arxiv_url(query: str, n: int = 10) -> str:
    q = quote_plus(f'all:"{query}"' if " " in query else f"all:{query}")
    return f"https://export.arxiv.org/api/query?search_query={q}&sortBy=submittedDate&sortOrder=descending&max_results={n}"


def parse_arxiv(data: bytes, limit: int = 10) -> list[feeds.Item]:
    """arXiv Atom entries -> Items citing the abstract page (the writer never sees the PDF)."""
    out = []
    for e in feedparser.parse(data).entries[:limit]:
        link = next((l.get("href") for l in e.get("links", []) if l.get("type") == "text/html"), None) or e.get("link") or e.get("id", "")
        link = link.replace("http://", "https://")
        iso, ts = feeds._iso(e.get("published_parsed") or e.get("updated_parsed"))
        authors = ", ".join(a.get("name", "") for a in e.get("authors", [])[:3])
        title = feeds.strip_html(e.get("title", ""))
        summary = feeds.strip_html(e.get("summary", ""))
        if title and link:
            out.append(feeds.Item("arXiv search", title, (f"By {authors}. " if authors else "") + summary, link, iso, ts))
    return out


def github_search_url(query: str, days: int = GITHUB_PUSHED_DAYS, n: int = 8, now: float | None = None) -> str:
    since = time.strftime("%Y-%m-%d", time.gmtime((time.time() if now is None else now) - days * 86400))
    return f"https://api.github.com/search/repositories?q={quote_plus(query + ' pushed:>' + since)}&sort=stars&order=desc&per_page={n}"


def parse_github_search(data: bytes, limit: int = 8) -> list[feeds.Item]:
    out = []
    for r in json.loads(data).get("items", [])[:limit]:
        if r.get("archived") or r.get("fork"):
            continue
        desc = feeds.strip_html(r.get("description") or "")
        name = r.get("full_name", "")
        summary = (f"{name} is a GitHub repository with {r.get('stargazers_count', 0)} stars. {desc}").strip()
        iso = (r.get("pushed_at") or "")[:10]
        ts = time.mktime(time.strptime(iso, "%Y-%m-%d")) if iso else 0.0
        if name and r.get("html_url"):
            out.append(feeds.Item("GitHub search", f"{name}: {desc}" if desc else name, summary, r["html_url"], iso, ts))
    return out


def hn_url(query: str, n: int = 10, min_points: int = HN_MIN_POINTS) -> str:
    return (f"https://hn.algolia.com/api/v1/search_by_date?query={quote_plus(query)}&tags=story"
            f"&numericFilters={quote_plus(f'points>={min_points}')}&hitsPerPage={n}")


def parse_hn_leads(data: bytes, limit: int = 10) -> list[feeds.Item]:
    """HN stories as leads: the item is the linked primary URL, named after its host. No URL -> not a lead."""
    out = []
    for h in json.loads(data).get("hits", [])[:limit]:
        url = h.get("url") or ""
        if not url.startswith("http") or "news.ycombinator.com" in url:
            continue
        host = urlsplit(url).netloc.lower().removeprefix("www.")
        ts = float(h.get("created_at_i") or 0)
        iso = time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else ""
        title = feeds.strip_html(h.get("title") or "")
        if title:
            # summary is empty on purpose: the lead is only usable once enrich() fetched the primary page
            out.append(feeds.Item(host, title, "", url, iso, ts))
    return out


def web_candidates(topic: dict, token: str = "", get=None, log=print, now: float | None = None):
    """Items for a topic from the keyless APIs. Returns (items, report); failures are reported, never raised."""
    get = get or feeds._get
    items, report = [], []
    hdr_gh = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"} if token else {"Accept": "application/vnd.github+json"}
    plan = []
    for q in _queries(topic):
        plan.append(("arXiv search", arxiv_url(q), {}, parse_arxiv))
        plan.append(("GitHub search", github_search_url(q, now=now), hdr_gh, parse_github_search))
        plan.append(("HN lead", hn_url(q), {}, parse_hn_leads))
    seen = set()
    for name, url, hdr, parse in plan:
        t0 = time.time()
        rec = {"api": name, "url": url, "items": 0, "note": ""}
        try:
            got = parse(get(url, hdr))
            fresh = [i for i in got if i.url not in seen]
            seen.update(i.url for i in fresh)
            items += fresh
            rec["items"] = len(fresh)
        except Exception as e:
            rec["note"] = f"{type(e).__name__}: {str(e)[:80]}"
        rec["seconds"] = round(time.time() - t0, 2)
        report.append(rec)
        log(f"web {name}: items={rec['items']} {rec['note']}")
    return items, report


def topic_sources(topic: dict, log=print):
    """A topic's own feeds / GitHub release repos (same shape as feeds.CANDIDATES), via feeds.fetch_all."""
    cands = [c for c in topic.get("sources", []) if isinstance(c, dict) and c.get("kind") in ("feed", "github")]
    if not cands:
        return [], []
    items, reports = feeds.fetch_all(cands, max_feeds=len(cands), log=log)
    return items, feeds.reports_json(reports)
