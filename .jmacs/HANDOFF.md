# Handoff: AI-247 go live on ai-247.pages.dev

## Objective
Make https://ai-247.pages.dev play the 24/7 channel: verify R2 has a manifest, verify the Worker playlist (CORS, media sequence), test the player with ?src=, then set streamUrl in site/config.json via PR, merge, let deploy.yml push the site, and re-test the plain URL.

## Done
- Read docs/PLAN.md, DAY2.md, DEPLOY.md, R2_LAYOUT.md, worker/wrangler.toml, worker/src, site/, ci.yml, day1.yml, deploy.yml, scripts/smoke.sh.
- State verified via gh: PR #18 (Day 1 publish to R2, segments first, root manifest last) merged 11:47Z. day1-episode run 42212912268 (dispatched on main 11:48Z) has passed render + tests and is in the "Publish to R2" step. deploy run 42213278774 (PR #8 merge) failed only in deploy-site "Deploy Pages" (token lacks Pages: Edit, Trevor fixing).
- Branch cloud/ai247-golive created from main.

- Run 42212912268 green. Publish step log: 108 objects, 105 segments (100 bulletin + 5 slate) under bulletins/20261106T115430Z/, root manifest.json written last (6,910 bytes), epoch 1793000000, cycle_start_k 161021.
- Session network: personal cloud environment "ai-247" (hosts: ai247-live.trotha01.workers.dev, ai-247.pages.dev, cdn.jsdelivr.net) approved; checks run from the sandbox.
- scripts/smoke.sh against the Worker: SMOKE OK (healthz 200; /live.m3u8 200, #EXTM3U, CORS *, media-sequence 161039 -> 161040; first segment 200 video/mp2t 451,764 bytes).
- Headless Chromium (Playwright, H.264/AAC present) on https://ai-247.pages.dev/?src=<worker>/live.m3u8: state live, currentTime 12.06 -> 20.02 in 8 s, no OFFLINE overlay, playlist + 3 segments with CORS, no JS errors, no failed requests. Screenshot kept in the session scratchpad (not committed).
- site/config.json streamUrl set to https://ai247-live.trotha01.workers.dev/live.m3u8 on this branch.

## Pending
- PR for this branch; merge after ci; deploy.yml deploy-site must succeed (needs the Pages: Edit token permission Trevor is adding; last two runs failed with Authentication error 10000).
- Re-run the player check against plain https://ai-247.pages.dev/ (config.json cached ~60 s).

## Next step
Open the PR, wait for ci, merge, watch the deploy run.
