# Handoff

## Objective
AI-247 "seed pool/manifest.json in R2 and schedule the replay-pool refresh": the replay pool exists and stays fresh without a human. Branch `cloud/ai247-pool`. Two sessions worked this item: the first did steps 1-4 (PR #24), the second added the self-verification and guard-hardening follow-up (PR #28). Both are merged to main.

## Done
- Search first: read replay-pool.yml, newsbot/replay_pool.py + tests, worker/src/{index,channel,failover}.js (healthz, PR #20), worker/wrangler.toml, docs/{PLAN,FAILOVER,DEPLOY,R2_LAYOUT}.md, deploy.yml, scripts/smoke.sh, .jmacs/HANDOFF.md of the r2test and prwatch tasks, PR list #1-#26. Reused: the existing bootstrap script and workflow (PR #20), newsbot/r2.py, the FakeS3 test harness, the deploy.yml secrets-gate pattern, the DAY1_CRON_ENABLED kill-switch pattern, site/config.json streamUrl as the Worker URL. Not reused: the earlier handoff's "Worker host blocked from the sandbox" workaround; the host answered directly, so /healthz was read directly throughout.
- Steps 1-4 (PR #24, squash-merged as 034b61b): replay-pool run 42222599138 seeded `pool/manifest.json` (2 blocks, 200 segments from bulletins/20261106T120928Z and 20261106T115430Z; /healthz went from pool.problem "missing" to pool.ok true); daily cron `41 4 * * *` (after the 03:23 UTC day1 run) with guard (empty/unchanged/no-complete-episode) and the `REPLAY_POOL_CRON_ENABLED` repo-variable kill switch; `MAX_MANIFEST_AGE_S` "0" -> "14400". Deploy run 42225273267 green (test-worker, Deploy Worker, Smoke). /healthz after deploy: source live-manifest, max_age_s 14400, pool.ok true.
- Follow-up (PR #28, squash-merged as e9fdd8c at 13:58Z; checks tests, worker-site-e2e, claude-review all green, review had 0 blocking / 4 non-blocking findings, answered on the PR): `verify_pool` HEAD-checks the existing pool; a newer still-verifying pool is not replaced by an older candidate (`--force` overrides); a broken pool is replaced even by an older episode; `--min-segments` (workflow passes 10; exit 3, R2 untouched); skipped runs write the live pool to `--write`; `scripts/pool_check.py` reads the pool back from R2, re-verifies segments and keys, polls /healthz for pool.ok with this run's built_at; replay-pool.yml R2-secrets gate (warn + exit 0), verify step, publish log + /healthz in the job summary and artifact; docs/FAILOVER.md "Verification" section; 30 tests pass (test_replay_pool + test_publish). No worker/** change, so #28 triggered no redeploy.
- Final /healthz at 13:58:52Z: source live-manifest, reason null, manifest age 6472 s (max_age_s 14400), pool ok, 200 segments, built_at 2026-11-06T13:05:53Z, failover null.

## Pending
- Nothing for this item. First scheduled pool refresh: 2026-11-07 04:41 UTC (expected `not uploading: unchanged` plus a green verify step unless newer episodes exist).
- Non-blocking review follow-ups from #28, not done (would need another ci round): pool_check.py head_object on a missing pool key prints a traceback instead of the FAIL line (job still fails); refresh_decision's exit code is chosen by substring-matching the reason text; no test for the /healthz polling loop or the R2 path of check_r2.

## Watch for (Trevor)
- No `schedule` run has fired in this repo yet (0 as of 14:33Z): the 3-hourly day1-episode cron missed 12:23Z; the episode published at 14:09:22Z came from a manual dispatch (run 42229528561 at 13:56Z). With MAX_MANIFEST_AGE_S 14400 the channel switches to the pool once the live manifest is older than 4 h (from about 18:09Z unless another episode lands); /healthz then shows source replay-pool and reason stale, and returns on the next publish. Intended, but if GitHub never fires the crons the pool will be on air most of the time, and the daily pool refresh (also a cron) will not run either: check Actions for a `schedule` event after 15:23Z and 2026-11-07 04:41Z.
- /healthz at 14:33Z: source live-manifest, manifest age 1456 s (max_age_s 14400), pool.ok true, 200 segments, failover null.

## Next step
None. Item done. (Branch cloud/ai247-pool carries only this .jmacs state on top of main e9fdd8c.)
