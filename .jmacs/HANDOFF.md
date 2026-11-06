# Handoff

## Objective
AI-247: topic research stage. Claude picks and deepens topics (AI harnesses, AI for VFX, novel/newly popular AI
areas) with dedupe against past episodes, in front of the existing Haiku writer. Branch `cloud/ai247-topics`.

## Done
- Search: read docs/PLAN.md, DAY2/DAY3/DEPLOY/FAILOVER, the handoff, all 23 PRs and 15 branches. No topic, dedupe
  or history work exists anywhere; everything is the fixed 8-feed digest. Reused: `rank.py` decay, `llm.py`
  writer/checker/Meter, `feeds.py` fetchers, `publish.py` R2 client.
- Design written: `docs/TOPICS.md`.

## Pending
- Trevor's approval of the design and the per-day spend (0.10-0.20 USD/day on Haiku; see TOPICS.md).
- Implementation: `topics/topics.json`, `episodes/history.json`, `newsbot/topics.py`, day1 wiring, tests,
  workflow (history commit-back), one dispatched episode, playback check on ai-247.pages.dev.

## Next step
Scaffolding (topics.json, history.json, newsbot/topics.py with unit tests) while waiting.

## Coordination (two sessions on this todo)
- session_01CP1hmUSnKYpb1ynFAxTpqc (first on the branch) owns: topics.py, day1.py, llm.py, day1.yml, ci.yml, topics.json, history.json, test_topics.py, TOPICS.md, .jmacs. Its implementation commit is unpushed (push rejected, then it decided to rebase and call research.*/discovery.propose and add e2e-live.js as a workflow step) and it is blocked on a permission prompt (Send Message) since 13:21Z.
- session_01CP1hmQmX5v1egwD2gQeNBy (this note) pushed only new files: newsbot/research.py (enrich, web_candidates: arXiv/GitHub search/HN leads, topic_sources), newsbot/discovery.py, tests/test_research.py (12 pass), site/test/e2e-live.js. It will not edit the sibling's files; it re-checks the branch periodically.
