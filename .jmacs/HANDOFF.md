# Handoff

## Objective
AI-247: fix the failed `hourly-bulletins` scheduled run (42298386727, the first `schedule` event ever for this repo, 21:38Z on 2026-11-06), make scheduled runs degrade gracefully (publish whatever rendered, never fail for a lost slice), restore fresh footage, prove the next cron slots. Branch `cloud/ai247-hourlyfix`.

## Done
- Diagnosis (docs/PLAN.md "Scheduled run 1"): schedule fired; 2 of 6 full bulletins were rejected by the >= 4 sources acceptance floor (9 aired stories from 3 sources, rank order 4 + 4 + 1 under the hourly per-source cap 4); 1 slice lost to apt timeouts (ffmpeg install > 120 s, 3 attempts); stitch published 3 bulletins (30 min) but the run went red because matrix jobs failed. Not secrets, not inputs defaults, not budget, not concurrency.
- Protective dispatch from main at 01:00:44Z (run 42321630781) because the live manifest was 11,157 s old against the 14,400 s failover.
- Fix on this branch: `rank.interleave_sources` + `NEWSBOT_RUNDOWN_INTERLEAVE=1` (round-robin the rundown by source), `NEWSBOT_MIN_SOURCES` floor 3 kept from PR #36 (merged by the cron worker meanwhile), apt bounds 180/240 s + named stage + `dpkg --configure -a` before retry + static ffmpeg fallback from GitHub releases when apt ffmpeg still fails (hourly.yml and ci.yml; the protective dispatch lost slice 5 to the same ffmpeg stall), render matrix `continue-on-error`, stitch warns per missing slice and fails only when nothing rendered. Unit test added; 40 tests green locally.

## Pending
- PR to main: ci (tests, worker-site-e2e) + claude-review, squash-merge.
- After the merge: dispatch one run, confirm `/healthz` manifest uploaded and `/live.m3u8` serves the new bulletin prefix.
- Watch the 01:23Z and 02:23Z slots; record in docs/PLAN.md watch log. If neither fires: disable/enable toggle via `gh api` on workflow 409501317 and note it.

## Next step
Open the PR and wait for the checks.
