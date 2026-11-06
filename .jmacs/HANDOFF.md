# Handoff

## Objective
AI-247 auto-deploy on merge to main: `.github/workflows/deploy.yml` (Worker via cloudflare/wrangler-action on `worker/**`, Pages site via `wrangler pages deploy site/ --project-name=ai-247` on `site/**`), tests first, concurrency group, no-op when `CLOUDFLARE_API_TOKEN` is absent, post-deploy `scripts/smoke.sh`, `docs/DEPLOY.md`.

**Stopped on request** (message relayed from Trevor via the Day 1 status session, 2026-11-06): no further changes from this session; a Fable agent takes over from branch `cloud/ai247-deploy`. Nothing was merged.

## Done
Search only; no workflow, script or doc was written yet. Findings for whoever continues:

- **Pages project name**: `ai-247` (https://ai-247.pages.dev), from PR #8 (`docs/DAY3.md` diff). It was deployed by direct upload of a `_worker.js` (Pages advanced mode) and is NOT Git-connected. `wrangler pages deploy site --project-name=ai-247 --branch=main` replaces that stopgap with the plain static files, which is the intended result.
- **Worker**: name `ai247-live`, `worker/wrangler.toml`, R2 binding `ai247-media` (bucket must exist or `wrangler deploy` fails), vars `PREFIX`, `WINDOW`, `EPOCH=1793000000`. Endpoints: `/healthz` -> `ok`; `/live.m3u8` (alias `/index.m3u8`) with `content-type: application/vnd.apple.mpegurl`, `cache-control: public, max-age=1`, CORS `access-control-allow-origin: *`, 503 when `manifest.json` is missing in R2; `/seg/<key>.ts` -> `video/mp2t`. HEAD is supported.
- **Worker tests**: `cd worker && npm ci && npm test` = `test/unit` (vitest, <1 s) + `test/dev` (spawns `wrangler dev --local`, ~30 s). PR #11 (open, `cloud/ai247-e2e`) adds `test/e2e/layout.test.js` (needs python3 + ffmpeg) to `npm test` and a `worker-site-e2e` job in `ci.yml`, plus `PREFIX` normalisation in `worker/src/index.js`. To keep deploy.yml independent of that, run `npx vitest run test/unit test/dev` in `worker/` as the deploy gate.
- **Versions verified via `git ls-remote --tags` on 2026-11-06**: cloudflare/wrangler-action v4.1.3 (node24; inputs `apiToken`, `accountId`, `workingDirectory`, `wranglerVersion`, `command`, `packageManager`; outputs `deployment-url`, `command-output`, `pages-deployment-id`); actions/setup-node v7.1.0; actions/checkout v7.0.1; actions/cache v6.1.0. wrangler latest on npm = 4.158.0 (matches `worker/package.json`); pass `wranglerVersion: "4.158.0"`.
- **Secrets context cannot be used in job-level `if`**: gate with a step that reads `${{ secrets.CLOUDFLARE_API_TOKEN }}` into an env var, writes `has_token=true|false` to `$GITHUB_OUTPUT`, prints "CLOUDFLARE_API_TOKEN not set: deploy skipped (no-op)", and later steps use `if: steps.gate.outputs.has_token == 'true'`. Same for `CLOUDFLARE_ACCOUNT_ID`.
- **Per-job path filters**: workflow-level `on.push.paths` applies to all jobs, so use a `changes` job (`git diff --name-only ${{ github.event.before }} ${{ github.sha }}` with `fetch-depth: 0`, deploy both if `before` is all zeros) or `dorny/paths-filter@v3`. Add `workflow_dispatch` with a `target` input (all/worker/pages) so an older commit can be redeployed for rollback.
- **Concurrency**: `concurrency: { group: deploy, cancel-in-progress: false }` at workflow level.
- **Smoke test plan** (`scripts/smoke.sh <worker-base-url>`): `/healthz` 200 `ok`; `/live.m3u8` 200, first line `#EXTM3U`, `access-control-allow-origin` present; read `EXT-X-MEDIA-SEQUENCE`, wait 7 s (segments are 6 s, so the sequence must rise), fetch again and require a strictly higher value; resolve the first segment URI (`seg/...`) against the playlist URL, require 200 and `content-type: video/*`. Exit non-zero on any failure. Worker URL comes from `steps.deploy.outputs.deployment-url`. Note: an empty R2 bucket gives 503 on `/live.m3u8`, so the smoke test fails until the first manifest is uploaded.
- Local tooling in this session: node 22, `npm ci` done in `worker/` (wrangler 4.158.0 works through the proxy), so `wrangler dev --local` can be used to test `smoke.sh` offline (EPOCH 1793000000 is in the past, so the clock is live).

## Pending
- Everything in Objective: write `deploy.yml`, `scripts/smoke.sh`, `docs/DEPLOY.md`; test `smoke.sh` against `wrangler dev --local`; PR, CI check, merge.
- Draft PR for this branch (number in `.jmacs/status.json`).

## Next step
Taken over by a Fable agent from `cloud/ai247-deploy`. This session makes no further changes.
