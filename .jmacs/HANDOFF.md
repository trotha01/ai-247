# Handoff: AI-247 go live on ai-247.pages.dev

## Objective
Make https://ai-247.pages.dev play the 24/7 channel: verify R2 has a manifest, verify the Worker playlist (CORS, media sequence), test the player with ?src=, set streamUrl in site/config.json via PR, merge, let deploy.yml push the site, re-test the plain URL.

## Done
- Read docs/PLAN.md, DAY2.md, DEPLOY.md, R2_LAYOUT.md, worker/wrangler.toml, worker/src, site/, ci.yml, day1.yml, deploy.yml, scripts/smoke.sh.
- Prerequisites landed: PR #18 (Day 1 publish to R2) merged 11:47Z; day1-episode run 42212912268 green at 11:56Z. Its Publish step log: 108 objects, 105 segments (100 bulletin + 5 slate) under bulletins/20261106T115430Z/, root manifest.json written last (6,910 bytes), epoch 1793000000, cycle_start_k 161021.
- Worker https://ai247-live.trotha01.workers.dev: scripts/smoke.sh SMOKE OK (healthz 200; /live.m3u8 200, #EXTM3U, Access-Control-Allow-Origin *, EXT-X-MEDIA-SEQUENCE 161039 -> 161040; first segment 200 video/mp2t 451,764 bytes). No redeploy needed.
- Player via ?src= on Pages (headless Chromium with H.264/AAC): state live, currentTime 12.06 -> 20.02 in 8 s, no OFFLINE overlay, playlist + segments with CORS, no JS errors, no failed requests.
- PR #19 (site/config.json streamUrl = https://ai247-live.trotha01.workers.dev/live.m3u8) merged after ci (tests + worker-site-e2e green). deploy run 42214640757: deploy-site success (Pages token permission now works).
- Plain https://ai-247.pages.dev/: config.json served the new streamUrl within ~10 s; headless check: state live, currentTime 12.05 -> 20.04, no overlay, no errors. Screenshots kept in the session scratchpad only (no workflow artifact; no new workflow was added).
- Session network: personal cloud environment "ai-247" (hosts ai247-live.trotha01.workers.dev, ai-247.pages.dev, cdn.jsdelivr.net), approved during the session.

## Pending
- Nothing for this item. Manual items for Trevor: custom domain/route for the Worker and the Pages site (docs/DEPLOY.md); the fixed EPOCH (1793000000) in worker/wrangler.toml and in the published manifest must never change; DAY1_CRON_ENABLED is unset so the 3-hourly cron (23 */3 * * *) is on; a failed day1 run leaves the previous manifest live, so the channel keeps looping the last episode + slate.

## Next step
None. Next manifest refresh: the day1-episode cron at 14:23Z (every 3 hours), which appends a new bulletin and keeps the previous one as a replay.
