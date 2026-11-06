# Handoff

## Objective
AI-247: topic research stage. Claude picks and deepens topics (AI harnesses, AI for VFX, novel/newly popular AI
areas) with dedupe against past episodes, in front of the existing Haiku writer. Branch `cloud/ai247-topics`.

## Done
- Search: read docs/PLAN.md, DAY2/DAY3/DEPLOY/FAILOVER, the handoff, all 23 PRs and 15 branches. No topic, dedupe
  or history work existed; everything was the fixed 8-feed digest. Reused: `rank.py` decay + dedupe, `llm.py`
  writer/checker/Meter (extended: per-model prices, cost by call kind, shared meter, `make_client`), `feeds.py`
  fetchers (topic-specific feeds/repos), `r2.py` client (history mirror).
- Design: `docs/TOPICS.md`. Status `waiting` with the 5-line needs_you summary was pushed first.
- Implementation (session_01CP1hmUSnKYpb1ynFAxTpqc): `topics/topics.json`, `episodes/history.json`,
  `newsbot/topics.py` (match, score, pick, plan call, history record CLI; calls `research.*` and
  `discovery.propose`), `newsbot/day1.py` stage `topic_research`, `episode.py` rundown title, `summary1.py`,
  `day1.yml` (inputs mode/topic/plan_model, `contents: write`, record-and-commit step, live playback check), ci.yml.
- Sibling session_01CP1hmQmX5v1egwD2gQeNBy: `newsbot/research.py` (enrich primary pages; keyless arXiv / GitHub
  search / HN leads), `newsbot/discovery.py` (proposal + deterministic gate), `tests/test_research.py`,
  `site/test/e2e-live.js` (Playwright check of the deployed page). Both sessions rebase before pushing.

## Pending
- Dispatch day1-episode on the branch (mode=topic) and verify the episode plays on ai-247.pages.dev.
- PR, ci green, merge to main. Report measured cost per episode.
- Trevor: approve design + per-day spend (docs/TOPICS.md).

## Next step
Push the rebased implementation, open the PR, dispatch the workflow, run e2e-live.js against the live site.
