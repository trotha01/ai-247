# Deploy

Production deploys happen automatically from `.github/workflows/deploy.yml` on every **push to `main`** (merged PRs). The workflow never runs on `pull_request`.

## What deploys on merge

| Changed paths | Job | What happens |
|---|---|---|
| `worker/**`, `scripts/smoke.sh`, the workflow | `test-worker` then `deploy-worker` | `npm run test:unit` and `npm run test:dev` in `worker/` (the uploader/browser e2e runs in `ci.yml`); only if green, `wrangler deploy` of the Worker `ai247-live` (name from `worker/wrangler.toml`), then `scripts/smoke.sh <worker url>`. |
| `site/**`, the workflow | `deploy-site` | `wrangler pages deploy site/ --project-name=ai-247`, then a curl of `https://ai-247.pages.dev/`. |

**`studio/` (Puddle Park, PRs #40-#44) is never deployed by `deploy.yml`.** Its two Workers, `puddle-live` (`studio/cloudflare/puddle-live/`, this repo's `worker/src` with `PREFIX=puddle/`) and `puddle-showrunner` (`studio/cloudflare/showrunner-link/`), deploy only through `.github/workflows/deploy-puddle.yml`, on pushes to `main` under `studio/cloudflare/` or by hand, and only when the repository variable `PUDDLE_DEPLOY_ENABLED` is `true` (unset by default: a no-op). Both bind the shared bucket `ai247-media`; ai-247 owns `bulletins/` and `pool/` at its root, Puddle Park owns `puddle/`. `tests/test_deploy_guard.py` (run by `ci.yml` on every PR) fails if any other workflow mentions `studio/`, if either deploy workflow's triggers, gates or working directories change, if the Puddle configs leave `ai247-media` or `puddle/`, or if `worker/wrangler.toml` stops being the `ai247-live` Worker.

The Pages project `ai-247` was created by direct upload and is **not Git-connected**, so this workflow is the only thing that updates the site after a merge. Both jobs run under one concurrency group (`deploy-production`), so deploys queue instead of overlapping. The workflow can also be run by hand (Actions -> deploy -> Run workflow, choose `all`, `worker` or `site`).

The smoke test fails the job if `/healthz` is not ok (plain `ok` or JSON `"ok": true`, see `docs/FAILOVER.md`), `/live.m3u8` does not start with `#EXTM3U`, the CORS header is missing, the first segment is not a 200 with a `video/*` content type, or `EXT-X-MEDIA-SEQUENCE` does not rise within ~25 s. Note that `/live.m3u8` is a 503 until `manifest.json` exists in the R2 bucket (see `docs/DAY2.md`), so the first Worker deploy fails the smoke step until the bucket is seeded; the Worker is deployed by then regardless.

## Required secrets (repository secrets, names only)

- `CLOUDFLARE_API_TOKEN` (Workers Scripts: Edit, Cloudflare Pages: Edit, Account Settings: Read, **and Account -> D1 -> Edit** for the episode-history database `ai247-history`, see `docs/TOPICS.md` "Persistence"; without D1: Edit the deploy warns and deploys the Worker without the history binding, and the day1 job falls back to the R2 history mirror). The first run (42211838846) failed `pages deploy` with `Authentication error [code: 10000]` on `/accounts/<id>/pages/projects/ai-247`: the current token lacks the Pages: Edit permission (or the project lives in another account). Fix the token, then re-run the workflow.
- `CLOUDFLARE_ACCOUNT_ID`

If either is missing the deploy jobs print a warning and exit successfully (no-op), so merging never breaks `main`. Add the secrets and re-run the workflow.

Optional repository variable: `WORKER_URL` (the Worker base URL) used by the smoke test if wrangler does not print a deployment URL.

## Worker URL -> site

`deploy-worker` logs the Worker URL (`https://ai247-live.<account-subdomain>.workers.dev`). Put `<that url>/live.m3u8` in `site/config.json` as `streamUrl` and merge; that merge redeploys the site. `streamUrl` empty means the page shows the offline fallback.

## Rollback

Re-run the `deploy` workflow of an older good commit: Actions -> deploy -> pick that commit's run -> "Re-run all jobs" (it redeploys exactly that commit's `worker/` and `site/`). Or run the workflow by hand on `main` after reverting the bad commit with a PR. Cloudflare also keeps previous Worker versions (dashboard -> Workers -> `ai247-live` -> Deployments -> Rollback) and previous Pages deployments (`ai-247` -> Deployments -> Rollback).

## Still manual

- Creating the API token and the two secrets (done once by Trevor).
- The R2 bucket `ai247-media` and its `manifest.json` / segments (the uploader, see `docs/DAY2.md`); the Worker only reads them.
- Custom domain / route for the Worker and the Pages site, and converting `ai-247` to a Git-connected Pages project if ever wanted (a direct-upload project cannot be converted; it would need a new project name and this workflow updated).
- The fixed `EPOCH` in `worker/wrangler.toml` (the fallback live clock origin): changing it shifts the live edge for every viewer, so it is edited deliberately, never by CI.
- Setting `streamUrl` in `site/config.json` once the Worker URL is known.
