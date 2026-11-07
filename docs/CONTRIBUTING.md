# Contributing

Short version: branch, open a pull request, make the checks green, merge. Nothing reaches `main` any other way.

## Branches and pull requests

- `main` is protected by the ruleset in `.github/rulesets/main.json`: changes land only through a pull request,
  the status checks `tests`, `worker-site-e2e` (both from `.github/workflows/ci.yml`) and `claude-review`
  (`.github/workflows/pr-review.yml`) must pass, and force-pushes and deletion of `main` are refused. No one,
  the owner included, is exempt; in an emergency the owner edits the ruleset in Settings > Rules.
- Collaborators with write access push a branch to this repository and open a PR from it. Automated
  sessions use `cloud/<task>`; people may use any name. Fork PRs are welcome too (see below).
- Squash-merge is the norm. Branches that merged can be deleted.

## What runs on every pull request

1. `ci` (`tests`, `worker-site-e2e`): the unit, seam, Worker and site e2e tests. Runs on the plain
   `pull_request` event, so it has no secrets and runs for forks as well.
2. `pr-review` (`claude-review`): Claude reads the PR diff and posts one comment with **blocking** and
   **non-blocking** findings; the check is red when there is a blocking finding or the review could not run
   (the comment says which: a failed step, or a step that returned no structured verdict).
   It uses `claude-haiku-5-5`, read-only tools, a turn cap and a diff cap, so a run costs cents. Draft PRs are
   skipped; mark the PR ready for review to trigger it.

   Safety: the job runs on `pull_request_target`, so it holds the repository's `ANTHROPIC_API_KEY`. It
   therefore never checks out or executes PR code. It checks out the base branch and fetches the PR as a diff
   through the API; the PR title, body and diff are given to Claude as data. The comment is posted by
   `.github/scripts/pr_review_comment.py`, not by the model.

   Fork PRs: the review runs only for authors listed in `FORK_REVIEW_AUTHORS` in `pr-review.yml`. For any other
   fork author the check posts a note and stays red; a maintainer either adds the author to the list (by PR)
   and re-runs the job, or pushes the branch into this repository and opens the PR from there.

A blocking finding you believe is wrong: reply on the PR, fix or explain, and ask a maintainer. Re-run the
`pr-review` job from the Actions tab after an API outage to get a verdict.

## Secrets

This repository is public. Never commit keys or tokens, never print them in a workflow, and never pass a
secret to a job triggered by `pull_request` or to code from a fork. `secret-check.yml` prints only
"present" or "absent".
