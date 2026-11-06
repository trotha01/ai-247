# Handoff

## Objective
AI-247: make the GitHub Actions episode cron fire unattended and prove it (a schedule-triggered run succeeds end to end, a new episode + root `manifest.json` land in R2, `/healthz` on the `ai247-live` Worker reflects it), then triage stale AI-247 todos and draft PR #14. Record the proof in docs/PLAN.md. Branch `cloud/ai247-cron`.

## Done
- Search: docs/PLAN.md, DEPLOY.md, FAILOVER.md, R2_LAYOUT.md, `.jmacs/HANDOFF.md` + `status.json` on every `cloud/*` branch, all PRs (REST; `gh pr list` GraphQL is blocked here), the day1-episode run list via REST, job logs. `kb search` / `jmacs` are not installed in the cloud session (not on PATH, nothing under /Users), so todo verdicts are recorded here instead of with `jmacs todo done`.
- PR #25 (merged 5ab227c, 13:13Z): fixed the silent replay-fetch 404 (`gh run list --workflow day1-episode.yml` is a file lookup; now `day1.yml`), added a Trigger step logging `event=`, documented schedule and cost-cap behaviour in `day1.yml`. The cap is a preflight guard (`Meter.preflight`): a call that could cross 0.05 USD is skipped, the rest goes extractive, `budget_abort` is recorded and the run stays green.
- PR #30 (merged f0921b3, 14:51Z): the Trigger step prints `DAY1_CRON_ENABLED=<value or <unset>>` (a variable, not a secret; the variables API is 403 through the session proxy).
- Draft PR #14 closed with a comment: superseded by PRs #15/#17 (deploy.yml, smoke.sh, DEPLOY.md); its branch only differs from main in `.jmacs/`.
- **Manual run verified end to end (Trevor's request, note for the todo status):** run **42235237153**, `workflow_dispatch` from `main` (e9fdd8c) at 14:35:11Z with the inputs a scheduled run has (tts blank = kokoro, llm on), **success** at 14:45:06Z (9 min 55 s). Timings: install 35 s; replay fetch 7 s (first run ever with replays: 3 earlier artifacts, `replay_blocks: 3`, so PR #25's fix works); render 6 min 16 s (pipeline 376 s; Haiku 59 drafted / 49 supported first pass / 2 rewritten / 0 dropped, cost 0.00459 USD, `budget_abort` false); tests 17 s (75 passed, 1 skipped); Publish 2 min 24 s (`r2 publish: 144.2 s`): `bulletins/20261106T144236Z/` 100 segments + block manifest + 5 slate + manifest, then root `manifest.json` last at 14:45:00Z, 108 objects / 33,025,999 bytes, `cycle_start_k` 162766, `cycle_start_dseq` 26, blocks [bulletin 144236Z, slate, replay 140715Z, replay 120928Z, replay 115430Z]; artifact `episode-day1` 59.7 MB.
  - `/healthz` at 14:46:18Z: ok, `source=live-manifest`, `manifest.uploaded` **2026-11-06T14:45:00.430Z** (was 14:09:22Z), 405 segments / 5 blocks, pool ok (200 segments), `max_age_s` 14400.
  - `/live.m3u8`: the Worker swapped at the loop boundary `k=162766` as designed: at 14:50:16Z media-sequence 162765, `...115430Z/seg_099.ts`, `#EXT-X-DISCONTINUITY`, then `seg/bulletins/20261106T144236Z/seg_000.ts`; that first segment fetched 200 `video/mp2t` 501,772 bytes. Discontinuity-sequence 26 = the published `cycle_start_dseq`.
  - https://ai-247.pages.dev/ (plain URL, headless Chromium from this session): state `live`, `currentTime` 24.2 -> 36.2 s over 12 s, readyState 4, not paused, no offline overlay, 0 page/console errors, fetching `seg/bulletins/20261106T144236Z/seg_003.ts`, `seg_004.ts` (200).
- **Schedule trigger: 12:23Z, 15:23Z and 16:23Z slots all missed; `actions/runs?event=schedule` is 0 for the whole repo (checked 16:51Z).** Diagnosis of the trigger itself, from the API and git on main:
  - Workflow enabled state: every workflow `active` (day1-episode 409166637, hourly-bulletins 409501317).
  - Job `if:` gate (`vars.DAY1_CRON_ENABLED != 'false'`, unset = runs): not the cause. A `false` variable would leave a run record with the job skipped, and there is no record at all. 09:23Z predates the cron (on main since 09:48:54Z).
  - Default-branch recency: `main` received pushes at 13:13, 13:34, 14:51, 14:56, 15:47 and 16:40Z (`pushed_at` 16:49Z); each re-registers the schedule per GitHub staff in community discussion #185355 ("any commit pushed to the default branch will resync the impacted scheduled workflows"). Three slots passed with a cron on main (12:23Z and 15:23Z under day1.yml `23 */3 * * *`; 16:23Z under hourly.yml `23 * * * *`, where PR #33 moved the cron at 15:47Z) and none produced a run.
  - Actor: every PR was merged by `trotha01` (User) and every push run on main has `actor` = `trotha01`, so it is not a bot/removed-collaborator actor problem. Not a fork, not archived, public, owner type User, concurrency queues rather than cancels.
  - What remains is outside the repo: the repository was created today at 07:59:56Z and GitHub's scheduler has never emitted an event for it. Closest matches on GitHub's community forum: #203473 (brand-new public repo, first schedule event about 8 h after creation, no explanation) and #185355 (staff: a backend regression rolled back; later posters with still-silent schedules moved to an external cron calling the `workflow_dispatch` API). No in-repo setting fixes this; the remaining levers are time, a disable/enable toggle of the workflow (a repo-settings change, left to Trevor), or a GitHub Support ticket.
  - Fallback that does not depend on GitHub's scheduler (needs Trevor's account): a Cloudflare Cron Trigger (free) on a Worker that POSTs `/repos/trotha01/ai-247/actions/workflows/hourly.yml/dispatches` with a fine-grained PAT (repository `ai-247`, Actions: read and write) stored as a Worker secret. Not built: it needs the token and a decision on where the cron lives (the live `ai247-live` Worker or a separate one).
