# Handoff

## Objective
AI-247 merge PR #19 (streamUrl) and PR #20 (replay-pool failover) and verify that the plain https://ai-247.pages.dev/ plays the live channel without `?src=`, and that the Worker's failover did not break the live stream.

## Done
- Search: `.github/workflows/{deploy,ci,day1,replay-pool}.yml`, `docs/{DEPLOY,PLAN,DAY2,R2_LAYOUT,MANIFEST-SWAP,FAILOVER}.md`, `site/config.json`, PR #19 and PR #20 files/bodies/comments (no review comments on either), deploy runs 42214640757 and 42215042026, post-merge CI.
- PR #19 (cloud/ai247-golive): already merged by its worker at 12:02Z (squash 6238d60). Diff is exactly `site/config.json` `streamUrl: "" -> https://ai247-live.trotha01.workers.dev/live.m3u8` plus `.jmacs/` files. Deploy run 42214640757: `deploy-site` (config sanity, Pages direct upload, site smoke) all green.
- PR #20 (cloud/ai247-failover): already merged by its worker at 12:05Z (squash 2d5e304). Deploy run 42215042026: `test-worker`, `deploy-worker`, Worker smoke all green. Review against DAY2/R2_LAYOUT/MANIFEST-SWAP/FAILOVER: `channel.js` falls back on missing / invalid / empty / stale (`MAX_MANIFEST_AGE_S`, default 0 = off) / missing-segment; `failover.js` keeps MEDIA-SEQUENCE clock-derived (monotonic), tags the switch (`k0`, pool[0] = block start) and the return (`r`, forced), folds completed failovers into `dseq_offset`; live chain returns in its own phase so the uploader's `cycle_start_k`/`prev` contract is untouched. `/healthz` JSON reports `source`, `reason`, `manifest.age_s`, pool state, `failover {since_k, return_k}`. No cron, no notifier (replay-pool workflow is dispatch-only). Tests: 16 unit (hls-parser on every reload: sequences never decrease, per-segment dseq = global tag count, URI/tag per number never change, switch/return tagged, hourly swaps during outage, cold start, flapping, nested re-entry) + 7 dev (real Worker, R2 objects deleted/re-put). 71 unit tests re-run locally: pass. No blocker found.
- PR #21 (golive final status, `.jmacs/` only) merged 12:11Z by its worker; nothing to do.
- Live verification from this sandbox (both hosts reachable):
  - `curl https://ai-247.pages.dev/config.json` -> 200, `streamUrl` = Worker URL.
  - Headless Chromium on plain `https://ai-247.pages.dev/` (no `?src=`): body state `live`, `video.currentTime` 12.5 s -> 36.5 s over 27 s, readyState 4, not paused, no OFFLINE overlay, 0 page errors, 0 console errors; `config.json`, `live.m3u8` and `seg/bulletins/20261106T115430Z/seg_048..054.ts` all 200 from the Worker (cross-origin).
  - Worker after failover deploy: `/healthz` 200 `source=live-manifest`, manifest age ~835 s, 105 segments / 2 blocks, 5 segments HEAD-checked; `/live.m3u8` 200 `#EXTM3U`, `access-control-allow-origin: *`, `x-ai247-source: live-manifest`, MEDIA-SEQUENCE 161177 -> 161179 across 8 s; `scripts/smoke.sh` SMOKE OK.

## Pending
- Trevor: `pool/manifest.json` is not in R2 yet (`/healthz` pool.problem = missing), so until the `replay-pool` workflow is run once (Actions -> replay-pool -> source=r2) a broken `manifest.json` only yields `live-manifest-cached`, not the pool. Not run here (writes to the production bucket; left to Trevor as PR #20's handoff said).
- Trevor: `MAX_MANIFEST_AGE_S` is `0` (stale rule reports but does not switch); set it in `worker/wrangler.toml` (e.g. 14400) only if a dead pipeline should switch to the pool.
- No revert needed: the live stream is healthy after the failover deploy.

## Next step
Merge this branch's `.jmacs/` update to main (PR, after CI), then done.
