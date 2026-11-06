# Handoff

## Objective
AI-247 replay-pool failover (no alerts, no cron, no external services): a bootstrap that publishes `pool/manifest.json` (loop of the Day 0 bulletin or the latest good episode already in R2), Worker fallback to that pool when `manifest.json` is missing / empty / stale beyond `MAX_MANIFEST_AGE_S` / references missing segments, `/healthz` JSON saying which source is live and the manifest age, tests (hls-parser + wrangler dev/Miniflare) that the playlist stays valid across the switch and the return.

## Done
- Search: read docs/PLAN.md, DAY2.md, MANIFEST-SWAP.md, DAY3.md, worker/ (index.js, playlist.js, tests), site/, workflows, newsbot/playlist.py, r2.py, pool.py, manifest.py; PR #11 (e2e/key layout, open) and PR #12 (merged). Reusing: playlist.js `eras`/`tagsBeforeEras`/`layout` (manifest-swap primitives), hls-parser, vitest, wrangler dev --local (Miniflare R2), pool.py block shape, r2.py credential convention.

## Pending
- Worker: `worker/src/failover.js` (pure state machine + composed playlist), `worker/src/channel.js` (R2 loads, checks, caching), small edits in `index.js`.
- Bootstrap: `newsbot/replay_pool.py` + `tests/test_replay_pool.py` + dispatch-only workflow.
- Docs: `docs/FAILOVER.md`. PR, CI, merge.

## Next step
Write the Worker code and its unit tests.
