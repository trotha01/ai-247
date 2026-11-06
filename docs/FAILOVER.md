# Replay-pool failover (no alerts, no external services)

The channel must never be empty. Two parts:

1. **Bootstrap and refresh** (`newsbot/replay_pool.py`, workflow `replay-pool`: manual plus a daily cron, see "Schedule and refresh guard"): publishes `pool/manifest.json` in R2, a loop of the newest good episodes (or the Day 0 bulletin).
2. **Worker** (`worker/src/failover.js` pure logic, `worker/src/channel.js` R2 side; `index.js` only delegates): serves the pool whenever `manifest.json` is unusable, and switches back when it is good again, keeping the HLS playlist valid throughout. `/healthz` says which source is on air and how old the manifest is, so Trevor can check by eye. Nothing notifies anyone.

## When the Worker falls back

Checked on every manifest reload (cache 10 s, `MANIFEST_TTL_MS`), in this order; the first problem is the reason shown in `/healthz`:

| Reason | Condition |
|---|---|
| `missing` | `{PREFIX}manifest.json` is not in the bucket |
| `invalid` | not JSON |
| `empty` | no segments, a segment with duration <= 0, or a bad `cycle_start_k`/`prev` chain (what `layout()`/`eras()` reject) |
| `stale` | `MAX_MANIFEST_AGE_S > 0` and R2's upload time of `manifest.json` is older than that. Deployed value `14400` (4 h): the 3-hourly `day1-episode` cron (`23 */3`, up to 35 min) normally republishes within ~3.6 h, so one missed or failed run switches the channel to the pool until the next publish lands. `0` turns the rule off (a looping manifest is still valid content); `/healthz` reports `manifest.age_s` either way. |
| `missing-segment` | one of the next `CHECK_SEGMENTS` (default 5) segments the live mapping would list is not in R2 (HEAD). Checked before any client is sent that URI. |

If the live manifest is unusable and the pool is unusable too, the Worker keeps serving the last good manifest from memory (`source: live-manifest-cached`); only with no history at all does `/live.m3u8` answer 503.

## How the switch stays valid (RFC 8216 6.2.1 / 6.2.2)

Global segment number `k` comes from the clock (`epoch`, `segment_seconds`), so `EXT-X-MEDIA-SEQUENCE` is monotonic by construction. The Worker serves a composed view:

- `k < k0`: what was served before the failover (frozen snapshot), so a number a client has seen never changes URI.
- `k0 <= k < r`: the pool, `pool[(k - k0) mod N]`. `k0 = (live edge at detection) + 1`, the first number no client has been shown yet, and it is `pool[0]`, a block start, so it carries `EXT-X-DISCONTINUITY`. Pool block starts and the pool wrap are tagged as usual.
- `k >= r`: the live manifest again **in its own phase** (`idx = (k - cycle_start_k) mod N`, exactly what it would have played with no failover), so the uploader's `cycle_start_k`/`prev` bookkeeping (`docs/MANIFEST-SWAP.md`) is untouched. `r = (live edge when the manifest is good again) + 1`, always tagged.
- `EXT-X-DISCONTINUITY-SEQUENCE` is the count of tagged numbers before the window under that composed mapping. Once the window has moved past `r` the failover collapses into a constant `dseq_offset` added to the live manifest's own count forever (visible in `/healthz`; may be negative because pool and episode have different tag densities, the served sequence itself only ever increases).
- A cold isolate that finds no manifest plays the pool from `k = 0` (`cycle_start_k` 0): deterministic across isolates, no synthetic switch.
- Hysteresis: `FAILOVER_MIN_S` (default 30) minimum time on the pool before returning, so a flapping manifest does not insert a tag every 10 s.

Tested in `worker/test/unit/failover.test.js` (hls-parser on every reload over simulated hours: media sequence and discontinuity sequence never decrease, per-segment discontinuity sequence equals the global tag count, URI and tag of a number never change, the switch and the return are tagged, pool content between them, in-phase live content after, hourly uploader swaps during an outage, cold start, flapping, nested re-entry) and in `worker/test/dev/failover-dev.test.js` (the real Worker under `wrangler dev --local`, deleting and re-putting R2 objects: manifest missing/back, segment missing/back, empty manifest, stale with `MAX_MANIFEST_AGE_S=2`, `/healthz` fields, `x-ai247-source` header).

