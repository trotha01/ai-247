# Handoff

## Objective
AI-247: hourly cadence with >= 60 min of new footage per run (Trevor's rule: produced minutes >= cadence minutes), playlist prefers fresh bulletins and falls back to replays only when fresh footage is exhausted. Branch `cloud/ai247-coverage`.

## Done
- Survey: docs/PLAN.md, day1.yml, newsbot/, Worker (playlist.js / failover.js / channel.js), docs/MANIFEST-SWAP.md, FAILOVER.md, R2_LAYOUT.md, the cron worker's HANDOFF (cloud/ai247-cron: PRs #25 and #30 merged; 0 schedule runs ever; waiting for the 15:23Z slot) and the topics worker's HANDOFF + docs/TOPICS.md (cloud/ai247-topics, PR #29 open: rewrites day1.yml, day1.py, llm.py, wrangler.toml, test_day1_output.py; avoid those files).
- Measured from runs 42235237153 / 42214045472 / 42229528561: one 10-min episode (100 x 6 s) renders in 376-594 s pipeline (TTS+plan 190-210 s, render+encode 280-320 s, ~1x real time), whole job 10-15 min; render step limit 25 min; job limit 35 min (GitHub max 6 h); R2 publish of 108 objects 91-144 s sequential.

- Implemented on this branch: `.github/workflows/hourly.yml` (cron `23 * * * *`; plan -> render matrix of 6 x 10-min bulletins -> stitch/publish, HOURLY_LLM_SLICES default 1, HOURLY_CRON_ENABLED switch), `newsbot/hourly.py` (aired-URL memory from R2 per-bulletin manifests, dedupe, never-aired first, dealing with per-source caps, shortfall handling, job summary), `newsbot/publish.py publish_many` (bulletins/<ts>-NN/, 12 parallel uploads, loop_from, pending-manifest inheritance, 6 replays), `newsbot/channel.py` + `worker/src/playlist.js`/`failover.js` (`loop_from`: fresh once then loop; swap at end of fresh region else k+margin; legacy unchanged), `rank.py` NEWSBOT_PER_SOURCE_CAP, `feeds.py` arXiv limit 60, day1.yml cron removed (dispatch only). Tests: 99 Worker (unit + wrangler dev + layout e2e), 60+ Python incl. JS golden vectors. Docs: PLAN.md "Hourly cadence" (measurements, cost table, honest supply limit), MANIFEST-SWAP.md, R2_LAYOUT.md, FAILOVER.md.

## Pending
- PR 1 (this branch) -> ci + worker-site-e2e + claude-review -> squash-merge.
- After merge: `workflow_dispatch` hourly-bulletins on main; verify >= 60 min fresh in publish.json, `/healthz` manifest.uploaded, pages.dev plays; PR 2 with the "Verification run" numbers in PLAN.md.
- Cron proof: the first `23 * * * *` slot after merge (no schedule run has ever been observed on this repo; the cron worker's HANDOFF concluded nothing in the repo blocks it).

## Next step
Open PR 1, watch checks, merge, dispatch, verify, PR 2.
