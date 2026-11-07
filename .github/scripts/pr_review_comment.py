#!/usr/bin/env python3
"""Post (or update) the Claude review comment on a pull request and set the job result.

Reads from the environment (set by .github/workflows/pr-review.yml):
  GITHUB_REPOSITORY, PR_NUMBER, GH_TOKEN
  REVIEW_SKIPPED  "true" when the review was not run (fork PR from a non-allowlisted author)
  REVIEW_OUTCOME  outcome of the claude-code-action step: success | failure | cancelled | skipped
  REVIEW_JSON     the action's structured_output (JSON: summary, blocking[], non_blocking[])
  DIFF_TRUNCATED  "true" when the diff shown to Claude was cut at MAX_DIFF_BYTES
  REVIEW_MODEL    model id, for the footer

Exit status is the check result (EXIT_CODE): 0 = no blocking finding, 1 = blocking finding, a fork PR whose author
is not allowlisted, or a review that reached no verdict (the action step failed, or succeeded without a structured
result). The comment says which of those happened, so a red check is never mistaken for a finding.
Stdlib only; never prints secrets.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

MARKER = "<!-- claude-pr-review -->"
API = "https://api.github.com"
# build() status -> job exit code.
EXIT_CODE = {"ok": 0, "incomplete": 1, "blocking": 1, "skipped": 1, "noresult": 1}


def gh(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    return json.loads(data) if data else None


def finding_line(item) -> str:
    if isinstance(item, str):
        return f"- {item}"
    where = item.get("file") or ""
    line = item.get("line")
    if where and line:
        where = f"`{where}:{line}` "
    elif where:
        where = f"`{where}` "
    return f"- {where}{item.get('finding', '')}".rstrip()


def build(repo: str, pr: str) -> tuple[str, str]:
    """Return (markdown, status) with status one of EXIT_CODE's keys: ok, incomplete, blocking, skipped."""
    skipped = os.environ.get("REVIEW_SKIPPED") == "true"
    outcome = os.environ.get("REVIEW_OUTCOME", "")
    raw = os.environ.get("REVIEW_JSON", "").strip()
    model = os.environ.get("REVIEW_MODEL", "claude")
    truncated = os.environ.get("DIFF_TRUNCATED") == "true"
    run_url = f"https://github.com/{repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"

    if skipped:
        md = (
            f"{MARKER}\n## Claude review: not run\n\n"
            "This pull request comes from a fork whose author is not on the review allowlist "
            "(`FORK_REVIEW_AUTHORS` in `.github/workflows/pr-review.yml`), so the repository's Anthropic key was "
            "not used. The tests in `ci` still run. A maintainer reviews this PR by hand.\n"
        )
        return md, "skipped"

    data = None
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
    if outcome != "success":
        md = (
            f"{MARKER}\n## Claude review: did not complete (no verdict)\n\n"
            f"The review step ended with outcome `{outcome or 'unknown'}` and returned no structured result: an API "
            f"error, the credit limit, the action's turn cap, or a transient failure (see the [workflow run]({run_url})). "
            "**No finding was recorded and nothing in this PR has been reviewed by Claude.** This check stays red until "
            "a re-run of the job completes or a maintainer reviews the PR by hand.\n"
        )
        return md, "incomplete"
    if not isinstance(data, dict):
        md = (
            f"{MARKER}\n## Claude review: no structured result\n\n"
            f"The review step succeeded but returned no structured result (see the [workflow run]({run_url})). "
            "This is not treated as an outage: the PR's own text may have steered the model away from answering, so "
            "**this check stays red** until a re-run produces a verdict or a maintainer reviews the PR by hand.\n"
        )
        return md, "noresult"

    blocking = data.get("blocking") or []
    non_blocking = data.get("non_blocking") or []
    summary = (data.get("summary") or "").strip()
    verdict = "changes requested" if blocking else "no blocking findings"
    lines = [MARKER, f"## Claude review: {verdict}", ""]
    if summary:
        lines += [summary, ""]
    lines += [f"**Blocking ({len(blocking)})**"]
    lines += [finding_line(x) for x in blocking] or ["- none"]
    lines += ["", f"**Non-blocking ({len(non_blocking)})**"]
    lines += [finding_line(x) for x in non_blocking] or ["- none"]
    lines += [""]
    foot = f"_Automated review by `{model}` via claude-code-action; read-only, the PR code was not executed._"
    if truncated:
        foot += " _The diff was truncated for review; large PRs deserve a human look._"
    lines += [foot, f"_[Run]({run_url})_"]
    return "\n".join(lines) + "\n", "blocking" if blocking else "ok"


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    pr = os.environ["PR_NUMBER"]
    md, status = build(repo, pr)

    existing = None
    page = 1
    while True:
        comments = gh("GET", f"/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}") or []
        for c in comments:
            if MARKER in (c.get("body") or ""):
                existing = c["id"]
        if len(comments) < 100:
            break
        page += 1
    try:
        if existing:
            gh("PATCH", f"/repos/{repo}/issues/comments/{existing}", {"body": md})
            print(f"updated comment {existing}")
        else:
            created = gh("POST", f"/repos/{repo}/issues/{pr}/comments", {"body": md})
            print(f"created comment {created.get('id') if created else '?'}")
    except urllib.error.HTTPError as e:
        print(f"::warning::could not post the review comment: HTTP {e.code}")

    print(md)
    if status == "incomplete":
        print("::error::Claude review did not complete: no verdict (re-run the job after the outage, or review by hand)")
    elif status == "skipped":
        print("::error::Claude review not run: fork author is not on FORK_REVIEW_AUTHORS")
    elif status == "noresult":
        print("::error::Claude review: the step succeeded but returned no structured result; re-run the job or review by hand")
    elif status == "blocking":
        print("::error::Claude review: blocking finding")
    return EXIT_CODE[status]


if __name__ == "__main__":
    sys.exit(main())
