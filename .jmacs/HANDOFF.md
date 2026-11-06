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
