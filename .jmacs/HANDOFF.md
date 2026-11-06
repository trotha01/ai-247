# Handoff

## Objective
AI-247 "seed pool/manifest.json in R2 and schedule the replay-pool refresh": the replay pool exists and stays fresh without a human. Branch `cloud/ai247-pool`. Two sessions were spawned for this item; the first (session "AI-247 pool manifest seeding") did steps 1-4 in PR #24, this session adds the follow-up PR (self-verification and guard hardening) so the unattended refresh checks itself.

## Done
- Search first: read `.github/workflows/replay-pool.yml`, `newsbot/replay_pool.py` + tests, `worker/src/channel.js` (healthz, PR #20), `worker/wrangler.toml`, `docs/PLAN.md`, `docs/FAILOVER.md`, `docs/DEPLOY.md`, `deploy.yml`, `scripts/smoke.sh`, `.jmacs/HANDOFF.md` of the r2test and prwatch tasks, PR list #1-#26 (REST). Reused: the existing bootstrap script/workflow, `newsbot/r2.py`, the FakeS3 test harness, the deploy.yml secrets-gate pattern, `site/config.json` `streamUrl` as the Worker URL. Found the other session's PR #24 on the same branch before pushing and did not push over it.
- Steps 1-4 (PR #24, squash-merged 13:24Z as 034b61b, by the other session): replay-pool run 42222599138 seeded `pool/manifest.json` (2 blocks, 200 segments from bulletins/20261106T120928Z and 20261106T115430Z); daily cron `41 4 * * *` with guard (empty/unchanged/no-complete-episode), `REPLAY_POOL_CRON_ENABLED` kill switch; `MAX_MANIFEST_AGE_S = "14400"`. Deploy run 42225273267 green, smoke test `ok: /healthz (source=live-manifest)` at 13:26Z. Verified again directly at 13:44Z: `source live-manifest`, `manifest.max_age_s 14400`, `manifest.age_s 5599` (uploaded 12:10:59Z), `pool.ok true`, 200 segments, `failover null`.
- Follow-up on this branch (restarted from main after #24 merged, commit on top of #26): `newsbot/replay_pool.py` `verify_pool` (existing pool HEAD-checked), a newer still-good pool is not replaced by an older episode (`--force` overrides), a broken pool is replaced even by an older episode, `--min-segments` (exit 3), skipped runs write the live pool to `--write`; `scripts/pool_check.py` reads the pool back from R2, verifies segments and keys, polls `/healthz` for `pool.ok` + this run's `built_at`; `replay-pool.yml` R2-secrets gate (warn + exit 0), `--min-segments 10`, verify step, publish log + `/healthz` in the summary/artifact; `docs/FAILOVER.md`; tests (30 pass in test_replay_pool + test_publish). `pool_check.py` exercised against the live Worker from the sandbox.

## Pending
- Follow-up PR from this branch: ci (`tests`, `worker-site-e2e`) and `claude-review` green, then squash-merge. The merge changes only `newsbot/`, `scripts/pool_check.py`, the workflow, docs and tests (no `worker/**`), so no redeploy follows.
- Optional proof: dispatch `replay-pool` (source=r2) once after the merge; expected `not uploading: unchanged` and the verify step green.

## Next step
Open the PR, wait for checks, merge, set status done.

## Watch for (Trevor)
- No scheduled workflow has ever fired in this repo (0 `schedule` runs as of 13:44Z); the 3-hourly `day1-episode` cron missed 12:23Z (PR #25 touched it). With `MAX_MANIFEST_AGE_S` 14400 the channel switches to the pool when the live manifest is older than 4 h (last publish 12:10:59Z, so from about 16:11Z unless an episode lands); `/healthz` then shows `source: replay-pool`, `reason: stale: ...`, and returns on the next publish. Intended, but the first visible effect may be the pool going on air.
- First scheduled pool refresh: 2026-11-07 04:41 UTC.
