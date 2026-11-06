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

- PR #25 (this fix) ci green (run 42223392070), squash-merged to main as 5ab227c at ~13:17Z. Branch restarted from main.
- Draft PR #14 closed with a comment: superseded by PRs #15/#17 (deploy.yml, smoke.sh, DEPLOY.md); its branch only differs from main in `.jmacs/`.

- Todo triage (jmacs is not installed in the cloud session, so I could not run `jmacs todo list --open` or `jmacs todo done`; the orchestrator/Trevor maps the ids t-675fb31c, t-dd8fda48, t-89a45dda, t-f6d0d35c, t-89a55812, t-e3e3ac7a to the workstreams below and applies the verdicts). Verified from `main` and the Actions/PR history on 2026-11-06:

  | AI-247 workstream (branch) | Evidence on main / Actions | Verdict |
  |---|---|---|
  | Day 0 bulletin (`cloud/ai247-day0`, PRs #1 #2) | `day0.yml`, `newsbot/pipeline.py`; runs 42187611180, 42197942314, 42211796435 green (last one with real R2 upload) | work done; its status.json still says `needs_you` (Trevor to watch the clip). Mark done unless Trevor still wants to review it. |
  | Day 1 episode (`cloud/ai247-day1`, PRs #3 #4 #5 #9 #13) | `day1.yml`, `newsbot/day1.py` etc.; Haiku runs 42203098918, 42210163643, 42214045472 green; PLAN.md "Day 1 run results" | work done; status.json `needs_you` (watch the episode). Same as Day 0. |
  | Day 2 Worker (`cloud/ai247-d2`, PR #7) + manifest swap (`cloud/ai247-swap`, PR #10) | `worker/src/{index,playlist}.js`, docs/DAY2.md, MANIFEST-SWAP.md; deployed by deploy run 42215042026; `/healthz` ok from this session | done |
  | Day 3 player (`cloud/ai247-d3`, PR #6; `cloud/ai247-d3-fix`, PR #8) | `site/`, docs/DAY3.md; Pages deploy run 42214640757 green; `ai-247.pages.dev/config.json` 200 | done |
  | e2e + R2 key layout (`cloud/ai247-e2e`, PR #11) | `worker/test/e2e`, docs/R2_LAYOUT.md, ci job `worker-site-e2e` green on main | done |
  | Install-step stall (`fix/install-step-timeout`, PR #12; `cloud/redispatch-d1` proposal patch) | PR #12 merged (timeouts + retries in day0/day1/ci); the redispatch-d1 verbose-logging patch was never applied and is superseded by #12 (installs 31-87 s since) | done (proposal superseded; nothing to apply) |
  | Auto-deploy on merge (`cloud/auto-deploy` PR #15, `cloud/auto-deploy-fix` PR #17, draft PR #14 on `cloud/ai247-deploy`) | `deploy.yml`, `scripts/smoke.sh`, docs/DEPLOY.md on main; deploy runs green for Worker and site; PR #14 closed today as superseded | done |
  | Day 1 publish to R2 (`cloud/ai247-r2test`, PRs #18 #22) | `newsbot/publish.py`, step "Publish to R2"; runs 42212912268 and 42214045472 wrote 108 objects each; PLAN.md "R2 upload verified" | done |
  | Go live (`cloud/ai247-golive`, PRs #19 #21) | `site/config.json` streamUrl = Worker playlist; plain pages.dev plays (mergeverify handoff) | done |
  | Replay-pool failover (`cloud/ai247-failover`, PR #20) | `worker/src/{failover,channel}.js`, `newsbot/replay_pool.py`, `replay-pool.yml`, docs/FAILOVER.md; replay-pool run 42222599138 (13:04Z) succeeded and `/healthz` shows `pool.ok=true` (200 segments / 2 blocks) | done (Trevor's one manual step, running the pool workflow once, has happened) |
  | Merge-verify (`cloud/ai247-mergeverify`, PR #23) | merged dabb881 | done |
  | Episode cron unattended (this item, `cloud/ai247-cron`, PR #25) | see above | in progress until the scheduled run is green |

  Left open / unclear: whether Trevor has done the Day 0 / Day 1 "watch it" reviews (not verifiable from the repo); `MAX_MANIFEST_AGE_S` is still `0` in `worker/wrangler.toml` (stale rule reports but never switches to the pool), a decision only Trevor can make.

- Trevor's request (14:35Z): manual run dispatched from main (e9fdd8c), run 42235237153, default inputs (tts blank = kokoro, llm on), i.e. what a scheduled run does. Being watched to completion; then R2 / `/healthz` / `live.m3u8` / pages.dev are checked.
- `DAY1_CRON_ENABLED`: the variables API is 403 through the session proxy, so the value cannot be read here. The job-level gate on a `schedule` event is `vars.DAY1_CRON_ENABLED != 'false'`: unset or any other value = true (job runs); exactly `false` = job skipped, but GitHub still creates a run record with conclusion `skipped`. There is no `schedule` run record at all, so the gate is not why 12:23Z was missed; 09:23Z predates the cron (it reached main at 09:48:54Z). The Trigger step now prints `DAY1_CRON_ENABLED=<value or <unset>>` (a variable, not a secret) so the 15:23Z run shows it.
- main moved while waiting: PRs #24 (pool seeded, MAX_MANIFEST_AGE_S 14400), #26 (ruleset: `tests`, `worker-site-e2e`, `claude-review` required on main), #28 (pool verify); Trevor dispatched run 42229528561 from `cloud/ai247-topics` at 13:56Z, which published the manifest live at 14:09:22Z (305 segments / 4 blocks). Branch rebased onto e9fdd8c.

## Pending
- Wait for the 15:23Z scheduled run; verify success, Publish step keys, root manifest in R2 via `/healthz` (`manifest.uploaded` after 15:23Z, blocks 3 with the new bulletin first).
- Todo triage: jmacs unavailable here; verdicts in the final handoff for the orchestrator to apply.
- docs/PLAN.md section "Cron proven".

## Next step
Poll `actions/workflows/409166637/runs?event=schedule` from 15:23Z; when the run is green, check `/healthz` (`manifest.uploaded` > 15:23Z) and the Publish step log, write the PLAN.md section, PR, merge, status done.
