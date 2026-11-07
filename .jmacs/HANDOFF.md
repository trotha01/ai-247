# Handoff

## Objective
AI-247: architecture page that visualizes Puddle Park's nodes (showrunner, writer, Blender, TTS, backdrops, publish, Worker, player) at site/puddle-architecture.html, mapped from studio/ on branch studio-puddle-park (PR #39) plus newsbot/publish.py, newsbot/channel.py, worker/src, site/. Linked from the site footer, render-checked in CI. Branch `cloud/puddle-arch`.

## Done
- Found a first version already on main (PR #48, c65ef0b, another session): inline SVG, info panel, footer link in site/index.html.
- PR #39 is closed unmerged, so only site/, docs/ and the CI test hook change here.
- Verified against the code: producer keeps inbox 8 deep (2 at once, polls 5 s); channel worker takes 4 scenes or a partial block after 180 s, voice.py then Blender as user render then ffmpeg 6 s HLS, publish_many, 8 GB cap, MOSS window every 600 s; engineer loop polls proposals every 20 s; channel approve copies action.py to actions/live/; start_showrunner.sh writes showrunner/url.txt (bucket root) for the showrunner-link Worker; aitv-live is worker/src with PREFIX=puddle/, WINDOW 5, MAX_MANIFEST_AGE_S 1800.

## Pending
- v2 page: non-overlapping lanes, Qwen llama-server and channel service nodes, "runs on" and "triggered by" per node.
- CI: headless render check of the page in worker-site-e2e.
- PR, checks, merge; todo status.

## Next step
Write site/puddle-architecture.html v2 and site/test/e2e-architecture.js.