## `/healthz`

Always HTTP 200 (liveness), JSON, `cache-control: no-store`:

```json
{
  "ok": true,
  "source": "live-manifest",            // or replay-pool | live-manifest-cached | none
  "reason": null,                       // while on the pool: missing: ... | empty: ... | stale: ... | missing-segment: ...
  "live_k": 123456,
  "manifest": {"key": "manifest.json", "ok": true, "problem": null, "age_s": 912, "uploaded": "2026-11-06T12:00:00.000Z",
               "segments": 118, "blocks": 3, "checked_segments": 5, "max_age_s": 0},
  "pool": {"key": "pool/manifest.json", "ok": true, "segments": 100, "blocks": 1, "built_at": "...", "built_from": {...}},
  "failover": null,                     // or {"since", "since_k", "reason", "return_k", "returning"}
  "dseq_offset": 0,
  "epoch_mismatch": null
}
```

`/live.m3u8` also carries `x-ai247-source: live-manifest | replay-pool` for a quick `curl -I`.

## Pool manifest (what the bootstrap writes)

Channel-manifest shape the Worker already reads, plus metadata:

```json
{"version": 2, "kind": "replay-pool", "segment_seconds": 6, "epoch": 1793000000,
 "built_at": "2026-11-06T12:00:00Z", "built_from": {"source": "r2", "manifest_keys": ["bulletins/20261106T120000Z/manifest.json"]},
 "blocks": [{"id": "pool-20261106T120000Z", "kind": "replay", "seconds": 600.0,
             "segments": [{"uri": "bulletins/20261106T120000Z/seg_000.ts", "file": "seg_000.ts", "duration": 6.0, "bytes": 123456, "sha256": "..."}, ...]}]}
```

