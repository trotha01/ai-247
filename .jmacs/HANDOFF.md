# Handoff

## Objective
AI-247: protect main, add a PR check + Claude review workflow, and report Mychal's access options.
This session (session_01CP1hmQq1BSGfWUjimppusq) was a DUPLICATE dispatch: session_01CP1hmTeuYuNokHuUpPx52n started the same todo a minute earlier, owns branch `cloud/ai247-prwatch` and PR #26, and is still running. This session stood down to avoid racing it; its own draft lives only on `claude/ai-247-pr-review-protection-zqkbjc`.

## Done
- Survey: ai-247 has ci.yml (jobs `tests`, `worker-site-e2e`) on pull_request, no review workflow, no rulesets, main `protected: false`. REST code search across trotha01 repos: no claude-code-action or Claude review workflow to reuse. Official anthropics/claude-code-action@v1 (GA): posts comments, exposes `structured_output`, creates no check run, so the workflow job itself is the required check.
- Reviewed PR #26's design (pull_request_target with base-only checkout, PR read as an API diff, Haiku 5.5, read-only tools, --json-schema -> sticky comment + `claude-review` check, fork allowlist): sound; `structured_output` output verified against action.yml.
- EliasTheApe verified: all 30 latest commits on trotha01/prompt-desk carry login `EliasTheApe`. ai-247 collaborators: trotha01 only.
- Found that this cloud environment's GitHub proxy refuses the two approved admin writes (HTTP 403): POST .../rulesets and PUT .../collaborators/EliasTheApe. Sent all of the above to the owning session.
- Drafted an alternative pull_request-only workflow (kept here for reference, not proposed): .github/workflows/pr-review.yml, .github/rulesets/main.json with admin bypass, docs/CONTRIBUTING.md.

## Pending
- NEEDS TREVOR (only an owner can run these; both pre-approved 2026-11-06), after PR #26 merges:
  1. `gh api -X POST repos/trotha01/ai-247/rulesets --input .github/rulesets/main.json`
  2. `gh api -X PUT repos/trotha01/ai-247/collaborators/EliasTheApe -f permission=push`
- PR #26 merge, the throwaway proof PR, and the final report belong to session_01CP1hmTeuYuNokHuUpPx52n.

## Next step
None for this session. Trevor: dedupe the todo (keep the other session), then run the two commands above once PR #26 is on main.
