# Contributing

## How a change lands

1. Push a branch to this repo (collaborators) or open a PR from a fork.
2. Open a pull request against `main`. Draft PRs get no review until you mark them ready.
3. Three checks must pass before the PR can merge (enforced by the `protect-main` ruleset in
   `.github/rulesets/main.json`):
   - `tests` and `worker-site-e2e` from `ci.yml`: the Python units, HLS seam tests, Worker tests and the
     browser e2e. No secrets, no deploy.
   - `claude-review` from `pr-review.yml`: Claude reads the diff and posts one comment with **Blocking**
     and **Non-blocking** findings, ending in `Verdict: PASS` or `Verdict: BLOCK`. BLOCK fails the check.
4. Fix blocking findings and push; every push re-runs the checks (the previous review is cancelled).
5. Merge (squash is fine). The deploy workflow runs from `main` only, never from a PR.

No force-pushes to `main`, no direct pushes: everything goes through a PR. The repo owner (admin) can
bypass the ruleset in an emergency; that bypass is for humans, not automation.

## Fork PRs

The tests run on fork PRs without secrets. The Claude review is skipped for forks (it would need the API
key), so the owner reviews those by hand and merges with the admin bypass, or pushes the branch into this
repo to get the automatic review.

## Rules of the road

- This repo is public. Never commit keys, stream keys or tokens; secrets live only in Actions secrets.
- Don't change `deploy.yml`, `day0.yml`, `day1.yml` or `replay-pool.yml` to run on `pull_request`.
- Keep the R2 layout (`docs/R2_LAYOUT.md`) and the root `manifest.json`-last ordering intact; those are
  blocking findings in review.
- The `.jmacs/` directory holds cloud-worker status files; a PR that changes only those is auto-passed by the
  review job.

## Running the checks locally

```sh
pip install -r requirements.txt
python -m pytest tests/test_day1_units.py tests/test_seam.py tests/test_units.py tests/test_publish.py tests/test_replay_pool.py
npm ci --prefix worker && npm test --prefix worker
```
