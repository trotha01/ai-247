"""The comment and check result of .github/scripts/pr_review_comment.py for each outcome of the review step.

The script is what turns claude-code-action's result into the `claude-review` status check (docs/CONTRIBUTING.md):
a blocking finding or a non-allowlisted fork author is red; a clean review is green; a run that did not reach a
verdict (step failed, no structured output) is green with a warning and a comment that says so, never a silent pass.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "pr_review_comment.py"
_spec = importlib.util.spec_from_file_location("pr_review_comment", SCRIPT)
prc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prc)

CLEAN = '{"summary": "Adds a thing.", "blocking": [], "non_blocking": [{"file": "x.py", "line": 2, "finding": "nit"}]}'
BLOCKING = '{"summary": "s", "blocking": [{"file": "a.py", "line": 3, "finding": "bug"}], "non_blocking": []}'


def build(monkeypatch, **env):
    for k in ("REVIEW_SKIPPED", "REVIEW_OUTCOME", "REVIEW_JSON", "DIFF_TRUNCATED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("REVIEW_MODEL", "test-model")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return prc.build("owner/repo", "7")


def test_clean_review_is_green(monkeypatch):
    md, status = build(monkeypatch, REVIEW_OUTCOME="success", REVIEW_JSON=CLEAN)
    assert status == "ok" and prc.EXIT_CODE[status] == 0
    assert md.startswith(prc.MARKER) and "no blocking findings" in md
    assert "**Blocking (0)**" in md and "`x.py:2` nit" in md
    assert "truncated" not in md


def test_blocking_finding_is_red(monkeypatch):
    md, status = build(monkeypatch, REVIEW_OUTCOME="success", REVIEW_JSON=BLOCKING, DIFF_TRUNCATED="true")
    assert status == "blocking" and prc.EXIT_CODE[status] == 1
    assert "changes requested" in md and "`a.py:3` bug" in md
    assert "truncated" in md  # large PRs are flagged for a human look


@pytest.mark.parametrize("outcome, raw", [("failure", ""), ("cancelled", ""), ("success", ""), ("success", "not json"),
                                          ("success", "[1, 2]")])
def test_incomplete_run_is_a_warning_not_a_failure(monkeypatch, outcome, raw):
    md, status = build(monkeypatch, REVIEW_OUTCOME=outcome, REVIEW_JSON=raw)
    assert status == "incomplete" and prc.EXIT_CODE[status] == 0
    assert "did not complete (no verdict)" in md
    assert "human must review" in md and "actions/runs/123" in md
    assert "no blocking findings" not in md  # never reads as a clean review


def test_fork_author_not_allowlisted_stays_red(monkeypatch):
    md, status = build(monkeypatch, REVIEW_SKIPPED="true", REVIEW_OUTCOME="skipped")
    assert status == "skipped" and prc.EXIT_CODE[status] == 1
    assert "not run" in md and "FORK_REVIEW_AUTHORS" in md


def test_every_status_has_an_exit_code():
    assert set(prc.EXIT_CODE) == {"ok", "incomplete", "blocking", "skipped"}
