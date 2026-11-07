"""Latin word analysis from William Whitaker's WORDS tables (DICTLINE.GEN, INFLECTS.LAT, UNIQUES.LAT).

Deterministic and dependency-free: a word is split into stem + ending in every possible way; an analysis is a
dictionary entry whose stem (the inflection's stem key) equals the stem and whose part of speech, declension or
conjugation and gender agree with an inflection carrying that ending. The most frequent entry wins (Whitaker's
frequency codes A..F), and every matching inflection of that entry is reported ("nom/acc s n").
This is a simplified WORDS (no tricks, no prefixes/suffixes); a word it cannot parse comes back with lemma None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FREQ = {c: i for i, c in enumerate("ABCDEFIMNX")}  # A = very frequent ... X = unknown
NDESC = {"N": 5, "PRON": 5, "ADJ": 6, "NUM": 6, "V": 7, "VPAR": 8, "SUPINE": 5, "ADV": 1, "PREP": 1, "CONJ": 0, "INTERJ": 0}
ENTRY_POS = {"VPAR": "V", "SUPINE": "V"}
POS_NAME = {"N": "noun", "V": "verb", "ADJ": "adj", "PRON": "pron", "NUM": "num", "ADV": "adv", "PREP": "prep",
            "CONJ": "conj", "INTERJ": "interj", "VPAR": "participle", "SUPINE": "supine"}
ABBR = {"NOM": "nom", "GEN": "gen", "DAT": "dat", "ACC": "acc", "ABL": "abl", "VOC": "voc", "LOC": "loc",
        "S": "sg", "P": "pl", "M": "m", "F": "f", "N": "n", "C": "", "X": "",
        "PRES": "pres", "IMPF": "impf", "FUT": "fut", "PERF": "perf", "PLUP": "plpf", "FUTP": "futpf",
        "ACTIVE": "act", "PASSIVE": "pass", "IND": "ind", "SUB": "subj", "IMP": "impv", "INF": "inf", "PPL": "ptcp",
        "POS": "", "COMP": "comp", "SUPER": "superl", "CARD": "card", "ORD": "ord", "DIST": "distr", "ADVERB": "adv"}


def norm(s: str) -> str:
    return s.lower().replace("j", "i").replace("v", "u").replace("æ", "ae").replace("œ", "oe")


@dataclass
class Entry:
    stems: list[str]
    pos: str
    codes: list[str]
    freq: int
    gloss: str

    @property
    def which(self):
        return self.codes[0] if self.codes else "0"

    @property
    def var(self):
        return self.codes[1] if len(self.codes) > 1 else "0"


@dataclass
class Infl:
    pos: str
    desc: list[str]
    key: int
    ending: str
    freq: int


@dataclass
class Analysis:
    word: str
    lemma: str | None
    pos: str = ""
    parse: str = ""
    gloss: str = ""
    alts: list[str] = field(default_factory=list)


_LINE = re.compile(r"^(.{19})(.{19})(.{19})(.{19})(\S+)\s+(.*?)\s+(\S) (\S) (\S) (\S) (\S) (.*)$")


def load_dictline(path: Path) -> list[Entry]:
    out = []
    for line in path.read_text(encoding="latin-1").splitlines():
        m = _LINE.match(line.ljust(110))
        if not m:
            continue
        stems = [norm(m.group(i).strip()) for i in range(1, 5)]
        pos = m.group(5)
        codes = m.group(6).split()
        out.append(Entry(stems, pos, codes, FREQ.get(m.group(10), 9), m.group(12).strip()))
    return out


def load_inflects(path: Path) -> list[Infl]:
    out = []
    for line in path.read_text(encoding="latin-1").splitlines():
        line = line.split("--")[0].strip()
        if not line:
            continue
        t = line.split()
        pos = t[0]
        if pos not in NDESC:
            continue
        n = NDESC[pos]
        desc = t[1:1 + n]
        try:
            key, ln = int(t[1 + n]), int(t[2 + n])
        except (IndexError, ValueError):
            continue
        ending = norm(t[3 + n]) if ln > 0 else ""
        out.append(Infl(pos, desc, key, ending, FREQ.get(t[-1], 9)))
    return out


def load_uniques(path: Path) -> dict[str, Analysis]:
    lines = [l.rstrip() for l in path.read_text(encoding="latin-1").splitlines()]
    out = {}
    for i in range(0, len(lines) - 2, 3):
        w, info, gloss = lines[i].strip(), lines[i + 1].split(), lines[i + 2]
        if not w or not info:
            continue
        pos = info[0]
        desc = info[3:1 + NDESC.get(pos, 0)]
        parse = " ".join(ABBR.get(x, x.lower()) for x in desc if not x.isdigit() and ABBR.get(x, x) != "")
        out[norm(w)] = Analysis(w, w.lower(), POS_NAME.get(pos, pos.lower()), parse, short_gloss(gloss))
    return out


def short_gloss(g: str) -> str:
    g = re.sub(r"\[.*?\]|\(.*?\)", "", g).strip(" |;")
    g = g.split(";")[0].split(",")[0].strip(" |")
    return g.split("/")[0].strip()[:40]


class Analyzer:
    def __init__(self, words_dir: Path):
        words_dir = Path(words_dir)
        self.entries = load_dictline(words_dir / "DICTLINE.GEN")
        self.infl = load_inflects(words_dir / "INFLECTS.LAT")
        self.uniques = load_uniques(words_dir / "UNIQUES.LAT")
        # sum/esse itself is hard-coded in WORDS (Ada), not in DICTLINE: stems s- / (empty) / fu- / fut-
        self.entries.insert(0, Entry(["s", "", "fu", "fut"], "V", ["5", "1", "TO_BEING"], -1, "be; exist; (also used to form verb perfect passive tenses)"))
        self.by_stem: dict[str, list[tuple[int, Entry]]] = {}
        for e in self.entries:
            for k, s in enumerate(e.stems, 1):
                if (s or e.freq < 0) and s != "zzz":
                    self.by_stem.setdefault(s, []).append((k, e))
        self.by_end: dict[str, list[Infl]] = {}
        for f in self.infl:
            self.by_end.setdefault(f.ending, []).append(f)
        self.max_end = max(len(e) for e in self.by_end)

    @staticmethod
    def _agrees(e: Entry, f: Infl) -> bool:
        if ENTRY_POS.get(f.pos, f.pos) != e.pos:
            return False
        if f.pos in ("ADV", "PREP", "CONJ", "INTERJ"):
            return f.pos != "PREP" or f.desc[0] == e.codes[0]
        which, var = f.desc[0], f.desc[1]
        if which != e.which and not (which == "0"):
            return False
        if var != "0" and var != e.var:
            return False
        if f.pos == "N" and len(e.codes) > 2:
            g = f.desc[4]
            if not (g == "X" or g == e.codes[2] or (g == "C" and e.codes[2] in ("M", "F"))):
                return False
        return True

    def _candidates(self, w: str):
        for n in range(0, min(self.max_end, len(w)) + 1):
            stem, end = (w[:-n], w[-n:]) if n else (w, "")
            for f in self.by_end.get(end, []):
                for k, e in self.by_stem.get(stem, []):
                    if k == f.key and self._agrees(e, f):
                        yield e, f
        for k, e in self.by_stem.get(w, []):  # indeclinables listed with a full stem (PREP, CONJ, ADV ...)
            if e.pos in ("PREP", "CONJ", "INTERJ", "ADV") and k == 1:
                yield e, Infl(e.pos, e.codes[:1] or ["X"], 1, "", 0)

    def analyze(self, word: str) -> Analysis:
        w = norm(re.sub(r"[^A-Za-zæœÆŒ]", "", word))
        if not w:
            return Analysis(word, None)
        if w in self.uniques:
            a = self.uniques[w]
            return Analysis(word, a.lemma, a.pos, a.parse, a.gloss)
        a = self._best(word, w)
        if a.lemma is None:
            for enc, g in (("que", "and"), ("ne", "?"), ("ue", "or")):
                if w.endswith(enc) and len(w) > len(enc) + 1:
                    b = self._best(word, w[: -len(enc)])
                    if b.lemma:
                        b.parse = (b.parse + f" +-{enc}").strip()
                        b.gloss = f"{b.gloss} + {g}"
                        return b
        return a

    def _best(self, word: str, w: str) -> Analysis:
        cands = list(self._candidates(w))
        if not cands:
            return Analysis(word, None)
        # most frequent entry; ties: more frequent inflection, then the longer stem (shorter ending)
        # abbreviations and names (Sextus for "sex", Aulus for "A") lose to ordinary words
        rare = lambda e: 1 if re.search(r"abb\.|praenomen", e.gloss) else 0
        cands.sort(key=lambda ef: (rare(ef[0]), ef[0].freq, ef[1].freq, len(ef[1].ending)))
        e = cands[0][0]
        tags = []
        for ce, f in cands:
            if ce is e:
                t = parse_tag(f)
                if t not in tags:
                    tags.append(t)
        pos = cands[0][1].pos
        tags = [t for t in tags if t] if pos != "ADV" else []
        lemma = w if e.pos == "NUM" else lemma_of(e)
        return Analysis(word, lemma, POS_NAME.get(pos, pos.lower()), " / ".join(tags[:3]), short_gloss(e.gloss),
                        tags[3:])


def parse_tag(f: Infl) -> str:
    d = f.desc[2:] if f.pos not in ("ADV", "PREP", "CONJ", "INTERJ") else f.desc
    if f.pos == "PREP":
        return "+" + ABBR.get(d[0], d[0].lower())
    if f.pos == "V":  # tense voice mood person number
        tense, voice, mood, person, num = d[:5]
        bits = [ABBR.get(tense, ""), ABBR.get(voice, ""), ABBR.get(mood, "")]
        if mood not in ("INF",) and person != "0":
            bits.append(f"{person}{ABBR.get(num, '')}")
        return " ".join(b for b in bits if b)
    return " ".join(x for x in (ABBR.get(t, t.lower()) for t in d) if x)


def lemma_of(e: Entry) -> str:
    s1, s2 = e.stems[0], e.stems[1]
    p, w, v = e.pos, e.which, e.var
    if p == "N":
        g = e.codes[2] if len(e.codes) > 2 else "M"
        second = s1 if v == "3" else s1 + ("um" if g == "N" else "us")
        return {"1": s1 + "a", "2": second, "4": s1 + ("u" if g == "N" else "us"), "5": s1 + "es"}.get(w, s1)
    if p == "V":
        if w == "5":
            return "sum"
        if w == "2":
            return s1 + "eo"
        if w == "3" and v == "4":
            return s1 + "o"
        return s1 + "o"
    if p == "ADJ":
        if w == "1":
            return s1 + "us"
        if w == "3":
            return s1 + "is" if v == "2" else s1
        return s1
    if p == "PRON":
        return {"qu": "qui", "h": "hic", "ill": "ille", "is": "is", "ips": "ipse", "ist": "iste"}.get(s1, s1)
    return s1
