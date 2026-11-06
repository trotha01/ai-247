# Handoff

## Objective
AI-247 "seed pool/manifest.json in R2 and schedule the replay-pool refresh": the replay pool exists and stays fresh without a human. (1) Run the `replay-pool` workflow once (source=r2) and confirm `pool/manifest.json` is in R2 and `/healthz` shows the pool healthy. (2) Add a daily schedule to `replay-pool.yml` with a guard that never overwrites a good pool manifest with an empty one. (3) Set `MAX_MANIFEST_AGE_S` to 14400 in `worker/wrangler.toml` and verify after deploy that `/healthz` still says `live-manifest` while the live manifest is fresh. PR, checks, merge to main.

## Done
- Read replay-pool.yml, newsbot/replay_pool.py, worker/src/{index,channel,failover}.js, wrangler.toml, scripts/smoke.sh, docs/FAILOVER.md, docs/DEPLOY.md, docs/PLAN.md, .jmacs/HANDOFF.md on main (cloud/ai247-r2test), PR list (#1-#23; #14 open draft, handed off).
- Confirmed the gap from the sandbox: `https://ai247-live.trotha01.workers.dev/healthz` (reachable here, unlike the earlier handoff said) at 13:04Z: source=live-manifest, manifest age 3237 s, 205 segments, pool.problem = "missing: pool/manifest.json is not in the bucket", max_age_s 0.
- Dispatched `replay-pool` on main with source=r2, max_blocks=2 (loops the two newest complete episodes: runs 42212912268 and 42214045472 per the r2test handoff).
- Branch `cloud/ai247-pool` created from main (fa66358).

## Pending
- Wait for the replay-pool run; confirm the upload in its log and `/healthz` pool.ok.
- replay-pool.yml: daily cron + guard; newsbot/replay_pool.py: do not replace an existing good pool with an unchanged or empty one; tests.
- worker/wrangler.toml MAX_MANIFEST_AGE_S = "14400"; docs; PR; ci; merge; deploy; verify /healthz.

## Next step
Check the replay-pool run result, then implement the schedule + guard + MAX_MANIFEST_AGE_S on this branch.