`uri` is an R2 key relative to the Worker `PREFIX` (same rule as `docs/R2_LAYOUT.md` in PR #11). Key: `{PREFIX}pool/manifest.json` (`POOL_KEY`).

```
python -m newsbot.replay_pool --from-r2 --upload                      # newest complete bulletins/<ts>/ already in R2; nothing re-uploaded
python -m newsbot.replay_pool --from-r2 --max-blocks 2 --upload       # loop the two newest
python -m newsbot.replay_pool --from-dir out --id day0 --upload       # local render (Day 0 artifact): sha256-checked, uploaded under pool/day0/, manifest last
python -m newsbot.replay_pool --from-dir out --write pool.json        # no R2 secrets: writes the manifest locally, uploads nothing
```

`--from-r2` skips uploads whose segments are missing or whose sizes differ from the per-bulletin manifest (truncated uploads) and lists them in the report; it copies `epoch` from the live `manifest.json` when present so the pool and the live manifest share one clock. The workflow `replay-pool` runs the same command on a runner with the `R2_*` secrets; with `source=artifact` it downloads a `bulletin-day0`/`episode-day1` artifact and loops that.

### Schedule and refresh guard

`replay-pool` runs by hand (`workflow_dispatch`) and **daily at 04:41 UTC** (`schedule`, after the 03:23 `day1-episode` cron run has published), with `source=r2 max_blocks=2`: the pool loops the two newest complete episodes in R2. Stop the cron without a commit by setting the repo variable `REPLAY_POOL_CRON_ENABLED` to `false` (or `gh workflow disable replay-pool`). Nothing is ever deleted from R2 (`docs/R2_LAYOUT.md`), so the episodes an older pool points at stay playable; the refresh only keeps the loop recent.

The refresh (`--from-r2 --upload`) never replaces a good `pool/manifest.json` with a bad one (`refresh_decision` in `newsbot/replay_pool.py`):

- Every segment the new pool lists is HEAD-checked in R2 (existence and size) before the manifest is built; incomplete episodes are skipped.
- No complete episode at all: the run exits 3 and writes nothing (the existing pool stays).
- The new manifest would have nothing playable (no segments, or a duration <= 0): not uploaded, the existing pool stays. (`build_pool_manifest` refuses an empty pool anyway.)
- The newest episodes are exactly the ones the pool already lists: no PutObject (the run says `not uploading: unchanged`), so a daily run with no new episode does not touch R2. `--force` (workflow input `force`) rewrites it anyway.
- Fewer than `--min-segments` segments (the workflow passes 10: a Day 0 bulletin is 10, an episode 100): exit 3, R2 untouched.
- The existing pool is read back and every segment it references is HEAD-checked (`verify_pool`). If it still verifies and loops a *newer* episode than the candidate (the newest upload is truncated, so `--from-r2` fell back to an older one), it is kept (`--force` overrides). If it points at a missing or truncated object, it is replaced by whatever complete episode exists, even an older one.
- A missing or non-JSON pool manifest in R2 is replaced.
- A skipped run writes the pool that stays live to `--write`, so the job summary and the `replay-pool-manifest` artifact always show what the Worker serves.

### Verification (`scripts/pool_check.py`)

After the publish step the workflow runs `python scripts/pool_check.py --manifest pool-manifest.json --wait 150`: it HEADs `pool/manifest.json` in R2, re-verifies every referenced segment, checks that the R2 copy lists the same segment keys as the local manifest, then polls the live Worker's `/healthz` (URL from the repo variable `WORKER_URL`, else the host of `streamUrl` in `site/config.json`) until `pool.ok` is true with this run's `built_at` (the Worker's pool cache is 60 s). An unusable pool fails the job; a usable pool with another `built_at` (another isolate) is only a warning. The last `/healthz` body goes into the job summary and the artifact (`healthz.json`). Without the `R2_*` secrets the whole job is a warning and exit 0. The script also runs by hand with the `R2_*` env and `--url`.

Seeded on 2026-11-06 by run 42222599138 (`source=r2`, `max_blocks=2`, 51 s): `pool/manifest.json` = 2 blocks, 200 segments, built from `bulletins/20261106T120928Z/` and `bulletins/20261106T115430Z/`; `/healthz` on `ai247-live` went from `pool.problem: "missing: pool/manifest.json is not in the bucket"` to `pool.ok: true` while `source` stayed `live-manifest`.

Tests: `tests/test_replay_pool.py` (fake S3 client: hash checks, newest-complete selection, skip reasons, manifest-last upload order, CLI with and without secrets, the refresh guard above end to end on the CLI path, the Worker fixture `worker/test/fixtures/replay-pool.json` kept in this shape, and the generated channel playlist passing `newsbot.playlist.check_sequence_over_time`).

## Config (`worker/wrangler.toml` `[vars]`)

| Var | Default | Meaning |
|---|---|---|
| `POOL_KEY` | `pool/manifest.json` | pool manifest key under `PREFIX` |
| `MAX_MANIFEST_AGE_S` | `14400` | stale threshold in seconds (4 h: one missed 3-hourly `day1-episode` run plus slack); 0 = never stale |
| `CHECK_SEGMENTS` | `5` | upcoming live segments HEADed per manifest reload; 0 = off |
| `FAILOVER_MIN_S` | `30` | minimum time on the pool before returning |
| `MANIFEST_TTL_MS` / `POOL_TTL_MS` | `10000` / `60000` | caches (tests pass smaller values with `--var`) |

## Limits

- State is per Worker isolate (as the manifest-swap cache already is). Two isolates can pick different `k0`/`r` for the same outage; a client normally sticks to one colo. Persisting the decision in R2 (`failover.json`) would make all isolates agree and is the natural next step if that bites.
- The pool manifest is not HEAD-checked by the Worker (the bootstrap verifies before publishing). If the pool itself points at deleted objects, segments 404.
- A new `manifest.json` published *during* a failover is honoured on return (the return lands in the newest manifest's phase); its `cycle_start_dseq` anchor is still consistent because the Worker adds `dseq_offset` on top of the uploader's own count rather than rewriting it.
- `uploaded` comes from R2 (`R2Object.uploaded`); a manifest copied with a tool that preserves nothing but the bytes still gets a fresh upload time, which is the intended meaning of "stale".
- Nothing here contacts anything outside R2 (the Worker is deployed by `deploy.yml`, see `docs/DEPLOY.md`).
