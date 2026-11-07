# Handoff

## Objective
AI-247: Mychal's (EliasTheApe) Puddle Park studio code. It started as PR #39, closed and split into #40-#44. Trevor's final scope:
- confirm and guard that our CI/deploy never touches `studio/`;
- merge #40-#44 (squash, in order; #43 too, despite requested changes);
- track every review finding in one issue, linked from each merged PR;
- set the `claude-review` policy (#47: NEUTRAL);
- point Puddle Park at Trevor's account (shared bucket `aitv-media` under `puddle/`, Worker `puddle-live` deployed only by our workflow);
- port the `site/player.js` retry fix.

Do not deploy anything. Status branch `cloud/ai247-pr39`.

## Done
- **#46** `site/player.js` retry fix: merged 4e36185.
- **#49** CI guard: merged ca3aa27. `tests/test_deploy_guard.py` runs in `ci.yml`. `deploy.yml` was deliberately not edited, because it is in its own trigger paths and an edit would redeploy production.
- **#40-#44** merged in order, squash. No bypass was used: all three checks were green on every head.
  - #40: 916f73c
  - #41: 13df8b2
  - #42: cc44658 (head da87125)
  - #43: ca82dd8
  - #44: ca89864

  Each PR has a comment linking #50. Only `ci` ran on those merges; there was no `deploy` run.
- **#50** tracking issue "Puddle Park: review findings to fix in re-architecture": every finding with file:line. The open blocker from #43 is item 1: root reads the engineer-owned `review.md` through a symlink (`engineer_loop.py:96`, `:124`). A progress comment marks what #54 resolved.
- **#54** Puddle Park on Trevor's account: merged ca5c18b.
  - Worker `puddle-live`, bucket `aitv-media`, `PREFIX=puddle/`. Worker `puddle-showrunner`.
  - The tunnel address moved to `puddle/showrunner/url.txt`. `channel_worker.py` refuses a prefix outside `puddle/`.
  - `PUDDLE_STREAM_URL` replaces the hardcoded Worker URL.
  - `.github/workflows/deploy-puddle.yml` is the only deploy path. It runs only on main, only for `studio/cloudflare/**` changes, and only when `vars.PUDDLE_DEPLOY_ENABLED == 'true'`. Its run on the merge (42358051355) skipped every deploy step.
  - Includes the note to Mychal.
- **#45** closed as superseded by #47.
- **#47** rebuilt on main to the NEUTRAL policy and the turn cap.
  - `pr-review.yml` now has two jobs: `review` and the required `claude-review` gate job. The gate is skipped (which counts as passing) when a run errors or returns no verdict; it fails on a blocking finding or the fork gate. `MAX_TURNS` is 30.
  - 18 tests. tests and e2e are green.
- Superseded instructions, recorded so nobody acts on them: the separate `puddle-media` bucket (Trevor reverted to the shared `aitv-media`); merging #39 (closed; replaced by #40-#44).

## Pending (needs Trevor)
1. **#47 is not merged.** Its `claude-review` is red with one blocking finding: the policy itself ("fail-open on a required check needs a maintainer decision"). Trevor's bypass authorization covers only a crashed run, so I did not bypass and did not re-run to shop for a different answer. PR comment 6704751418 explains this. Trevor: merge #47 with the owner bypass to confirm NEUTRAL.
2. Create an R2 API token for `aitv-media` (Object R/W) for Mychal's box (`.r2.env`, `R2_BUCKET=aitv-media`). The token is bucket-scoped; the `puddle/` limit is enforced in code.
3. When Puddle Park should go live on Trevor's account: set the repository variable `PUDDLE_DEPLOY_ENABLED=true`, then run `deploy-puddle`. The token needs Workers Scripts: Edit.
4. Optional: the `puddle-park.pages.dev` Pages project is still on Mychal's account. Say if a Pages job is wanted here under a new name.

## Next step
Nothing for me until Trevor answers the items above. After #47 merges, the first PR's run will show the two-job structure (`claude-review (run)` plus the `claude-review` gate).
