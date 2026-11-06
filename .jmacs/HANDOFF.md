# Handoff

## Objective
AI-247 "seed pool/manifest.json in R2 and schedule the replay-pool refresh": the replay pool exists and stays fresh without a human. (1) Run the `replay-pool` workflow once (source=r2) and confirm `pool/manifest.json` is in R2 and `/healthz` shows the pool healthy. (2) Add a daily schedule to `replay-pool.yml` with a guard that never overwrites a good pool manifest with an empty one. (3) Set `MAX_MANIFEST_AGE_S` to 14400 in `worker/wrangler.toml` and verify after deploy that `/healthz` still says `live-manifest` while the live manifest is fresh. PR, checks, merge to main.

## Done
- Search: read replay-pool.yml, newsbot/replay_pool.py, worker/src/{index,channel,failover}.js, wrangler.toml, scripts/smoke.sh, docs/FAILOVER.md, docs/DEPLOY.md, docs/PLAN.md, docs/R2_LAYOUT.md, .jmacs/HANDOFF.md on main (from cloud/ai247-r2test), PR list #1-#23 (#14 is an open draft handed off; nothing pending touches the pool). Reused as-is: the existing `replay-pool` workflow and `--from-r2` path (PR #20) for the seed, no new uploader; the `DAY1_CRON_ENABLED`-style kill switch pattern from day1.yml; the Worker's `MAX_MANIFEST_AGE_S` var (already implemented and dev-tested in PR #20, only the default changed). Not reused: the earlier handoff's "Worker host blocked from the sandbox" workaround (deploy smoke log): the host answered directly this session, so /healthz was read directly.
- (1) Seed: `/healthz` at 13:04Z showed pool.problem "missing: pool/manifest.json is not in the bucket". Dispatched `replay-pool` on main (source=r2, max_blocks=2): run 42222599138 green, publish step 51 s. `/healthz` at 13:06Z: pool.ok true, 2 blocks, 200 segments, built_at 2026-11-06T13:05:53Z from bulletins/20261106T120928Z and bulletins/20261106T115430Z, epoch_mismatch null, source still live-manifest (manifest age 3315 s).
- (2) On branch cloud/ai247-pool (commit 96ad9a4): replay-pool.yml daily cron `41 4 * * *` (after the 03:23 UTC day1 run), schedule defaults source=r2 max_blocks=2, `REPLAY_POOL_CRON_ENABLED` variable kill switch, `force` input. newsbot/replay_pool.py `refresh_decision`: never replace a good pool with one that has nothing playable; no complete episode -> exit 3, nothing written; same segments as the pool already lists -> no PutObject (`--force` overrides); missing/non-JSON pool -> replaced. Tests added (10 pass in tests/test_replay_pool.py; test_publish 17 pass).
- (3) worker/wrangler.toml MAX_MANIFEST_AGE_S "0" -> "14400". Worker unit tests 71 pass locally. docs/FAILOVER.md and docs/PLAN.md updated.

## Pending
- PR #24 open from cloud/ai247-pool (904cf48); local worker dev tests 12 passed. Wait for ci (tests + worker-site-e2e), then merge.
- After merge: deploy.yml runs test-worker + deploy-worker (worker/** changed) and the smoke test; then read `/healthz` directly: expect source live-manifest, manifest.max_age_s 14400, pool.ok true.
- Status done only after merge + post-deploy /healthz check.

## Next step
Wait for ci on PR #24, merge, then verify the deployed /healthz (max_age_s 14400, source live-manifest, pool.ok).
