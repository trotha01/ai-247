"""The comment and status of .github/scripts/pr_review_comment.py for each outcome of the review step, and the
gate in pr-review.yml that turns the status into the `claude-review` check.

Policy (docs/CONTRIBUTING.md): the check fails only for a completed review with a blocking finding (or a fork author
not on the allowlist); a review that errored (step failed, timed out, hit a cap, or returned no structured verdict)
is neutral: the check job is skipped and the comment says nothing was reviewed. A clean review passes.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "pr_review_comment.py"
_spec = importlib.util.spec_from_file_location("pr_review_comment", SCRIPT)
prc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prc)

CLEAN = '{"summary": "Adds a thing.", "blocking": [], "non_blocking": [{"file": "x.py", "line": 2, "finding": "nit"}]}'
BLOCKING = '{"summary": "s", "blocking": [{"file": "a.py", "line": 3, "finding": "bug"}], "non_blocking": []}'


def setenv(monkeypatch, **env):
    for k in ("REVIEW_SKIPPED", "REVIEW_OUTCOME", "REVIEW_JSON", "DIFF_TRUNCATED", "GITHUB_OUTPUT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("REVIEW_MODEL", "test-model")
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def build(monkeypatch, **env):
    setenv(monkeypatch, **env)
    return prc.build("owner/repo", "7")


def test_clean_review_passes(monkeypatch):
    md, status = build(monkeypatch, REVIEW_OUTCOME="success", REVIEW_JSON=CLEAN)
    assert status == "ok" and prc.CHECK[status] == "pass"
    assert md.startswith(prc.MARKER) and "no blocking findings" in md
    assert "**Blocking (0)**" in md and "`x.py:2` nit" in md
    assert "truncated" not in md


def test_blocking_finding_fails(monkeypatch):
    md, status = build(monkeypatch, REVIEW_OUTCOME="success", REVIEW_JSON=BLOCKING, DIFF_TRUNCATED="true")
    assert status == "blocking" and prc.CHECK[status] == "fail"
    assert "changes requested" in md and "`a.py:3` bug" in md
    assert "truncated" in md


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", ""])
def test_errored_step_is_neutral(monkeypatch, outcome):
    md, status = build(monkeypatch, REVIEW_OUTCOME=outcome, REVIEW_JSON="")
    assert status == "incomplete" and prc.CHECK[status] == "neutral"
    assert "did not complete (no verdict)" in md and "nothing in this PR has been reviewed" in md
    assert "skipped (neutral)" in md and "actions/runs/123" in md
    assert "no blocking findings" not in md  # never reads as a clean review


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", '"text"'])
def test_no_structured_verdict_is_neutral(monkeypatch, raw):
    md, status = build(monkeypatch, REVIEW_OUTCOME="success", REVIEW_JSON=raw)
    assert status == "noresult" and prc.CHECK[status] == "neutral"
    assert "no structured verdict" in md and "skipped (neutral)" in md


def test_fork_author_not_allowlisted_fails(monkeypatch):
    md, status = build(monkeypatch, REVIEW_SKIPPED="true", REVIEW_OUTCOME="skipped")
    assert status == "skipped" and prc.CHECK[status] == "fail"
    assert "not run" in md and "FORK_REVIEW_AUTHORS" in md


class FakeGitHub:
    def __init__(self, existing_id=None):
        self.existing_id, self.calls = existing_id, []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return [{"id": self.existing_id, "body": prc.MARKER + " old"}] if self.existing_id else []
        return {"id": 99}


@pytest.mark.parametrize("env, status, annotation", [
    ({"REVIEW_OUTCOME": "success", "REVIEW_JSON": CLEAN}, "ok", None),
    ({"REVIEW_OUTCOME": "success", "REVIEW_JSON": BLOCKING}, "blocking", "::error::Claude review: blocking finding"),
    ({"REVIEW_OUTCOME": "failure", "REVIEW_JSON": ""}, "incomplete", "::warning::Claude review did not complete"),
    ({"REVIEW_OUTCOME": "success", "REVIEW_JSON": "nope"}, "noresult", "::warning::Claude review did not complete"),
    ({"REVIEW_SKIPPED": "true", "REVIEW_OUTCOME": "skipped"}, "skipped", "::error::Claude review not run"),
])
def test_main_posts_comment_and_publishes_status(monkeypatch, capsys, tmp_path, env, status, annotation):
    out_file = tmp_path / "out"
    setenv(monkeypatch, GITHUB_OUTPUT=str(out_file), **env)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "7")
    fake = FakeGitHub()
    monkeypatch.setattr(prc, "gh", fake)
    assert prc.main() == 0  # the gate job, not this step, sets the check result
    assert out_file.read_text() == f"status={status}\n"
    posted = [c for c in fake.calls if c[0] == "POST"]
    assert len(posted) == 1 and posted[0][1] == "/repos/owner/repo/issues/7/comments"
    assert posted[0][2] == {"body": prc.build("owner/repo", "7")[0]}
    printed = capsys.readouterr().out
    if annotation:
        assert annotation in printed
    else:
        assert "::error::" not in printed and "::warning::" not in printed


def test_main_updates_an_existing_sticky_comment(monkeypatch):
    setenv(monkeypatch, REVIEW_OUTCOME="success", REVIEW_JSON=CLEAN)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "7")
    fake = FakeGitHub(existing_id=42)
    monkeypatch.setattr(prc, "gh", fake)
    assert prc.main() == 0
    assert [c[:2] for c in fake.calls if c[0] != "GET"] == [("PATCH", "/repos/owner/repo/issues/comments/42")]
    assert fake.calls[-1][2] == {"body": prc.build("owner/repo", "7")[0]}


def test_gate_job_runs_only_for_a_verdict():
    """pr-review.yml: the required `claude-review` job runs for exactly the statuses CHECK marks pass/fail."""
    wf = (ROOT / ".github/workflows/pr-review.yml").read_text()
    job = wf[wf.index("\n  claude-review:\n"):]
    gated = set(re.findall(r'"(\w+)"', re.search(r"fromJSON\('(\[[^\]]*\])'\)", job).group(1)))
    assert gated == {s for s, c in prc.CHECK.items() if c != "neutral"}
    assert "needs: review" in job and "always()" in job
    assert "status: ${{ steps.post.outputs.status }}" in wf
    assert "continue-on-error: true" in wf
