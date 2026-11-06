"""Synthetic feed items for offline tests (invented companies/products; no real claims)."""
import json
import time

from newsbot import feeds

SOURCES = ["OpenAI", "Google AI", "Hugging Face", "NVIDIA Developer", "Microsoft Research", "arXiv cs.AI",
           "Claude Code releases", "Anthropic Python SDK"]


def _summary(i: int) -> str:
    return (f"Acme Labs released Widget {i}.0 today, a model family built for {TOPICS[i % len(TOPICS)]}. "
            f"The release includes {i + 2} new tools and a faster tokenizer. "
            f"Early partners reported that startup time dropped by {10 + i} percent on laptops. "
            f"Widget {i}.0 is available in the Acme Console starting Monday. "
            f"The company said pricing details will be published in the documentation. "
            f"Engineers at Acme described the training run as the most stable they have completed. "
            f"A migration guide covers the changes from Widget {i - 1}.0.")


TOPICS = ["document search", "robot arms", "protein folding", "speech synthesis", "chip design", "weather models",
          "code review", "satellite imagery", "tutoring", "game agents", "translation", "medical imaging",
          "data centers", "voice cloning safeguards", "math proofs", "energy grids", "video editing", "chatbot memory"]


def make_items(n: int = 18, now: float | None = None):
    now = now or time.time()
    items = []
    for i in range(n):
        src = SOURCES[i % len(SOURCES)]
        ts = now - 3600 * (2 + i * 5)
        pub = time.strftime("%Y-%m-%d", time.gmtime(ts))
        items.append(feeds.Item(src, f"{src} unveils Widget {i}.0 for {TOPICS[i % len(TOPICS)]}", _summary(i),
                                f"https://example.com/{src.split()[0].lower()}/{i}", pub, ts))
    return items


def write_items_json(path, n: int = 18):
    items = make_items(n)
    path.write_text(json.dumps({"items": [i.__dict__ for i in items], "reports": [{"name": s, "ok": True} for s in SOURCES]}))
    return items
