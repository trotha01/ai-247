# Handoff

## Objective
AI-247 replay-pool failover (no alerts, no cron, no external services): a bootstrap that publishes `pool/manifest.json` (loop of the Day 0 bulletin or the latest good episode already in R2), Worker fallback to that pool when `manifest.json` is missing / empty / stale beyond `MAX_MANIFEST_AGE_S` / references missing segments, `/healthz` JSON saying which source is live and the manifest age, tests (hls-parser + wrangler dev/Miniflare) that the playlist stays valid across the switch and the return.

## Done
- Search: docs/PLAN.md, DAY2.md, MANIFEST-SWAP.md, DAY3.md, worker/ (index.js, playlist.js, tests), site/, workflows, newsbot/playlist.py, r2.py, pool.py, manifest.py; PR #11 (e2e/key layout, open) and PR #12 (merged). Reused: playlist.js `eras`/`tagsBeforeEras`/`layout`/`tagsBefore` (manifest-swap primitives), hls-parser, vitest, wrangler dev --local (Miniflare R2), pool.py block shape, r2.py credential convention, actions/checkout+setup-python+upload-artifact. Built: the composed-view state machine (nothing in the ecosystem does "fallback at the first unlisted segment, in-phase return, monotonic discontinuity sequence").
- Worker: `worker/src/failover.js` (pure), `worker/src/channel.js` (R2 loads, checks, caching, /healthz), `index.js` delegates; `wrangler.toml` vars POOL_KEY, MAX_MANIFEST_AGE_S (0 = off), CHECK_SEGMENTS, FAILOVER_MIN_S. Tests: `worker/test/unit/failover.test.js` (16, simulated hours, hls-parser on every reload) and `worker/test/dev/failover-dev.test.js` (7, real Worker under wrangler dev --local, R2 objects deleted/re-put). All 71 unit + 7 dev tests pass locally.
- Bootstrap: `newsbot/replay_pool.py` (`--from-r2` newest complete episode, `--from-dir` local render, manifest written last), `tests/test_replay_pool.py` (8, fake S3), dispatch-only `.github/workflows/replay-pool.yml`, `tests/test_replay_pool.py` added to ci.yml.
- Docs: `docs/FAILOVER.md`; two lines in `docs/DAY2.md`.

## Pending
- Nothing on my side: PR #20 merged to main at 2d5e304 after green CI (`tests`, `worker-site-e2e`). main already merged in (PR #11, deploy workflow, Day 1 publisher): `scripts/smoke.sh` and `docs/DEPLOY.md` updated for the JSON `/healthz`; `replay_pool.py` reuses `r2.client()/bucket()`.
- Merging changes `worker/**`, so the `deploy` workflow (added on main by PR #15/#17) deploys the Worker if the Cloudflare secrets exist. I did not and will not run a deploy myself.
- Trevor, after deploy: run the `replay-pool` workflow once (source=r2 or artifact) so `pool/manifest.json` exists; set `MAX_MANIFEST_AGE_S` only if a dead pipeline should switch to the pool.
- Note for the swap owner: `tagsBeforeEras` returns 0 for `first < oldest era start`; if the uploader publishes twice within ~N+10 segments the dropped `prev.prev` makes DISCONTINUITY-SEQUENCE dip to 0 for a few reloads. Not changed here.

## Next step
Trevor: the `deploy` workflow on main will deploy the Worker (if the Cloudflare secrets exist); then dispatch the `replay-pool` workflow once (source=r2 after a Day 1 publish, or source=artifact for the Day 0 bulletin) so `pool/manifest.json` exists, and look at `/healthz` (`source`, `manifest.age_s`). Decide whether to set `MAX_MANIFEST_AGE_S` (default 0 = off).
