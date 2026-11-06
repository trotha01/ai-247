"""Bulletin script: story selection, deterministic extractive writer, and the fact check."""
from __future__ import annotations

import re
from collections import Counter

N_STORIES = 4
MAX_HEADLINE_WORDS_SPOKEN = 15
MAX_QUOTE_WORDS = 14

_BAD_SENT = re.compile(r"^(full changelog|what's changed|see the|https?://|\W*$)", re.I)


def words(s: str) -> list[str]:
    return s.split()


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def pick_quote(item) -> str:
    """First usable sentence of the summary, cut at a word boundary to <= MAX_QUOTE_WORDS."""
    for s in sentences(item.summary):
        w = words(s)
        if len(w) >= 5 and not _BAD_SENT.match(s):
            if len(w) > MAX_QUOTE_WORDS:
                return " ".join(w[:MAX_QUOTE_WORDS]).rstrip(",;:") + "..."
            return s
    return ""


def spoken_headline(title: str) -> str:
    w = words(title)
    return title if len(w) <= MAX_HEADLINE_WORDS_SPOKEN else " ".join(w[:MAX_HEADLINE_WORDS_SPOKEN])


def select_items(items, n: int = N_STORIES):
    """Newest first, one per source, requiring a usable quote; falls back to title-only items."""
    items = sorted(items, key=lambda i: i.ts, reverse=True)
    chosen, seen = [], set()
    for require_quote in (True, False):
        for it in items:
            if len(chosen) >= n:
                break
            if it.source in seen or it in chosen:
                continue
            if require_quote and not pick_quote(it):
                continue
            chosen.append(it)
            seen.add(it.source)
    return chosen[:n]


def source_counts(items, top: int = 6):
    c = Counter(i.source for i in items)
    return c.most_common(top)


def story_from_item(it, headline=None, quote=None) -> dict:
    quote = pick_quote(it) if quote is None else quote
    return {
        "source": it.source, "url": it.url, "published": it.published,
        "headline": headline or it.title,
        "quote": quote or it.title,
        "source_text": f"{it.title}. {it.summary}",
    }


def extractive_script(items, counts, n: int = N_STORIES) -> dict:
    """Day 0 stand-in for the LLM: claims are verbatim substrings of the feed text."""
    stories = [story_from_item(it) for it in select_items(items, n)]
    return build_script(stories, counts, "extractive")


def build_script(stories, counts, generated_by: str) -> dict:
    return {
        "generated_by": generated_by,
        "chart": {"title": "Items fetched per source", "data": counts,
                  "source": "Feeds listed on the source cards; fetched at render time"},
        # framing text contains no numbers/entities by design (not a claim)
        "intro": "Here are the latest A I headlines, straight from primary sources. This bulletin is A I generated.",
        "outro": "That is the bulletin. Every item shows its source. Links are in the description.",
        "stories": stories,
    }


# ---- fact check (acceptance test b) -------------------------------------------------

_NUM = re.compile(r"\d[\d,.]*\d|\d")
_TOK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-+/]*")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("’", "'"))


def claim_terms(text: str) -> list[str]:
    """Numbers, acronyms/mixed-case/digit tokens and capitalised words that are not sentence-initial."""
    out = [m.group(0).rstrip(".,") for m in _NUM.finditer(text)]
    sent_start = True
    for m in _TOK.finditer(text):
        tok = m.group(0).rstrip("._-+/")
        before = text[: m.start()].rstrip()
        sent_start = (not before) or before[-1] in ".!?:"
        if not tok or tok.lower() == "...":
            continue
        caps = sum(c.isupper() for c in tok)
        if (caps >= 2 or (caps >= 1 and not sent_start and tok[0].isupper())):
            out.append(tok)
    return out


def missing_terms(claim: str, source_text: str) -> list[str]:
    src = _norm(source_text)
    return sorted({t for t in claim_terms(claim) if _norm(t) not in src})


def check_story(story: dict) -> list[str]:
    """Return the claim terms (numbers / named entities) not found in the story's source text."""
    claim = f"{story['headline']}. {story['quote']}"
    return missing_terms(claim.replace("...", " "), story["source_text"])


def check_script(script: dict) -> dict[int, list[str]]:
    return {i: m for i, s in enumerate(script["stories"]) if (m := check_story(s))}
