"""Rule-based story ranker (Day 1): recency decay x source weight, near-duplicate removal, per-source cap.

No LLM is involved (plan section 12: persistent LLM agents are out of scope).
"""
from __future__ import annotations

import math
import os
import re
import time

HALF_LIFE_H = 48.0          # score halves every 48 h
DEFAULT_WEIGHT = 0.6
# Editorial weights: primary lab announcements > product release notes > research firehose.
SOURCE_WEIGHTS = {
    "OpenAI": 1.0, "Google AI": 0.95, "Google DeepMind": 0.95, "Microsoft Research": 0.85,
    "Claude Code releases": 0.85, "Anthropic Python SDK": 0.6, "Hugging Face": 0.8,
    "NVIDIA Developer": 0.75, "arXiv cs.AI": 0.35,
}
PER_SOURCE_CAP = int(os.environ.get("NEWSBOT_PER_SOURCE_CAP", "2"))  # the hourly slices (newsbot/hourly.py) raise it to 4
MIN_SUMMARY_CHARS = 60      # need a little text to say anything supported
DEDUPE_JACCARD = 0.6

_STOP = {"the", "a", "an", "of", "and", "to", "in", "for", "on", "with", "is", "are", "at", "by", "from", "new", "how"}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP}


def is_duplicate(a, b) -> bool:
    if a.url and a.url == b.url:
        return True
    ta, tb = _tokens(a.title), _tokens(b.title)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= DEDUPE_JACCARD


def score(item, now: float) -> float:
    age_h = max(0.0, (now - item.ts) / 3600.0) if item.ts else 24 * 14.0  # undated items rank as 2 weeks old
    recency = 0.5 ** (age_h / HALF_LIFE_H)
    weight = SOURCE_WEIGHTS.get(item.source, DEFAULT_WEIGHT)
    richness = min(1.0, len(item.summary or "") / 400.0)  # small bonus for items we can actually narrate
    return round(weight * recency * (0.8 + 0.2 * richness), 6)


def rank(items, n: int = 12, now: float | None = None, per_source: int = PER_SOURCE_CAP):
    """Return up to n items in rank order. Pure function of (items, now)."""
    now = time.time() if now is None else now
    pool = [i for i in items if len((i.summary or "").strip()) >= MIN_SUMMARY_CHARS]
    scored = sorted(pool, key=lambda i: (-score(i, now), i.url))
    chosen, per = [], {}
    for it in scored:
        if len(chosen) >= n:
            break
        if per.get(it.source, 0) >= per_source:
            continue
        if any(is_duplicate(it, c) for c in chosen):
            continue
        chosen.append(it)
        per[it.source] = per.get(it.source, 0) + 1
    return chosen


def explain(items, now: float) -> list[dict]:
    return [{"source": i.source, "title": i.title, "published": i.published, "score": score(i, now)} for i in items]
