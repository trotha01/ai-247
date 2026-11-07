"""Language channel: lesson generator, pool, transliteration, Latin analyzer (when WORDS data is present), loops and
deploy guards. Runs without Piper/Chromium: only the committed lang/pool/*.json is needed."""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

import pytest

from lang import lesson as L
from lang import translit as T
from lang.channel_worker import check_prefix, take_batch
from lang.producer_loop import fill

ROOT = Path(__file__).resolve().parents[1]


def test_pools_exist_and_are_well_formed():
    for lang in L.ORDER:
        p = L.pool(lang)
        assert len(p) >= 200, lang
        for v in p:
            assert v["lang"] == lang and v["english"] and 3 <= len(v["words"]) <= 9
            for w in v["words"]:
                assert w["text"] and w["gloss"] and w["parse"], (v["ref"], w)
                assert lang == "la" or w["translit"], (v["ref"], w)
                assert w["lemma"], (v["ref"], w)


def test_rotation_and_determinism():
    a = [L.lesson(n) for n in range(9)]
    assert [x["lang"] for x in a] == ["la", "grc", "he"] * 3
    assert json.dumps(L.lesson(4), ensure_ascii=False) == json.dumps(a[4], ensure_ascii=False)


def test_stride_covers_every_verse_before_repeating():
    for lang in L.ORDER:
        n = len(L.pool(lang))
        assert math.gcd(L.STRIDE, n) == 1, (lang, n)
        k = L.ORDER.index(lang)
        ids = {L.lesson(3 * i + k)["id"].split("-", 2)[2] for i in range(n)}
        assert len(ids) == n


def test_lesson_steps_say_slow_then_normal_and_gloss_every_word():
    sc = L.lesson(1)
    kinds = [s["card"]["kind"] for s in sc["steps"]]
    assert kinds[0] == "intro" and kinds[1] == "verse" and kinds[-1] == "verse"
    words = [s for s in sc["steps"] if s["card"]["kind"] == "word"]
    assert len(words) == len(sc["words"])
    assert sc["steps"][1]["say"][0]["rate"] > sc["steps"][-2]["say"][0]["rate"]  # slow first, then normal
    assert sc["steps"][-1]["say"][0]["voice"] == "en" and sc["steps"][-1]["say"][0]["text"] == sc["english"]


def test_hebrew_is_rtl_without_cantillation():
    sc = L.lesson(2)
    assert sc["dir"] == "rtl"
    assert not re.search("[֑-֯]", sc["verse"])
    assert re.search("[ְ-ּ]", sc["verse"])  # vowel points kept


def test_greek_translit():
    assert T.greek_translit("λόγος") == "logos"
    assert T.greek_translit("ὁ") == "ho"
    assert T.greek_translit("Ἐν") == "En"
    assert T.greek_translit("εὐαγγέλιον") == "euangelion"
    assert T.greek_translit("ῥῆμα") == "rhēma"
    assert T.greek_translit("οὐρανοῦ") == "ouranou"


def test_hebrew_ipa_and_display():
    assert T.hebrew_ipa("bārāʾ") == "baˈra"
    assert "ʃ" in T.hebrew_ipa("rēʾšiyṯ") and T.hebrew_ipa("ʾĕlōhiym").endswith("him")
    assert T.hebrew_display("rēʾšiyṯ") == "rēʾšît"


def test_latin_speech_is_ecclesiastical_respelling():
    assert T.latin_speech("caelum") == "celum"
    assert T.latin_speech("gratia") == "grazia"
    assert T.latin_speech("mihi") == "michi"
    assert T.latin_speech("hominum") == "ominum"


WORDS = Path(os.environ.get("LANG_WORDS_DIR", ROOT.parent / "data" / "words"))


@pytest.mark.skipif(not (WORDS / "DICTLINE.GEN").exists(), reason="Whitaker's WORDS data not downloaded")
def test_latin_analyzer():
    from lang.latin import Analyzer
    a = Analyzer(WORDS)
    assert (a.analyze("erat").lemma, a.analyze("erat").parse) == ("sum", "impf act ind 3sg")
    assert a.analyze("Verbum").lemma == "uerbum"
    x = a.analyze("Dixitque")
    assert x.lemma == "dico" and "-que" in x.parse
    assert a.analyze("creavit").parse == "perf act ind 3sg"


def test_producer_fills_and_worker_batches(tmp_path):
    assert fill(tmp_path, 4) == 4 and fill(tmp_path, 4) == 0
    assert (tmp_path / "producer" / "next_n").read_text().strip() == "4"
    inbox = tmp_path / "inbox"
    assert len(take_batch(inbox, 2, 9999)) == 2
    assert take_batch(inbox, 10, 9999) == []                          # not a full block, not waited long enough
    assert len(take_batch(inbox, 10, 60, now=time.time() + 120)) == 4  # partial flush after max-wait


def test_prefix_guard():
    assert check_prefix("lang/") == "lang/"
    for bad in ("", "puddle/", "lang", "lang/../"):
        with pytest.raises(SystemExit):
            check_prefix(bad)


def test_lang_worker_config_and_deploy_gate():
    toml = (ROOT / "lang/cloudflare/lang-live/wrangler.toml").read_text().splitlines()
    assert 'name = "lang-live"' in toml and 'bucket_name = "ai247-media"' in toml and 'PREFIX = "lang/"' in toml
    assert 'main = "../../../worker/src/index.js"' in toml
    wf = (ROOT / ".github/workflows/deploy-lang.yml").read_text()
    assert "vars.LANG_DEPLOY_ENABLED" in wf and 'if [ "$ENABLED" != "true" ]' in wf
    assert "github.ref == 'refs/heads/main'" in wf and "pull_request" not in wf
    steps = wf.split("\n      - ")[1:]
    assert all("if: steps.gate.outputs.ready == 'true'" in s for s in steps if "wrangler-action" in s)
    cfg = json.loads((ROOT / "site/lang/config.json").read_text())
    assert cfg["streamUrl"].startswith("https://lang-live.")


def test_lang_channel_workflow_publishes_only_under_lang():
    wf = (ROOT / ".github/workflows/lang-channel.yml").read_text()
    assert "--prefix lang/" in wf and "--key-prefix lang/" in wf and "R2_BUCKET: ai247-media" in wf


def test_box_install_is_portable():
    """No host-specific paths in the channel code or units; units restart forever and start at boot."""
    files = [*ROOT.glob("lang/*.py"), *ROOT.glob("deploy/box/lang/*"), ROOT / "deploy/box/install.sh"]
    for p in files:
        t = p.read_text(errors="ignore")
        for bad in ("/hyperai", "griffith", "/home/"):
            assert bad not in t, (p, bad)
    for u in ROOT.glob("deploy/box/lang/*.service"):
        t = u.read_text()
        assert "Restart=always" in t and "WantedBy=default.target" in t and "@ROOT@" in t


def test_worker_prunes_local_cache(tmp_path):
    from lang.channel_worker import prune_local
    for i in range(3):
        d = tmp_path / "work" / f"b{i}"
        d.mkdir(parents=True)
        (d / "x").write_bytes(b"0" * 1000)
        os.utime(d, (i, i))
    assert prune_local(tmp_path, 1500) == 2
    assert [p.name for p in (tmp_path / "work").iterdir()] == ["b2"]
