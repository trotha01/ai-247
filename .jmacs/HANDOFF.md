# Handoff

## Objective
AI-247: hourly cadence with >= 60 min of new footage per run (Trevor's rule: produced minutes >= cadence minutes), playlist prefers fresh bulletins and falls back to replays only when fresh footage is exhausted. Branch `cloud/ai247-coverage`.

## Done
- Survey: docs/PLAN.md, day1.yml, newsbot/, Worker (playlist.js / failover.js / channel.js), docs/MANIFEST-SWAP.md, FAILOVER.md, R2_LAYOUT.md, the cron worker's HANDOFF (cloud/ai247-cron: PRs #25 and #30 merged; 0 schedule runs ever; waiting for the 15:23Z slot) and the topics worker's HANDOFF + docs/TOPICS.md (cloud/ai247-topics, PR #29 open: rewrites day1.yml, day1.py, llm.py, wrangler.toml, test_day1_output.py; avoid those files).
- Measured from runs 42235237153 / 42214045472 / 42229528561: one 10-min episode (100 x 6 s) renders in 376-594 s pipeline (TTS+plan 190-210 s, render+encode 280-320 s, ~1x real time), whole job 10-15 min; render step limit 25 min; job limit 35 min (GitHub max 6 h); R2 publish of 108 objects 91-144 s sequential.

## Pending
- Design + implementation (see Next step).

## Next step
Implement: hourly.yml (cron 23 * * * *, plan job -> 6-slice render matrix -> stitch/publish), slice planning in newsbot/hourly.py, multi-bulletin publish with `loop_from` (fresh blocks play once, then slate + replays loop), Worker + Python swap math for block-boundary swaps, tests, docs/PLAN.md cost estimate, dispatch run, PR, merge.
