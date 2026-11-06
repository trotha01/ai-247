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
- Merge PR #34 (all three checks green on 50f9574; the PLAN.md run 3 push re-runs them once more), then status done.
- Cron proof: 16:23Z slot produced no run; the 17:23Z slot is the next chance (hourly.yml on main since 15:47Z; the Trigger step prints `event=schedule`). If it never fires, that is a GitHub-side question (same symptom as the Day 1 cron), not something in the repo.

## Done since PR #33
- Verification run 1 (main): 2 of 6 bulletins (Day 1 floor of 10 stories rejected 3 full bulletins with 9; 1 install stall); swap at 16:51:26Z verified on pages.dev.
- Run 2 (branch, floor 6): 3 of 6 (3 install stalls); swap landed exactly at run 1's fresh end (164181).
- Run 3 (branch, install fix): **6 of 6, 60.0 min rendered and published in 15 min**, 613 objects / 195 MB in 80 s, run 2's 3 pending bulletins inherited in front (90 min fresh region), coverage check passed; pages.dev playing run 2's first bulletin at 17:12Z with 0 errors. Haiku slice 0.00583 USD.
- Fixes in PR #34: NEWSBOT_MIN_STORIES (6 for slices), install steps bounded per stage with fast-failing pip and 20-minute budgets (hourly.yml and ci.yml), vitest 30 s per-test timeout for the wrangler dev suites, fresh_minutes with inherited blocks, merge of main (PR #29) with the topic test restored, PLAN.md "Verification runs".

## Next step
Squash-merge PR #34 when the re-run is green, write status done, check the 17:23Z cron slot.
