#!/usr/bin/env python3
"""Producer loop for the language channel: keeps the worker's inbox TARGET lesson scripts deep, forever.

    python -m lang.producer_loop --root /hyperai/home/loop/lang

Same shape as studio/pipeline/producer_loop.py (queue of finished work ahead of the worker), but no LLM: each lesson
is lang.lesson.lesson(n), deterministic from the committed pool. The next lesson number lives in ROOT/producer/next_n,
so a restart carries on where it stopped. Files are written as .tmp and renamed, so the worker never reads half a
script. touch ROOT/STOP to stop the producer and the worker.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lang.lesson import lesson  # noqa: E402


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fill(root: Path, target: int) -> int:
    """Top the inbox up to `target` scripts; returns how many were written."""
    inbox, pdir = root / "inbox", root / "producer"
    inbox.mkdir(parents=True, exist_ok=True)
    pdir.mkdir(parents=True, exist_ok=True)
    state = pdir / "next_n"
    n = int(state.read_text().strip() or 0) if state.exists() else 0
    have = len(list(inbox.glob("*.json")))
    wrote = 0
    while have < target:
        sc = lesson(n)
        tmp = inbox / f".{sc['id']}.tmp"
        tmp.write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, inbox / f"{sc['id']}.json")
        n += 1
        state.write_text(f"{n}\n")
        with open(pdir / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "n": sc["n"], "id": sc["id"], "ref": sc["ref"]}) + "\n")
        have += 1
        wrote += 1
    return wrote


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=Path("/hyperai/home/loop/lang"))
    ap.add_argument("--target", type=int, default=12, help="lesson scripts to keep waiting in the inbox")
    ap.add_argument("--start", type=int, default=None, help="set the next lesson number (once, at start)")
    ap.add_argument("--once", action="store_true", help="fill the inbox once and exit")
    a = ap.parse_args(argv)
    if a.start is not None:
        (a.root / "producer").mkdir(parents=True, exist_ok=True)
        (a.root / "producer" / "next_n").write_text(f"{a.start}\n")
    log(f"lang producer: root {a.root}, keeping {a.target} lessons ahead")
    while not (a.root / "STOP").exists():
        try:
            w = fill(a.root, a.target)
            if w:
                log(f"queued {w} lesson(s)")
        except Exception as e:  # never die: log, wait, retry
            log(f"producer error: {e!r}")
        if a.once:
            break
        time.sleep(5)
    log("stopped")


if __name__ == "__main__":
    main()
