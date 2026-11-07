# Handoff

## Objective
AI-247: review Mychal's (EliasTheApe) Puddle Park studio PR #39 for Trevor: re-run/fix the `claude-review` check, human-read the files the bot never saw (`studio/showrunner/channel`, `gate.js`, `start_showrunner.sh`, `pipeline/channel_worker.py`, the engineer agent), confirm nothing in our CI/deploy picks up `studio/`, post one courteous review, give Trevor a 3-line verdict, and port the `player.js` retry pile-up fix to `site/player.js` (own PR, own merge). Trevor merges Mychal's PR(s). Branch `cloud/ai247-pr39`.

## Done
- Search: PR #39 body, its 3 comments, check runs and the `claude-review` job log; docs/CONTRIBUTING.md; `.github/workflows/pr-review.yml` + `.github/scripts/pr_review_comment.py`; `.github/rulesets/main.json` (required checks `tests`, `worker-site-e2e`, `claude-review`; squash/merge/rebase allowed; repo-admin bypass).
- **PR #39 is already closed (05:38Z), not merged.** Mychal split it into #40 README+engine, #41 pipeline, #42 showrunner, #43 engineer, #44 box scripts/Cloudflare/tools, "same code plus the fixes from this review". Verified file by file: the five branches cover exactly #39's 44 files plus `studio/.gitignore` and `studio/env.box.example`; 39 files are byte-identical to #39's head, 5 differ (README, `channel`, `gate.js`, `start_showrunner.sh`, `tools/box.sh`: all hardening, listed in the review notes below).
- `claude-review` on #39 failed for a tooling reason, not the API: Claude returned a success result after 14 turns and claude-code-action discards a result above `MAX_TURNS` (12), so the structured output was lost and the check went red (`Claude reported a successful result after 14 turns, exceeding the configured maximum of 12`). Cost of that run: about 0.01 USD.
- Split PR checks at 05:44Z: #40 and #44 all green; #41 and #43 red on a real **blocking** bot finding each (see Pending); #42 `claude-review` still running.

## Pending
- #41 blocking (bot): `studio/pipeline/channel_worker.py` passes the whole worker environment (`{**os.environ, ...}`) to the Blender render that runs AI-written plug-ins; if the R2 keys are in that environment they reach plug-in code. Verify in the human read.
- #43 blocking (bot): `studio/engineer/engineer_loop.py` reviewer gate accepts a stale `review.jpg` from an earlier round.
- Human read of channel / gate.js / start_showrunner.sh / channel_worker.py / engineer code: in progress.
- pr-review.yml fix (turn cap + a run that could not complete must not read as a failed review): to do on its own branch, own PR, merge.
- Deploy collision check for `studio/cloudflare/aitv-live/wrangler.toml`: in progress.
- `site/player.js` retry pile-up port: to do, own PR.

## Next step
Finish the human read, then post the review(s) on the open split PRs (#39 is closed, so the review goes where the code now is), then the two own PRs.
