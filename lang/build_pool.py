"""Build lang/pool/{la,grc,he}.json: short verses with word-by-word lemma, gloss and parsing, plus the WEB English.

    python -m lang.build_pool --data ~/lang-data          # after deploy/box/lang/fetch_data.sh

Sources (licences in lang/LICENSES.md): MACULA Greek (SBLGNT), MACULA Hebrew (WLC + OSHB morphology),
Clementine Vulgate (VulSearch text) with Whitaker's WORDS, World English Bible (public domain).
Only chapters whose verse count matches the WEB are used, so the English always belongs to the verse shown.
The pool is committed: the channel needs no download at run time, and the tests read it.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import OrderedDict
from pathlib import Path

from .translit import greek_translit, hebrew_display

HERE = Path(__file__).resolve().parent
POOL = HERE / "pool"
MAX_PER_LANG = 450

# MACULA / USFM book codes -> WEB vpl codes, and English names for the screen
WEB_CODE = {"MRK": "MAR", "JHN": "JOH", "PHP": "PHI", "JAS": "JAM", "1JN": "1JO", "2JN": "2JO", "3JN": "3JO",
            "SNG": "SOL", "EZK": "EZE", "JOL": "JOE", "NAM": "NAH"}
NAMES = {"GEN": "Genesis", "EXO": "Exodus", "DEU": "Deuteronomy", "RUT": "Ruth", "PSA": "Psalms", "PRO": "Proverbs",
         "ECC": "Ecclesiastes", "ISA": "Isaiah", "MAT": "Matthew", "MRK": "Mark", "LUK": "Luke", "JHN": "John",
         "ACT": "Acts", "ROM": "Romans", "1CO": "1 Corinthians", "2CO": "2 Corinthians", "GAL": "Galatians",
         "EPH": "Ephesians", "PHP": "Philippians", "COL": "Colossians", "1TH": "1 Thessalonians", "HEB": "Hebrews",
         "JAS": "James", "1PE": "1 Peter", "1JN": "1 John", "REV": "Revelation"}
# Clementine file -> USFM code (books whose Vulgate versification is close to the English; chapters are checked anyway)
CLEM = {"Gn": "GEN", "Rt": "RUT", "Pr": "PRO", "Mt": "MAT", "Mc": "MRK", "Lc": "LUK", "Jo": "JHN", "Act": "ACT",
        "Rom": "ROM", "1Cor": "1CO", "2Cor": "2CO", "Gal": "GAL", "Eph": "EPH", "Phlp": "PHP", "Col": "COL",
        "1Thes": "1TH", "Hbr": "HEB", "Jac": "JAS", "1Ptr": "1PE", "1Jo": "1JN", "Apc": "REV"}
HE_BOOKS = {"GEN", "DEU", "RUT", "PRO", "ISA", "PSA"}


def load_web(path: Path):
    verses, counts = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\S+) (\d+):(\d+) (.*)$", line)
        if not m:
            continue
        b, c, v, t = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).strip()
        verses[(b, c, v)] = t
        counts[(b, c)] = max(counts.get((b, c), 0), v)
    return verses, counts


def english_for(web, book, c, v):
    return web[0].get((WEB_CODE.get(book, book), c, v))


def chapter_ok(web, book, c, n_verses):
    return web[1].get((WEB_CODE.get(book, book), c)) == n_verses


def _ref(r):
    m = re.match(r"^(\S+) (\d+):(\d+)", r)
    return m.group(1), int(m.group(2)), int(m.group(3))


def _clean(s):
    return (s or "").strip()


def greek_parse(row):
    cls = row["class"]
    if cls == "verb":
        bits = [row["tense"], row["voice"], row["mood"]]
        if row["person"]:
            bits.append(f"{ {'first': '1', 'second': '2', 'third': '3'}.get(row['person'], row['person'])}{'sg' if row['number'] == 'singular' else 'pl' if row['number'] else ''}")
        elif row["mood"] == "participle":
            bits += [row["case"][:3], row["number"][:2] if row["number"] else "", row["gender"][:1]]
        return "verb, " + " ".join(b for b in bits if b)
    if cls in ("noun", "adj", "det", "pron"):
        name = {"adj": "adjective", "det": "article", "pron": "pronoun"}.get(cls, cls)
        bits = [row["case"][:3], {"singular": "sg", "plural": "pl"}.get(row["number"], ""), row["gender"][:1]]
        return name + ", " + " ".join(b for b in bits if b)
    return {"prep": "preposition", "conj": "conjunction", "adv": "adverb", "ptcl": "particle", "intj": "interjection",
            "num": "numeral"}.get(cls, cls)


def build_greek(path: Path, web):
    verses = OrderedDict()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if not row.get("ref"):
                continue
            key = _ref(row["ref"])
            verses.setdefault(key, []).append({
                "text": row["text"], "after": row["after"], "translit": greek_translit(row["text"]),
                "lemma": row["lemma"], "gloss": _clean(row["english"]) or _clean(row["gloss"]),
                "parse": greek_parse(row)})
    return _select("grc", verses, web, lambda ws: 3 <= len(ws) <= 9)


def hebrew_parse(rows):
    out = []
    for r in rows:
        pos = r["pos"]
        if pos == "verb":
            bits = [r["stem"], r["type"], {"first": "1", "second": "2", "third": "3"}.get(r["person"], ""),
                    r["gender"][:1], {"singular": "s", "plural": "p", "dual": "d"}.get(r["number"], "")]
            out.append("verb " + " ".join(b for b in bits[:2] if b) + (" " + "".join(bits[2:]) if any(bits[2:]) else ""))
        elif pos in ("noun", "adjective", "pronoun"):
            bits = [{"masculine": "m", "feminine": "f", "both": "c"}.get(r["gender"], ""),
                    {"singular": "s", "plural": "p", "dual": "d"}.get(r["number"], ""),
                    {"absolute": "abs", "construct": "cstr"}.get(r["state"], "")]
            out.append(f"{pos} " + ".".join(b for b in bits if b))
        else:
            out.append(r["type"] if pos == "particle" and r["type"] else pos)
    return " + ".join(o.strip() for o in out)


def build_hebrew(path: Path, web):
    verses = OrderedDict()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if not row.get("ref"):
                continue
            book = row["ref"].split()[0]
            if book not in HE_BOOKS:
                continue
            key = _ref(row["ref"])
            words = verses.setdefault(key, OrderedDict())
            words.setdefault(row["ref"], []).append(row)
    out = OrderedDict()
    for key, words in verses.items():
        ws = []
        for rows in words.values():
            text = "".join(r["text"] for r in rows)
            tl = "".join(r["transliteration"] for r in rows)
            ws.append({"text": text, "after": rows[-1]["after"], "translit": hebrew_display(tl), "tl_raw": tl,
                       "lemma": " + ".join(r["lemma"] for r in rows),
                       "gloss": "-".join(g for g in (_clean(r["english"]) for r in rows) if g),
                       "parse": hebrew_parse(rows)})
        out[key] = ws
    return _select("he", out, web, lambda ws: 3 <= len(ws) <= 6 and all(w["gloss"] and w["translit"] for w in ws))


def build_latin(clem_dir: Path, words_dir: Path, web):
    from .latin import Analyzer
    an = Analyzer(words_dir)
    verses = OrderedDict()
    for fn, book in CLEM.items():
        p = clem_dir / f"{fn}.lat"
        if not p.exists():
            continue
        for line in p.read_text(encoding="cp1252", errors="replace").splitlines():
            m = re.match(r"^(\d+):(\d+)\s+(.*)$", line.strip())
            if not m:
                continue
            text = re.sub(r"[\[\]/\\<>]", "", m.group(3))
            text = re.sub(r"\s+", " ", text).strip()
            text = re.sub(r"\s+([:;,.?!])", r"\1", text)
            ws = []
            for tok in text.split(" "):
                mm = re.match(r"^([^A-Za-zÆæŒœ]*)([A-Za-zÆæŒœ]+)(.*)$", tok)
                if not mm:
                    continue
                a = an.analyze(mm.group(2))
                ws.append({"text": mm.group(2), "after": mm.group(3) + " ", "translit": "", "lemma": a.lemma or "",
                           "gloss": a.gloss, "parse": (a.pos + (", " + a.parse if a.parse else "")).strip(", ")})
            if ws:
                ws[-1]["after"] = ws[-1]["after"].rstrip()
            verses[(book, int(m.group(1)), int(m.group(2)))] = ws
    return _select("la", verses, web, lambda ws: 3 <= len(ws) <= 9 and all(w["lemma"] and w["gloss"] for w in ws))


def _select(lang, verses, web, keep):
    per_ch = {}
    for (b, c, v) in verses:
        per_ch[(b, c)] = max(per_ch.get((b, c), 0), v)
    out = []
    for (b, c, v), ws in verses.items():
        if not keep(ws) or not chapter_ok(web, b, c, per_ch[(b, c)]):
            continue
        en = english_for(web, b, c, v)
        if not en or len(en) > 120:
            continue
        out.append({"lang": lang, "book": b, "chapter": c, "verse": v,
                    "ref": f"{NAMES.get(b, b.title())} {c}:{v}", "english": en, "words": ws})
    random.Random(f"lang-pool-{lang}").shuffle(out)
    return out[:MAX_PER_LANG]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, required=True, help="folder made by deploy/box/lang/fetch_data.sh")
    a = ap.parse_args(argv)
    d = a.data
    web = load_web(d / "web" / "engwebp_vpl.txt")
    POOL.mkdir(exist_ok=True)
    pools = {"la": build_latin(d / "clem" / "clemtext" / "source", d / "words", web),
             "grc": build_greek(d / "macula-greek" / "SBLGNT" / "tsv" / "macula-greek-SBLGNT.tsv", web),
             "he": build_hebrew(d / "macula-hebrew" / "WLC" / "tsv" / "macula-hebrew.tsv", web)}
    for lang, verses in pools.items():
        (POOL / f"{lang}.json").write_text(json.dumps(verses, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"{lang}: {len(verses)} verses -> {POOL / (lang + '.json')}")
    return 0 if all(pools.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
