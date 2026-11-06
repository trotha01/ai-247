# Handoff

## Objective
AI-247 topic research stage (docs/TOPICS.md), approved by Trevor 2026-11-06 with four changes: web-searching
discovery (Claude API web_search tool), no per-day cap on new topics, episode history in Cloudflare D1 (not the repo),
plan + discovery on Claude Fable 5.1 at low effort (writer/checker stay Haiku 5.5). Branch `cloud/ai247-topics`,
PR #29. Done means: one dispatched episode plays on https://ai-247.pages.dev, measured cost in TOPICS.md, PR merged.

## Done
- Survey: PLAN/DAY2/DAY3/DEPLOY/FAILOVER docs, all PRs, the sibling session's implementation (topics.py, day1 wiring,
  day1.yml, tests; run 42229528561 produced a topic episode on agent-harnesses, Haiku cost 0.00586 USD).
- Owned by this session since Trevor's approval: newsbot/discovery.py (Fable 5.1 + web_search_20260209, primary-link
  gate, no daily cap), newsbot/history_db.py (D1 via REST, bound params, auth error names the permission),
  newsbot/topics.py (D1-first history, R2 mirror as read cache, plan on Fable low, discovery after the writer),
  newsbot/llm.py (Fable prices, web-search billing, cap 0.75), worker (D1 binding, migration, /history.json + test),
  deploy.yml (D1 lookup/create/migrate, non-fatal), day1.yml (Cloudflare secrets, plan_model default Fable, only
  topics.json committed back), docs (TOPICS.md rewritten, DEPLOY.md, README), tests (99 Python + 73 Worker pass).
- episodes/history.json removed from the repo and git-ignored; main merged into the branch (PR #29 was dirty).

## Pending
- Dispatch day1-episode on the branch (mode=topic), read measured cost by kind, fill TOPICS.md "Measured run".
- Confirm D1 works with the current CLOUDFLARE_API_TOKEN; if it lacks Account -> D1 -> Edit, status needs_you.
- Playback proof (e2e-live.js step output), ci + claude-review green, merge PR #29, final status.

## Next step
Push, dispatch the run via the REST API, wait for it, then update docs/status and merge.
