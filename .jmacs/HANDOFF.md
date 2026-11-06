# Handoff

## Objective
AI-247: hourly cadence with >= 60 min of new footage per run (Trevor's rule: produced minutes >= cadence minutes), playlist prefers fresh bulletins and falls back to replays only when fresh footage is exhausted. Branch `cloud/ai247-coverage`.

## Done
- Survey: docs/PLAN.md, day1.yml, newsbot/, Worker (playlist.js / failover.js / channel.js), docs/MANIFEST-SWAP.md, FAILOVER.md, R2_LAYOUT.md, the cron worker's HANDOFF (cloud/ai247-cron: PRs #25 and #30 merged; 0 schedule runs ever; waiting for the 15:23Z slot) and the topics worker's HANDOFF + docs/TOPICS.md (cloud/ai247-topics, PR #29 open: rewrites day1.yml, day1.py, llm.py, wrangler.toml, test_day1_output.py; avoid those files).
- Measured from runs 42235237153 / 42214045472 / 42229528561: one 10-min episode (100 x 6 s) renders in 376-594 s pipeline (TTS+plan 190-210 s, render+encode 280-320 s, ~1x real time), whole job 10-15 min; render step limit 25 min; job limit 35 min (GitHub max 6 h); R2 publish of 108 objects 91-144 s sequential.

- Implemented on this branch: `.github/workflows/hourly.yml` (cron `23 * * * *`; plan -> render matrix of 6 x 10-min bulletins -> stitch/publish, HOURLY_LLM_SLICES default 1, HOURLY_CRON_ENABLED switch), `newsbot/hourly.py` (aired-URL memory from R2 per-bulletin manifests, dedupe, never-aired first, dealing with per-source caps, shortfall handling, job summary), `newsbot/publish.py publish_many` (bulletins/<ts>-NN/, 12 parallel uploads, loop_from, pending-manifest inheritance, 6 replays), `newsbot/channel.py` + `worker/src/playlist.js`/`failover.js` (`loop_from`: fresh once then loop; swap at end of fresh region else k+margin; legacy unchanged), `rank.py` NEWSBOT_PER_SOURCE_CAP, `feeds.py` arXiv limit 60, day1.yml cron removed (dispatch only). Tests: 99 Worker (unit + wrangler dev + layout e2e), 60+ Python incl. JS golden vectors. Docs: PLAN.md "Hourly cadence" (measurements, cost table, honest supply limit), MANIFEST-SWAP.md, R2_LAYOUT.md, FAILOVER.md.

- PR #33 merged (squash 9d5ec65, 15:47Z) after three Claude review rounds: one real bug fixed (the NEWSBOT_NO_LLM expression always disabled Haiku), the R2 listing bounded, stitch-job summary deps, shared concurrency group `episode-publish` with day1-episode, no-slate fallback, rendered vs inherited minutes. `tests` and `worker-site-e2e` each hit the 8-minute install stall once on older heads (not this PR's), green on the merged head. deploy.yml run 42246388079 redeployed the Worker (15:50Z) with the loop_from support.
- Branch restarted from main for PR 2.

## Pending
- Run 3 (42256733605, install fix): all 6 installs 35-46 s, 6 renders in progress since 16:58Z; publish expected ~17:10Z. Fill PLAN.md "Run 3", push, merge PR #34 (tests, worker-site-e2e, claude-review were green on 9a27c2e), status done.
- Cron proof: 16:23Z slot produced no run; watch 17:23Z (hourly.yml has been on main since 15:47Z).

## Done since PR #33
- Verification run 1 (main): 2 of 6 bulletins published (3 failed the Day 1 floor of 10 stories with 9, 1 install stall); swap at 16:51:26Z verified on pages.dev. Run 2 (branch, floor 6): 3 of 6 (3 install stalls); swap landed exactly at run 1's fresh end (164181). Fixes on the branch: NEWSBOT_MIN_STORIES (6 for slices), install steps bounded per stage with fast-failing pip and 20-minute budgets in hourly.yml and ci.yml, vitest 30 s per-test timeout for the wrangler dev suites, fresh_minutes with inherited blocks, merge of main (PR #29 topic stage) with the topic test restored.

## Next step
When run 3 publishes: read its stitch log (PUBLISH line, rendered_minutes), write PLAN.md "Run 3", push, wait for the three checks, squash-merge PR #34, set status done (or note the shortfall honestly if run 3 is below 60 min).
