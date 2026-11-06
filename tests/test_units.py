"""Unit tests that need no rendered output: playlist checker (e), fact check (b), LLM plug-in, feed parsing."""
import json
from types import SimpleNamespace

import pytest

from newsbot import feeds, llm, playlist, script as sm

MANIFEST = {"segment_seconds": 6, "segments": [{"file": f"seg_{i:03d}.ts", "duration": 6.0 + (i % 3) * 0.004} for i in range(10)]}


# ---- (e) playlist checker ----
@pytest.mark.parametrize("now", [0, 5.9, 6, 29, 59.9, 60, 61, 125, 600, 12345.6])
def test_e_rolling_playlist_valid(now):
    assert playlist.check_media_playlist(playlist.rolling_playlist(MANIFEST, now)) == []


def test_e_discontinuity_and_sequence_semantics():
    # live segment 12 -> window 8..12, wrap at 10 is tagged, nothing scrolled out yet
    p = playlist.parse(playlist.rolling_playlist(MANIFEST, 12 * 6 + 1))
    assert p["seq"] == 8 and p["dseq"] == 0
    assert [i for i, s in enumerate(p["segs"]) if s["disc"]] == [2]
    assert [s["uri"] for s in p["segs"]] == ["seg_008.ts", "seg_009.ts", "seg_000.ts", "seg_001.ts", "seg_002.ts"]
    # live segment 15 -> window 11..15, the tagged segment 10 scrolled out -> dseq 1
    p = playlist.parse(playlist.rolling_playlist(MANIFEST, 15 * 6))
    assert p["seq"] == 11 and p["dseq"] == 1 and not any(s["disc"] for s in p["segs"])


def test_e_continuity_over_time():
    prev = playlist.rolling_playlist(MANIFEST, 0)
    for t in range(6, 6 * 45, 6):
        cur = playlist.rolling_playlist(MANIFEST, t)
        assert playlist.check_continuity(prev, cur) == [], t
        prev = cur


def test_e_checker_catches_bad_playlists():
    good = playlist.rolling_playlist(MANIFEST, 100)
    assert playlist.check_media_playlist(good.replace("#EXT-X-TARGETDURATION:7", "#EXT-X-TARGETDURATION:5"))
    assert playlist.check_media_playlist(good.replace("#EXT-X-MEDIA-SEQUENCE:12\n", ""))
    assert playlist.check_media_playlist(good.replace("#EXTM3U\n", ""))
    assert playlist.check_media_playlist(good.replace("6.000", "9.000", 1))
    bad = playlist.rolling_playlist(MANIFEST, 100).replace("MEDIA-SEQUENCE:12", "MEDIA-SEQUENCE:3")
    assert playlist.check_continuity(playlist.rolling_playlist(MANIFEST, 100), bad)


def test_e_ffmpeg_playlist_valid(out):
    text = (out / "index.m3u8").read_text()
    assert playlist.check_media_playlist(text) == []
    assert "#EXT-X-ENDLIST" in text


# ---- (b) fact check ----
def test_b_detects_unsupported_numbers_and_entities():
    src = "OpenAI released GPT-5 with 3 new tools on Monday."
    assert sm.missing_terms("OpenAI released GPT-5 with 3 new tools", src) == []
    assert "7" in sm.missing_terms("OpenAI released GPT-5 with 7 new tools", src)
    assert "Google" in sm.missing_terms("OpenAI and Google released GPT-5", src)
    assert "GPT-6" in sm.missing_terms("OpenAI released GPT-6", src)


# ---- pluggable Haiku step ----
class FakeClient:
    def __init__(self, replies):
        self.replies, self.messages = list(replies), self
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        txt = self.replies[(self.calls - 1) % len(self.replies)]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=txt)],
                               usage=SimpleNamespace(input_tokens=500, output_tokens=60))


def _items(n=6):
    return [feeds.Item(f"Src{i}", "Acme ships Widget 1", "Acme ships Widget today with faster startup times.",
                       f"https://x/{i}", "2026-11-05", 1000 + i) for i in range(n)]


def test_llm_skipped_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.write_with_claude(_items(), []) is None


def test_llm_path_with_fake_client_and_factcheck():
    ok = FakeClient([json.dumps({"headline": "Acme ships Widget 1", "quote": "Acme ships Widget today."}),
                     json.dumps({"supported": True})])
    s = llm.write_with_claude(_items(), [], client=ok)
    assert s and len(s["stories"]) == 4 and sm.check_script(s) == {}
    hallucinating = FakeClient([json.dumps({"headline": "Acme ships Widget 9000", "quote": "Acme ships Widget today."}),
                                json.dumps({"supported": True})])
    assert llm.write_with_claude(_items(), [], client=hallucinating) is None  # number not in source -> dropped


def test_llm_budget_abort(monkeypatch):
    monkeypatch.setattr(llm, "MAX_RUN_USD", 0.0001)
    c = FakeClient([json.dumps({"headline": "Acme ships Widget 1", "quote": "Acme ships Widget today."})])
    with pytest.raises(llm.BudgetExceeded):
        llm.write_with_claude(_items(), [], client=c)


# ---- feed parsing ----
def test_parse_pypi_rss_and_github_json():
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>PyPI recent updates for foo</title>
    <item><title>1.2.3</title><link>https://pypi.org/project/foo/1.2.3/</link><description>Foo lib</description>
    <pubDate>Thu, 05 Nov 2026 18:59:09 GMT</pubDate></item></channel></rss>"""
    it = feeds.parse_feed_bytes("PyPI foo", rss)[0]
    assert it.title == "foo 1.2.3 released" and it.published == "2026-11-05"
    gh = json.dumps([{"name": "v1", "tag_name": "v1", "html_url": "https://github.com/a/b/releases/v1",
                      "published_at": "2026-11-04T10:00:00Z", "body": "## Changes\n- Fixed a bug", "draft": False,
                      "prerelease": False}]).encode()
    g = feeds.parse_github_releases("B", "a/b", gh)[0]
    assert g.published == "2026-11-04" and "Fixed a bug" in g.summary
