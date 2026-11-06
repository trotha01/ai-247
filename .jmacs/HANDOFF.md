# Handoff

## Objective
Day 1 of the ai-247 news-channel PoC (docs/PLAN.md): 10-minute HLS episode (rule-based ranked rundown of 10-12 stories), Claude Haiku 5.5 script writer + separate fact-check (runs only with ANTHROPIC_API_KEY, 0.05 USD/run cap), seam tests, slate loop + replay pool, Actions housekeeping and doc verification.

## Done
- newsbot/rank.py, llm.py (Day 1 writer/checker/repair, Meter with verified prices), episode.py, slate.py, pool.py, media.py, day1.py, playlist.py channel functions.
- tests/test_day1_units.py, tests/test_seam.py (mock client; real media seam checks), workflows day1.yml (dispatch + 3-hourly test cron) and day0.yml bumped to Node 24 action majors.
- Prices verified on platform.claude.com (Haiku 5.5 0.10/0.50, Sonnet 5.5 2/10). docs.github.com, rfc-editor.org, datatracker.ietf.org, github.blog are NOT reachable from the cloud session.

## Pending
- Local full render check, push branch, PR + merge, dispatch day1-episode on Actions (extractive run), then Haiku run if ANTHROPIC_API_KEY secret exists, update docs/PLAN.md with measured Day 1 results.

## Next step
Run day1-episode via workflow_dispatch after merge; collect measurements; write PLAN.md section.
