# Handoff

## Objective
AI-247: make the GitHub Actions episode cron (`day1-episode`, `23 */3 * * *`) fire unattended and prove it (a schedule-triggered run succeeds end to end, a new episode + root `manifest.json` land in R2, `/healthz` on the `ai247-live` Worker reflects it), then triage stale AI-247 todos and draft PR #14. Record the proof in docs/PLAN.md.

## Done
- Search: docs/PLAN.md, DEPLOY.md, FAILOVER.md, R2_LAYOUT.md, `.jmacs/HANDOFF.md` + `status.json` on every `cloud/*` branch, all 23 PRs (REST; `gh pr list` GraphQL is blocked here), the day1-episode run list via REST, the job log of run 42214045472. `kb search` / `jmacs` are not installed in the cloud session (not on PATH, nothing under /Users), so todo verdicts are recorded here instead of with `jmacs todo done`.
- Diagnosis (no scheduled run has ever existed: `actions/runs?event=schedule` total_count 0 for the whole repo):
  - The cron landed on `main` at 09:48:54Z (PR #3) and the file was last changed on main at 11:47Z (PR #18). The only cron slot since then was 12:23Z and it did not fire. Workflow state `active`, repo not a fork, not archived, pushed_at 12:47Z (no 60-day inactivity), `DAY1_CRON_ENABLED` unset per the golive handoff (a `false` value would still create a run with the job skipped, and there is no run at all), nothing was running at 12:23Z (last dispatch ended 12:10Z, concurrency is queue-not-cancel). Repo variables and Actions permissions are 403 through the session proxy, so they are not read directly.
  - Conclusion: nothing in the repo blocks the schedule; one slot was missed, consistent with GitHub's documented delay/drop of `schedule` events (and the file having been re-registered 36 min before the slot). The fix PR is itself a push to `main` that re-syncs the schedule.
  - Real bug found in the same workflow: the replay step ran `gh run list --workflow day1-episode.yml`, which is a FILE lookup and 404s (confirmed in the run log), so no replay artifact was ever fetched (`replay_blocks: 0`). Fixed to `day1.yml`. R2 publishing was unaffected (it takes replays from the live manifest).
  - Budget/price guard on a scheduled run: `inputs.*` are empty, so TTS = kokoro and the Haiku writer is on. The cap is a preflight guard (`Meter.preflight`): a call that could cross 0.05 USD is skipped, the rest goes extractive, `budget_abort` is recorded and the run stays green; `test_render_under_25_minutes_and_cost_cap` only asserts cost <= cap. Observed cost 0.005 USD/run; 8 runs/day is ~1.2 USD/month, inside the 10 USD monthly limit. Documented in the workflow header.
- day1.yml on this branch: header comment with the schedule facts, a "Trigger" step that logs `event=` (schedule vs workflow_dispatch; no secrets), the replay `--workflow day1.yml` fix. Cron line unchanged (`23 */3 * * *`).
- Live check from this session (hosts allowed in the personal environment "ai-247"): `/healthz` ok, `source=live-manifest`, manifest uploaded 12:10:59Z (run 42214045472), 205 segments / 3 blocks; `pool/manifest.json` now exists (built 13:05:53Z from R2, so the replay-pool workflow has been run).

## Pending
- PR for this branch: open, wait for ci, merge to main (before the 15:23Z slot).
- Wait for the 15:23Z scheduled run; verify success, Publish step keys, root manifest in R2 via `/healthz` (`manifest.uploaded` after 15:23Z, blocks 3 with the new bulletin first).
- Close draft PR #14 (cloud/ai247-deploy, `.jmacs/` only; deploy.yml landed via PRs #15/#17) with a comment.
- Todo triage: jmacs unavailable here; verdicts in the final handoff for the orchestrator to apply.
- docs/PLAN.md section "Cron proven".

## Next step
Open the PR, merge after ci, then poll `actions/workflows/409166637/runs?event=schedule` from 15:23Z.
