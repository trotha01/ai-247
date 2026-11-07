"""Lesson generator: lesson number n -> one short-verse lesson script (JSON), deterministic from lang/pool/*.json.

Rotation: n % 3 picks Latin, Greek, Hebrew in turn; the verse is pool[(n // 3) * STRIDE % len(pool)], so every verse
comes round once before any repeats (STRIDE is prime and shares no factor with the pool sizes; checked in tests).

A script is a list of steps; each step is one screen (`card`) plus what is said over it (`say`, in order):
  intro       English: language and reference
  verse_slow  the verse, read slowly in the language
  word i      each word: the word slowly in the language, then its gloss in English
  verse       the verse at normal speed, now with the English shown
  english     the English translation read aloud (World English Bible)
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

POOL = Path(__file__).resolve().parent / "pool"
ORDER = ("la", "grc", "he")
STRIDE = 97
LANG_NAME = {"la": "Latin", "grc": "Greek", "he": "Hebrew"}
SCRIPT_NAME = {"la": "Latin (Clementine Vulgate)", "grc": "Koine Greek (SBLGNT)", "he": "Biblical Hebrew (Westminster Leningrad Codex)"}
SLOW, NORMAL, WORD = 1.6, 1.0, 1.5   # Piper length_scale: >1 is slower


@lru_cache(maxsize=None)
def pool(lang: str) -> list[dict]:
    return json.loads((POOL / f"{lang}.json").read_text(encoding="utf-8"))


def strip_cantillation(s: str) -> str:
    """Keep the vowel points, drop the accents (te'amim U+0591-U+05AF, meteg U+05BD, paseq/sof pasuq marks)."""
    return "".join(c for c in unicodedata.normalize("NFC", s) if not ("֑" <= c <= "֯" or c in "ֽ׀"))


def verse_text(v: dict) -> str:
    s = "".join(w["text"] + w["after"] for w in v["words"]).strip()
    if v["lang"] == "he":
        s = strip_cantillation(s).replace("׃", "").strip()
    return s


def ref_spoken(v: dict) -> str:
    book = re.sub(r" \d+:\d+$", "", v["ref"])
    return f"{book}, chapter {v['chapter']}, verse {v['verse']}"


def lesson(n: int) -> dict:
    lang = ORDER[n % 3]
    p = pool(lang)
    v = p[(n // 3) * STRIDE % len(p)]
    words = []
    for w in v["words"]:
        text = strip_cantillation(w["text"]) if lang == "he" else w["text"]
        after = w["after"].strip().replace("\u05c3", "") if lang != "he" or w["after"].strip() != "־" else ""
        words.append({"text": text, "after": after, "translit": w["translit"], "lemma": w["lemma"], "gloss": w["gloss"],
                      "parse": w["parse"], "speak": w.get("tl_raw") or text})
    vt = verse_text(v)
    speak_verse = " ".join(w["speak"] for w in words) if lang == "he" else vt
    steps = [{"card": {"kind": "intro"},
              "say": [{"voice": "en", "text": f"{LANG_NAME[lang]}. {ref_spoken(v)}.", "rate": NORMAL}]},
             {"card": {"kind": "verse", "english": False},
              "say": [{"voice": lang, "text": speak_verse, "rate": SLOW}]}]
    for i, w in enumerate(words):
        steps.append({"card": {"kind": "word", "i": i},
                      "say": [{"voice": lang, "text": w["speak"], "rate": WORD},
                              {"voice": "en", "text": w["gloss"].replace("-", " ").replace("[", "").replace("]", ""), "rate": NORMAL}]})
    steps.append({"card": {"kind": "verse", "english": True},
                  "say": [{"voice": lang, "text": speak_verse, "rate": NORMAL}]})
    steps.append({"card": {"kind": "verse", "english": True},
                  "say": [{"voice": "en", "text": v["english"], "rate": NORMAL}]})
    return {"id": f"{n:06d}-{lang}-{v['book']}{v['chapter']}.{v['verse']}", "n": n, "lang": lang,
            "language": SCRIPT_NAME[lang], "ref": v["ref"], "verse": vt, "english": v["english"],
            "dir": "rtl" if lang == "he" else "ltr", "words": words, "steps": steps}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="print lesson scripts as JSON")
    ap.add_argument("n", type=int, nargs="+")
    a = ap.parse_args(argv)
    for n in a.n:
        print(json.dumps(lesson(n), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
