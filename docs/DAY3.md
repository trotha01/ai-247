# Day 3: static player (site/)

`site/` is a static page (no build step): `index.html`, `player.js`, `style.css`, `sources.json`, `config.json`.

- **Player**: hls.js 1.6.15 from jsDelivr, pinned by exact version plus a `sha384` SRI hash of `dist/hls.min.js` (taken from the npm package; jsDelivr serves it unmodified). Safari/iOS uses native HLS.
- **Labelling**: a fixed `AI-GENERATED` badge in the header and a disclosure line above the player.
- **Sources**: `site/sources.json` lists the 8 Day 0 feeds. It is hand-maintained; update it when `newsbot/feeds.py` changes. Per-story citations are already burned into the video by the source-citation cards.
- **Fallback**: if `config.json` has no `streamUrl`, the playlist or segments fail fatally, or playback makes no progress for 15 s, the page shows an overlay ("The channel is offline or temporarily stalled...") and retries every 10 s, recovering by itself.
- **Config**: `site/config.json` `streamUrl` is empty until the Day 2 Worker exists. `?src=<m3u8>` overrides it. Test-only `?stall=<ms>&retry=<ms>`.

## Testing (done in the cloud session)

```
site/test/make_stream.sh OUT            # Day 0-spec stand-in segments (see below)
cd site/test && NODE_PATH=$(npm root -g) node e2e.js OUT path/to/hls.min.js
```

`e2e.js` serves `site/` and the stream locally (`serve.py`), routes the CDN URL to a local hls.js copy (the SRI hash is still enforced), and checks: label, 8 sources, no JS errors, offline message with no stream configured, real playback with advancing `currentTime`, 404 playlist -> fallback and later recovery, hanging segments -> stalled fallback. All passed in Playwright Chromium.

**Caveat**: the real `bulletin-day0` artifact (run 42187611180) could not be downloaded from the cloud session (the blob host `productionresultssa4.blob.core.windows.net` is blocked, as is jsDelivr). The tests used ten 6 s segments made with ffmpeg to the same spec (H.264 720p30, 2 s closed GOP, AAC 48 kHz mono, `independent_segments`), not the real bulletin. To re-run on the real one: download and unzip the artifact and pass that directory to `e2e.js`. Not tested: Safari/Firefox, the live CDN fetch, Day 2 Worker CORS.

## What Trevor must do to deploy (nothing below was done)

1. Cloudflare dashboard -> Workers & Pages -> create a Pages project connected to `trotha01/ai-247`, production branch `main`, no build command, output directory `site`. (Or `wrangler pages deploy site`.) Alternatively enable GitHub Pages from a workflow; this repo has none.
2. Once the Day 2 Worker exists, set `streamUrl` in `site/config.json` to its playlist URL via a PR.
3. The Worker/R2 responses for the playlist and segments need `Access-Control-Allow-Origin` for the Pages origin (or `*`), since hls.js fetches them with XHR.
4. Optional: add a CSP header (`script-src 'self' https://cdn.jsdelivr.net`) in a Pages `_headers` file.
5. Optionally run `e2e.js` against the real Day 0 artifact and in Safari/Firefox before announcing.

**Update:** `site/test/e2e-worker.js` now runs the page against the real Worker under `wrangler dev --local` (cross-origin `?src=`): playback, CORS and `video/mp2t` verified; runs in CI (`worker-site-e2e`).
