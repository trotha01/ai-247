# Handoff

## Objective
AI-247 "local end-to-end and R2 key layout": run the Worker under wrangler dev --local with seeded R2, serve site/ via ?src=, prove CORS + manifest format + key layout against newsbot/r2.py, reconcile on the Worker side (PREFIX var, .ts content type), document the layout in docs/, add worker tests + site e2e to ci.yml. Do not edit newsbot/. No deploy.

## Done
- Search: no `kb` CLI and no ~/org here; read PLAN/DAY2/DAY3, playlist.py, r2.py, site/, workflows. Reused wrangler/miniflare, hls-parser, vitest, Playwright, ffmpeg HLS muxer (existing); wrote no HLS parser.
- Finding: r2.py uploads to `bulletins/<ts>/<file>` (sorted, so manifest.json lands BEFORE the segments); Worker read manifest at bucket root -> 503.
- Worker: PREFIX normalised (worker/src/index.js), CORS preflight allows Range, .ts always video/mp2t.
- worker/test/e2e: real newsbot.r2.upload with a fake S3 -> local R2 -> wrangler dev; 8 tests pass.

## Pending
- Site browser e2e against the Worker (site/test), docs/R2_LAYOUT.md, ci.yml jobs, merge main, PR + merge.

## Next step
Write site/test/e2e-worker.js, docs, ci.yml; commit, push, PR, merge.
