# Handoff

## Objective
AI-247 "local end-to-end and R2 key layout" (Worker/site/docs/ci only; newsbot/ untouched; no deploy).

## Done
- Search done (no kb/~/org available); reused wrangler/miniflare, vitest, hls-parser, Playwright, ffmpeg; no custom HLS code.
- Found mismatch: r2.py -> `bulletins/<ts>/<file>`, manifest.json uploaded before segments; Worker read root -> 503.
- Worker: PREFIX normalised, preflight Range, .ts always video/mp2t. docs/R2_LAYOUT.md has the contract.
- Tests: worker/test/e2e (real r2.upload -> local R2 -> Worker), site/test/e2e-worker.js (browser, cross-origin, real playback). 56 worker tests pass locally; site e2e passes.
- ci.yml job `worker-site-e2e` added.

## Pending
- PR + CI check + merge to main.
- Day 1 owner: upload manifest.json LAST (r2.py still sorted-order) and adopt Layout B in docs/R2_LAYOUT.md.

## Next step
Open PR, wait for CI, merge.
