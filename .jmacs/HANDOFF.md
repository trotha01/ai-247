# Handoff

## Objective
AI-247 "fix PR 8 check and test R2 upload": get PR #8 (Day 3 dark-mode link colour + docs) green and merged; exercise the real R2 upload once and record the result in docs/PLAN.md.

## Done
- Read ci.yml, day0.yml, day1.yml, newsbot/r2.py, docs/PLAN.md, docs/DAY2.md, docs/R2_LAYOUT.md, PRs #8, #11 (merged), #12 (merged), #13 (merged).
- PR #8 run 42202479950: apt finished 10:56:22, then no output inside `pip install -q` until the 15 min job timeout cancelled it at 11:08:33. Same stall PR #12 fixed on main; PR #8's branch is 7 commits behind main.
- day1.yml has NO R2 upload (newsbot/day1.py never calls r2.py). The uploader is only called from newsbot/pipeline.py (Day 0), and day0.yml passes the R2_* secrets. So the upload test uses the day0-bulletin workflow on main.

- PR #8 branch updated from main via the REST update-branch route (head ef3d049); ci run 42211791142 in progress.
- day0-bulletin run 42211796435 on main (dispatched before the orchestrator's correction): green, stage r2_upload 18.36 s with the real secrets, Day 0 layout bulletins/<ts>/ (manifest.json before segments).
- Orchestrator correction received: wire the upload into Day 1. Done on this branch: newsbot/channel.py (Python port of the Worker swap math, vectors checked against worker/src/playlist.js), newsbot/publish.py (segments first, per-block manifest after its segments, root manifest.json last in one PutObject; replays from the live manifest; skip with a log line without secrets), r2.py client()/bucket() helpers, tests/test_publish.py (17 tests, pass), day1.yml step "Publish to R2" after the Tests step with the four R2_* secrets, ci.yml runs the new test, docs/R2_LAYOUT.md section.

## Pending
- Open the PR for this branch, merge after ci; merge PR #8 after ci.
- Dispatch day1-episode on main: llm=off, then llm=on (max two). Confirm keys and the root manifest in the log.
- Record "R2 upload verified" in docs/PLAN.md (second small PR or the same branch after the runs).

## Next step
Push, open PR, wait for ci on both PRs.
