# HANDOFF

## Objective
AI-247: protect `main`, add a PR check + Claude review workflow, and report Mychal's (EliasTheApe) access options. Branch `cloud/ai247-prwatch`.

## Done
- Searched: ai-247 has `ci.yml` (jobs `tests`, `worker-site-e2e`, on pull_request + push main) and no review workflow, ruleset or branch protection; other trotha01 repos (REST search, 30 repos) have nothing reusable; `anthropics/claude-code-action@v1` is used (official, maintained) rather than a custom API script.
- Added `.github/workflows/pr-review.yml` (pull_request_target, base checkout only, PR read as API diff, Haiku 5.5, read-only tools, structured output -> sticky comment + check `claude-review`, drafts skipped), `.github/scripts/pr_review_comment.py`, `.github/rulesets/main.json` (require PR, require `tests`, `worker-site-e2e`, `claude-review`, no force-push, no bypass), `docs/CONTRIBUTING.md`.

## Pending
- PR from this branch; wait for ci; merge (pr-review runs from main, so it first appears on the proof PR).
- Apply the ruleset after the merge (POST /repos/trotha01/ai-247/rulesets; if the GitHub App lacks admin rights, Trevor imports `.github/rulesets/main.json` in Settings > Rules).
- Throwaway proof PR, then close it; record the result.
- Mychal's access: collaborator endpoints are blocked for this session (proxy 403), so neither checked nor changed. Trevor decides and invites.

## Next step
PR #26 open; merge when ci is green, then apply the ruleset and open the proof PR.
