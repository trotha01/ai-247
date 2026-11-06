"""Pluggable Claude Haiku script writer + fact-check pass.

Runs only when ANTHROPIC_API_KEY is set. The key is read from the environment by the SDK
and is never printed or logged. Per-run spend is tracked and aborts above MAX_RUN_USD.
"""
from __future__ import annotations

import json
import os

from .script import build_script, check_story, story_from_item, select_items

MODEL = os.environ.get("NEWSBOT_MODEL", "claude-haiku-5-5")
MAX_RUN_USD = float(os.environ.get("NEWSBOT_MAX_RUN_USD", "0.05"))
# USD per million tokens. ASSUMED, verify against current pricing before relying on the cap.
PRICE_IN = float(os.environ.get("NEWSBOT_PRICE_IN", "1.0"))
PRICE_OUT = float(os.environ.get("NEWSBOT_PRICE_OUT", "5.0"))


class BudgetExceeded(RuntimeError):
    pass


class Meter:
    def __init__(self):
        self.usd = 0.0

    def add(self, usage):
        self.usd += (usage.input_tokens * PRICE_IN + usage.output_tokens * PRICE_OUT) / 1e6
        if self.usd > MAX_RUN_USD:
            raise BudgetExceeded(f"run cost {self.usd:.4f} USD exceeds cap {MAX_RUN_USD}")


def _ask(client, meter, system, user, max_tokens=300) -> str:
    r = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                               messages=[{"role": "user", "content": user}])
    meter.add(r.usage)
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")


WRITE_SYS = ("You write one-line news bulletin lines. Use ONLY facts, numbers and names that appear in the "
             "provided source text. Reply with JSON: {\"headline\": str (<=14 words), \"quote\": str (<=14 words, one sentence)}.")
CHECK_SYS = ("You are a strict fact checker. Reply with JSON {\"supported\": bool}: true only if every claim in "
             "the draft is directly supported by the source text.")


def write_with_claude(items, counts, client=None, n=4):
    """Return a script dict, or None if the key is absent. Stories failing the fact check are dropped."""
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        import anthropic  # lazy: only needed on this path
        client = anthropic.Anthropic()
    meter = Meter()
    stories = []
    for it in select_items(items, n + 2):
        src = f"{it.title}. {it.summary}"[:3000]
        try:
            draft = json.loads(_ask(client, meter, WRITE_SYS, f"Source: {src}"))
            story = story_from_item(it, headline=draft["headline"], quote=draft["quote"])
            verdict = json.loads(_ask(client, meter, CHECK_SYS,
                                      f"Source: {src}\nDraft: {story['headline']} / {story['quote']}", 50))
        except BudgetExceeded:
            raise
        except Exception:
            continue
        if verdict.get("supported") is True and not check_story(story):
            stories.append(story)
        if len(stories) >= n:
            break
    if len(stories) < n:
        return None
    s = build_script(stories, counts, MODEL)
    s["cost_usd_estimate"] = round(meter.usd, 5)
    return s
