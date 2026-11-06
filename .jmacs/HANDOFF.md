# HANDOFF

## Objective
AI-247: protect `main`, add a PR check + Claude review workflow, and report Mychal's (EliasTheApe) access options. Branch `cloud/ai247-prwatch`.

## Done
- Searched: ai-247 had `ci.yml` (jobs `tests`, `worker-site-e2e`) and no review workflow, ruleset or branch protection; no other trotha01 repo has a reusable Claude review workflow; the official `anthropics/claude-code-action@v1` is used instead of a custom script.
- PR #26 merged to main (e0d5442): `.github/workflows/pr-review.yml` (pull_request_target; base checkout only; PR read as an API diff, so fork code never runs with secrets; claude-haiku-5-5, read-only tools, --max-turns 12, --max-budget-usd 0.50, diff cap 150 KB; drafts skipped; structured output -> sticky comment + status check `claude-review`), `.github/scripts/pr_review_comment.py`, `.github/rulesets/main.json`, `docs/CONTRIBUTING.md`. Its `worker-site-e2e` failed once with the known install stall (no output 8 min) and passed on one re-run.
- Proof PR #27 opened (trivial docs file) to observe `tests`, `worker-site-e2e`, `claude-review` and the review comment; closed after observation.

## Pending
- Ruleset NOT applied: this session's GitHub proxy refuses the write (POST repos/trotha01/ai-247/rulesets -> 403 "Write access to this GitHub API path is not permitted through this proxy"). Trevor applies it with one command from his machine:
  `gh api -X POST repos/trotha01/ai-247/rulesets --input .github/rulesets/main.json`
  (or Settings > Rules > Rulesets > New > Import, file `.github/rulesets/main.json`). Content: main only; PR required (0 approvals); required checks `tests`, `worker-site-e2e`, `claude-review` (not strict, so cloud/* worker PRs need no update-branch); no force-push; no deletion; no bypass actors. cloud/* workers keep merging as today: they already open a PR and wait for ci green; now they also wait for `claude-review`. A blocking finding means the worker fixes it or Trevor edits the ruleset; no owner bypass is needed for the flow.
- Mychal's access: collaborator endpoints are blocked for this session (403), so his current access was neither checked nor changed. Recommendation: write access once the ruleset is live (branch + PR, review check and tests gate everything; no admin rights). If the repo stays owner-only, fork-and-PR works too: ci runs on forks without secrets and `claude-review` runs for him because `FORK_REVIEW_AUTHORS` lists EliasTheApe. Trevor invites: `gh api -X PUT repos/trotha01/ai-247/collaborators/EliasTheApe -f permission=push`.

## Next step
Observe PR #27 checks and comment, close it, record the result here, set status blocked (ruleset + invite are Trevor's commands).