- Todo triage (jmacs unavailable here; the orchestrator/Trevor maps t-675fb31c, t-dd8fda48, t-89a45dda, t-f6d0d35c, t-89a55812, t-e3e3ac7a to these workstreams and applies the verdicts). Verified from `main` and the Actions/PR history on 2026-11-06:

  | AI-247 workstream (branch) | Evidence on main / Actions | Verdict |
  |---|---|---|
  | Day 0 bulletin (`cloud/ai247-day0`, PRs #1 #2) | `day0.yml`, `newsbot/pipeline.py`; runs 42187611180, 42197942314, 42211796435 green (last with real R2 upload) | work done; its status.json still says `needs_you` (Trevor to watch the clip). Mark done unless Trevor still wants to review it. |
  | Day 1 episode (`cloud/ai247-day1`, PRs #3 #4 #5 #9 #13) | `day1.yml`, `newsbot/day1.py`; Haiku runs 42203098918, 42210163643, 42214045472, 42235237153 green; PLAN.md "Day 1 run results" | work done; status.json `needs_you` (watch the episode). Same as Day 0. |
  | Day 2 Worker (`cloud/ai247-d2`, PR #7) + manifest swap (`cloud/ai247-swap`, PR #10) | `worker/src/{index,playlist}.js`, docs/DAY2.md, MANIFEST-SWAP.md; deployed by deploy run 42215042026; `/healthz` ok and the boundary swap observed live at 14:50Z | done |
  | Day 3 player (`cloud/ai247-d3`, PR #6; `cloud/ai247-d3-fix`, PR #8) | `site/`, docs/DAY3.md; Pages deploy run 42214640757 green; plain pages.dev plays (checked twice today) | done |
  | e2e + R2 key layout (`cloud/ai247-e2e`, PR #11) | `worker/test/e2e`, docs/R2_LAYOUT.md, ci job `worker-site-e2e` green on main | done |
  | Install-step stall (`fix/install-step-timeout`, PR #12; `cloud/redispatch-d1` proposal patch) | PR #12 merged (timeouts + retries); the redispatch-d1 verbose-logging patch was never applied and is superseded by #12 (installs 31-87 s since) | done (proposal superseded; nothing to apply) |
  | Auto-deploy on merge (`cloud/auto-deploy` PR #15, `cloud/auto-deploy-fix` PR #17, draft PR #14 on `cloud/ai247-deploy`) | `deploy.yml`, `scripts/smoke.sh`, docs/DEPLOY.md on main; deploy runs green for Worker and site; PR #14 closed today as superseded | done |
  | Day 1 publish to R2 (`cloud/ai247-r2test`, PRs #18 #22) | `newsbot/publish.py`, step "Publish to R2"; runs 42212912268, 42214045472, 42235237153 wrote 108 objects each; PLAN.md "R2 upload verified" | done |
  | Go live (`cloud/ai247-golive`, PRs #19 #21) | `site/config.json` streamUrl = Worker playlist; plain pages.dev plays | done |
  | Replay-pool failover (`cloud/ai247-failover`, PR #20; pool PRs #24 #28) | `worker/src/{failover,channel}.js`, `newsbot/replay_pool.py`, `replay-pool.yml`, docs/FAILOVER.md; replay-pool run 42222599138 succeeded, `/healthz` `pool.ok=true`, `MAX_MANIFEST_AGE_S` 14400 | done |
  | Merge-verify (`cloud/ai247-mergeverify`, PR #23) | merged dabb881 | done |
  | Episode cron unattended (this item) | manual path proven; `schedule` event never fired, see above | **not done**: blocked on GitHub's scheduler / Trevor's decision |

  Left open / unclear: whether Trevor has done the Day 0 / Day 1 "watch it" reviews (not verifiable from the repo).

## Coordination
- A separate worker (ai247-coverage, `cloud/ai247-coverage`, PR #33 merged) moved the cadence to hourly in `hourly.yml` (`hourly-bulletins`, cron `23 * * * *`); `day1.yml` is now `workflow_dispatch` only. This task does not touch cadence, cron line or render length. Its proof target is therefore any `schedule` run of `hourly-bulletins`. Trigger facts both workflows share: the gate variable pattern (`*_CRON_ENABLED != 'false'`, unset = runs), the Trigger step pattern, and the replay fetch by file name.

## Pending
- 17:23Z and 18:23Z `hourly-bulletins` slots (poller running on the repo-wide schedule run list).
- If a `schedule` run appears and is green: verify R2 + `/healthz`, write the PLAN.md section, PR, merge, status done.
- If not: PLAN.md records the diagnosis; status `needs_you` for Trevor: (a) toggle the workflow off/on in Actions (community-suggested probe), (b) open a GitHub Support ticket with the run history (0 schedule events since repo creation 07:59:56Z), or (c) approve the Cloudflare cron fallback and create the PAT for it.

## Next step
Wait for the poller (17:23Z / 18:23Z). Then either the proof section or the needs_you handoff, via PR to main (ci + worker-site-e2e + claude-review required).
