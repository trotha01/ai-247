# Handoff: AI-247 go live on ai-247.pages.dev

## Objective
Make https://ai-247.pages.dev play the 24/7 channel: verify R2 has a manifest, verify the Worker playlist (CORS, media sequence), test the player with ?src=, then set streamUrl in site/config.json via PR, merge, let deploy.yml push the site, and re-test the plain URL.

## Done
- Read docs/PLAN.md, DAY2.md, DEPLOY.md, R2_LAYOUT.md, worker/wrangler.toml, worker/src, site/, ci.yml, day1.yml, deploy.yml, scripts/smoke.sh.
- State verified via gh: PR #18 (Day 1 publish to R2, segments first, root manifest last) merged 11:47Z. day1-episode run 42212912268 (dispatched on main 11:48Z) has passed render + tests and is in the "Publish to R2" step. deploy run 42213278774 (PR #8 merge) failed only in deploy-site "Deploy Pages" (token lacks Pages: Edit, Trevor fixing).
- Branch cloud/ai247-golive created from main.

## Pending
- Wait for run 42212912268 to finish; confirm manifest.json + segments written in its log.
- Sandbox network: Default environment blocks workers.dev / pages.dev / cdn.jsdelivr.net (CONNECT 403). Requested a personal environment allowing those hosts. Fallback: verify from GitHub Actions.
- Worker curl checks, player Playwright check with ?src=, streamUrl PR, deploy, final check.

## Next step
Confirm the run's publish log, then curl the Worker.
