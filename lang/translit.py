"""Transliteration and speech preparation, rule-based and deterministic.

greek_translit   polytonic Greek -> SBL-style Latin letters (display)
hebrew_display   MACULA's academic transliteration -> a lighter one for the screen (rēʾšîṯ -> rēʾšît)
hebrew_ipa       MACULA transliteration -> IPA for Piper (modern Israeli-style reading: v/kh/f for spirants)
latin_speech     Latin -> respelled text an Italian voice reads as ecclesiastical Latin
"""
from __future__ import annotations

import re
import unicodedata

_GR = {"α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "ē", "θ": "th", "ι": "i", "κ": "k",
       "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t",
       "υ": "y", "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "ō"}


def _strip(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def greek_translit(word: str) -> str:
    """λόγος -> logos, Ἐν -> en, ὁ -> ho, εὐαγγέλιον -> euangelion, ῥῆμα -> rhēma."""
    nfd = unicodedata.normalize("NFD", word)
    rough = "̔" in nfd
    base = _strip(word)
    low = base.lower()
    out, i = [], 0
    while i < len(low):
        c, n = low[i], low[i + 1] if i + 1 < len(low) else ""
        if c in "αεηο" and n == "υ":
            out.append(_GR[c] + "u"); i += 2; continue
        if c == "ο" and n == "υ":
            out.append("ou"); i += 2; continue
        if c == "γ" and n in "γκξχ":
            out.append("n"); i += 1; continue
        if c == "υ" and out and out[-1] and out[-1][-1] in "aeēo" and False:
            pass
        out.append(_GR.get(c, c))
        i += 1
    s = "".join(out)
    if rough and s:
        s = "rh" + s[1:] if s[0] == "r" else "h" + s
    if base[:1].isupper():
        s = s[:1].upper() + s[1:]
    return s


def hebrew_display(t: str) -> str:
    """Drop the spirant/length marks the screen does not need: ṯ ḏ ḡ -> t d g, iy -> î, keep ḇ ḵ p̄ (they sound different)."""
    t = unicodedata.normalize("NFC", t)
    t = t.replace("ṯ", "t").replace("ḏ", "d").replace("ḡ", "g").replace("ᵃ", "a").replace("*", "").replace("ẖ", "h")
    t = re.sub(r"iy(?![aāeēiîoōuûəăĕŏ])", "î", t)
    t = t.replace("ēy", "ê").rstrip(":-–")
    return t


_HE = [("p̄", "f"), ("ḇ", "v"), ("ḡ", "g"), ("ḏ", "d"), ("ḵ", "χ"), ("ḥ", "χ"), ("ṯ", "t"), ("ṭ", "t"),
       ("ṣ", "ts"), ("ś", "s"), ("š", "ʃ"), ("q", "k"), ("y", "j"), ("w", "v"), ("ʿ", "ʔ"), ("ʾ", "ʔ"),
       ("ā", "a"), ("ă", "a"), ("â", "a"), ("ē", "e"), ("ê", "e"), ("ĕ", "e"), ("ệ", "e"), ("ə", "e"),
       ("ī", "i"), ("î", "i"), ("ō", "o"), ("ô", "o"), ("ŏ", "o"), ("ū", "u"), ("û", "u"), ("ᵃ", "a")]
_VOW = "aeiou"


def hebrew_ipa(t: str) -> str:
    """bārāʾ -> baˈra, rēʾšiyṯ -> reʔˈʃit, ʾĕlōhiym -> eloˈhim (stress on the last syllable, the common case)."""
    t = unicodedata.normalize("NFC", t).lower()
    t = re.sub(r"[^a-zāăâēêĕệəīîōôŏūûᵃḇḡḏḵḥṯṭṣśšʿʾ̄p\- ]", "", t)
    t = t.replace("iy", "ī").replace("ûw", "u").replace("ôw", "o")
    for a, b in _HE:
        t = t.replace(a, b)
    t = t.replace("̄", "")
    words = []
    for w in t.replace("-", " ").split():
        w = re.sub(r"(.)\1", r"\1", w)          # geminate consonants are not lengthened in modern reading
        w = re.sub(r"^ʔ", "", w)                # glottal stop at the start is not pronounced
        w = re.sub(r"h$", "", w)                # final mater lectionis (tôrāh)
        w = re.sub(r"ʔ$", "", w)
        w = w.replace("j", "j")
        vs = [m.start() for m in re.finditer(f"[{_VOW}]", w)]
        if len(vs) > 1:
            k = vs[-1]
            # stress before the onset consonant of the last syllable
            onset = k - 1 if k > 0 and w[k - 1] not in _VOW else k
            if onset > 0 and w[onset - 1] in "t" and w[onset] == "s":
                onset -= 1
            w = w[:onset] + "ˈ" + w[onset:]
        words.append(w)
    return " ".join(words)


def latin_speech(text: str) -> str:
    """Respell Latin so an Italian voice gives the ecclesiastical (Roman) pronunciation."""
    s = text.replace("æ", "e").replace("Æ", "E").replace("œ", "e").replace("Œ", "E")
    s = re.sub(r"ae", "e", s); s = re.sub(r"Ae", "E", s); s = re.sub(r"oe", "e", s)
    s = re.sub(r"\b(m|n)ih(i)", r"\1ich\2", s, flags=re.I)        # mihi, nihil -> miki, nikil
    s = re.sub(r"([^stx])ti(?=[aeiouAEIOU])", r"\1zi", s)         # gratia -> grazia (not after s, t, x)
    s = s.replace("j", "i").replace("J", "I").replace("y", "i").replace("Y", "I")
    s = s.replace("ph", "f").replace("Ph", "F").replace("th", "t").replace("Th", "T")
    s = re.sub(r"\bh", "", s); s = re.sub(r"\bH", "", s)
    return s
