# Manifest swap continuity (Worker <-> Day 1 uploader contract)

Problem: the Worker plays global segment `k` as `cycle[k % N]`. Replacing `manifest.json` (hourly) changes `N`/contents, so the segment behind a media-sequence number changes mid-stream and the discontinuity count jumps. Fix: **a new manifest takes effect only at a loop boundary of the old one**, and carries enough state for the Worker to keep sequence numbers monotonic. Implemented in `worker/src/playlist.js`, tested in `worker/test/unit/swap.test.js` (hourly-swap simulation, validated with `hls-parser`).

## Fields (all top-level in `manifest.json`)

| Field | Type | Meaning |
|---|---|---|
| `epoch` | int, unix s | Channel clock origin. **Set once, never changes**: `k = floor((now - epoch) / segment_seconds)`. |
| `segment_seconds` | number | Constant forever (6). |
| `blocks` / `segments` | as before | One loop `cycle` (N segments, flattened across blocks). Unchanged shape. |
| `cycle_start_k` | int >= 0 | Global segment number at which `cycle[0]` plays. Segment `k >= cycle_start_k` plays `cycle[(k - cycle_start_k) mod N]`. Default 0. First manifest ever: 0. |
| `cycle_start_dseq` | int >= 0 | Value `EXT-X-DISCONTINUITY-SEQUENCE` has at `cycle_start_k` (number of discontinuity-tagged segments with number < `cycle_start_k`). First manifest: 0. |
| `prev` | object, optional | The manifest that was live before this one, same shape (needs its own `cycle_start_k`, `cycle_start_dseq`, `blocks`; **no** `prev` inside it). The Worker plays `prev` for `k < cycle_start_k`. |

Discontinuity tags (Worker-computed): every block start, the loop wrap, and `cycle_start_k` itself (it is cycle[0], a block start). Never on `k = 0`.

## Uploader rule (each publish, after all `.ts` objects are uploaded; `manifest.json` last, one atomic PUT)

1. Read the currently published `cur = manifest.json` from R2 (none -> first manifest: `cycle_start_k=0`, `cycle_start_dseq=0`, `epoch` = fixed constant, no `prev`).
2. `K = floor((now - epoch) / segment_seconds)` (live segment now).
3. `want = K + MARGIN`, `MARGIN >= 10` segments (60 s: covers the 10 s Worker cache, R2 propagation, the 5-segment client window).
4. If `cur.cycle_start_k > want` (cur has not started yet): new `cycle_start_k = cur.cycle_start_k`, `prev = cur.prev`, `cycle_start_dseq = cur.cycle_start_dseq` (replace the pending manifest).
   Else: `cycle_start_k = cur.cycle_start_k + N_cur * ceil((want - cur.cycle_start_k) / N_cur)` (next loop boundary of cur, `N_cur` = segment count of `cur`'s cycle), `prev = cur` without its own `prev`.
5. `cycle_start_dseq` = tagged segments with number < `cycle_start_k` under cur. Tags per cycle `T` = number of non-empty blocks (each block start is tagged; the wrap is block 0). Reference: `swapDseq(cur, start)` in `worker/src/playlist.js`. Closed form when cur has started: `cur.cycle_start_dseq + (full loops since cur start) * T + tagged-in-partial-loop`, counting `cycle_start_k` itself as tagged, `k=0` never.
6. Keep every `.ts` referenced by `cur`/`prev` in R2 until `prev` is dropped (the next publish after `cycle_start_k` has passed), plus >= 1 hour so cached playlists still resolve. Never overwrite a key whose content changed: use fresh block ids per episode.
7. Write `manifest.json` **last and atomically** (single PutObject; the object is replaced whole), after segments are uploaded.

Worker reference implementations: `nextSwapStart(cur, K, margin)` and `swapDseq(cur, start)`. Python port must give identical results; add a test with a vector such as: `cur` = 10-segment single block, `cycle_start_k=100`, `K=103`, margin 10 -> start 120.

## Guarantees (tested)

- `EXT-X-MEDIA-SEQUENCE` and `EXT-X-DISCONTINUITY-SEQUENCE` never decrease across hourly swaps with changing N and block layout.
- A segment number, once listed, never changes URI on later reloads.
- The old cycle finishes (last segment of old cycle is `cycle_start_k - 1`); the first new segment is tagged `EXT-X-DISCONTINUITY`.
- Manifests without the new fields behave exactly as before (back-compat).

## Limits

- A Worker isolate holding a stale manifest cache longer than `MARGIN` segments would play the old cycle past the boundary; the 10 s TTL makes this safe with margin >= 10.
- If the uploader publishes twice before the first has started, the second replaces the first (step 4).
- Segment durations are assumed uniform (`segment_seconds`).
