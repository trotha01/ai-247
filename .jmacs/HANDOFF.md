# Handoff

## Objective
AI-247: architecture page that visualizes Puddle Park's nodes (showrunner, writer, Blender, TTS, backdrops, publish, Worker, player) at site/puddle-architecture.html, mapped from studio/ plus newsbot/publish.py, newsbot/channel.py, worker/src, site/. Linked from the site footer and README, render-checked in CI. Branch `cloud/puddle-arch`.

## Done
- v1 was already on main (PR #48, another session); Trevor's PR #51 trimmed operational details from it.
- PR #52 (merged 926bde0, 09:04Z): v2 page. It has separate lanes, plus the shared Qwen llama-server and channel service nodes. Each node has Runs on and Triggered by, checked against the loops in studio/, and source links point to main. #51's trims also apply to the new text. It adds site/test/e2e-architecture.js (light 1100 px and dark 360 px: nodes, labelled edges, no overlaps, full panels, no horizontal scroll, no errors, footer link, named paths exist) in worker-site-e2e with screenshots, and a README link. Four claude-review rounds: 0 blocking findings. The llama flags and restart details were trimmed, and the rest was answered on the PR.
- Live check (09:17Z, headless, 360 px): https://ai-247.pages.dev/puddle-architecture.html returns 200 with 15 nodes and 19 edges. Panels open, there is no horizontal scroll and no JS errors, and none of the trimmed strings appear. The ai-247 footer links it.
- Follow-up on this branch: PR #54 renamed the Puddle Park Worker aitv-live to puddle-live while #52 was in review. The page now names puddle-live and links studio/cloudflare/puddle-live/wrangler.toml and .github/workflows/deploy-puddle.yml. The path check also covers .github/ (44 paths, all exist).

## Pending
- Follow-up PR checks, then merge.
- jmacs todo-status done with the page URL: jmacs is not installed in cloud sessions, so the orchestrator applies it from status.json.

## Next step
Merge the follow-up PR when green. Nothing else.
