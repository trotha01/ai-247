"""The comment and check result of .github/scripts/pr_review_comment.py for each outcome of the review step.

The script is what turns claude-code-action's result into the `claude-review` status check (docs/CONTRIBUTING.md):
a blocking finding, a non-allowlisted fork author, or a step that succeeded without a structured verdict is red; a
clean review is green; a step that failed (outage, cap) is green with a warning and a comment that says no verdict
was reached, never a silent pass.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "pr_review_comment.py"
_spec = importlib.util.spec_from_file_location("pr_review_comment", SCRIPT)
prc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prc)

CLEAN = '{"summary": "Adds a thing.", "blocking": [], "non_blocking": [{"file": "x.py", "line": 2, "finding": "nit"}]}'
BLOCKING = '{"summary": "s", "blocking": [{"file": "a.py", "line": 3, "finding": "bug"}], "non_blocking": []}'


def setenv(monkeypatch, **env):
    for k in ("REVIEW_SKIPPED", "REVIEW_OUTCOME", "REVIEW_JSON", "DIFF_TRUNCATED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("REVIEW_MODEL", "test-model")
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def build(monkeypatch, **env):
    setenv(monkeypatch, **env)
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


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", ""])
def test_failed_step_is_a_warning_not_a_failure(monkeypatch, outcome):
    md, status = build(monkeypatch, REVIEW_OUTCOME=outcome, REVIEW_JSON="")
    assert status == "incomplete" and prc.EXIT_CODE[status] == 0
    assert "did not complete (no verdict)" in md
    assert "human must review" in md and "actions/runs/123" in md
    assert "no blocking findings" not in md  # never reads as a clean review


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", '"text"'])
def test_successful_step_without_a_verdict_stays_red(monkeypatch, raw):
    md, status = build(monkeypatch, REVIEW_OUTCOME="success", REVIEW_JSON=raw)
    assert status == "noresult" and prc.EXIT_CODE[status] == 1
    assert "no structured result" in md and "stays red" in md
    assert "no blocking findings" not in md


def test_fork_author_not_allowlisted_stays_red(monkeypatch):
    md, status = build(monkeypatch, REVIEW_SKIPPED="true", REVIEW_OUTCOME="skipped")
    assert status == "skipped" and prc.EXIT_CODE[status] == 1
    assert "not run" in md and "FORK_REVIEW_AUTHORS" in md


def test_every_status_has_an_exit_code():
    assert set(prc.EXIT_CODE) == {"ok", "incomplete", "blocking", "skipped", "noresult"}


class FakeGitHub:
    """Stands in for prc.gh: no existing comment on the first call, records what main() posts or patches."""

    def __init__(self, existing_id=None):
        self.existing_id = existing_id
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return [{"id": self.existing_id, "body": prc.MARKER + " old"}] if self.existing_id else []
        return {"id": 99}


@pytest.mark.parametrize("env, status, code, annotation", [
    ({"REVIEW_OUTCOME": "success", "REVIEW_JSON": CLEAN}, "ok", 0, None),
    ({"REVIEW_OUTCOME": "success", "REVIEW_JSON": BLOCKING}, "blocking", 1, "::error::Claude review: blocking finding"),
    ({"REVIEW_OUTCOME": "failure", "REVIEW_JSON": ""}, "incomplete", 0, "::warning::Claude review did not complete"),
    ({"REVIEW_OUTCOME": "success", "REVIEW_JSON": "nope"}, "noresult", 1, "::error::Claude review: the step succeeded"),
    ({"REVIEW_SKIPPED": "true", "REVIEW_OUTCOME": "skipped"}, "skipped", 1, "::error::Claude review not run"),
])
def test_main_posts_the_comment_and_returns_the_exit_code(monkeypatch, capsys, env, status, code, annotation):
    setenv(monkeypatch, **env)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "7")
    fake = FakeGitHub()
    monkeypatch.setattr(prc, "gh", fake)
    assert prc.main() == code == prc.EXIT_CODE[status]
    posted = [c for c in fake.calls if c[0] == "POST"]
    assert len(posted) == 1 and posted[0][1] == "/repos/owner/repo/issues/7/comments"
    assert posted[0][2]["body"] == prc.build("owner/repo", "7")[0]
    out = capsys.readouterr().out
    assert "created comment 99" in out
    if annotation:
        assert annotation in out
    else:
        assert "::error::" not in out and "::warning::" not in out


def test_main_updates_an_existing_sticky_comment(monkeypatch):
    setenv(monkeypatch, REVIEW_OUTCOME="success", REVIEW_JSON=CLEAN)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "7")
    fake = FakeGitHub(existing_id=42)
    monkeypatch.setattr(prc, "gh", fake)
    assert prc.main() == 0
    assert [c[:2] for c in fake.calls if c[0] != "GET"] == [("PATCH", "/repos/owner/repo/issues/comments/42")]
    assert json.dumps(fake.calls[-1][2])  # a JSON body
