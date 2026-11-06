# Manifest swap continuity (Worker <-> uploader contract)

Problem: the Worker plays global segment `k` as `cycle[k % N]`. Replacing `manifest.json` (hourly) changes `N`/contents, so the segment behind a media-sequence number changes mid-stream and the discontinuity count jumps. Fix: **a new manifest takes effect only at a point the uploader chose** (a loop boundary of the old one, or, with `loop_from`, the end of its fresh footage, see "Fresh footage first"), and carries enough state for the Worker to keep sequence numbers monotonic. Implemented in `worker/src/playlist.js` (Python port `newsbot/channel.py`, checked against the same vectors), tested in `worker/test/unit/swap.test.js` (hourly-swap simulations, validated with `hls-parser`) and `tests/test_publish.py`.

## Fields (all top-level in `manifest.json`)

| Field | Type | Meaning |
|---|---|---|
| `epoch` | int, unix s | Channel clock origin. **Set once, never changes**: `k = floor((now - epoch) / segment_seconds)`. |
| `segment_seconds` | number | Constant forever (6). |
| `blocks` / `segments` | as before | One loop `cycle` (N segments, flattened across blocks). Unchanged shape. |
| `cycle_start_k` | int >= 0 | Global segment number at which `cycle[0]` plays. Segment `k >= cycle_start_k` plays `cycle[(k - cycle_start_k) mod N]`. Default 0. First manifest ever: 0. |
| `cycle_start_dseq` | int >= 0 | Value `EXT-X-DISCONTINUITY-SEQUENCE` has at `cycle_start_k` (number of discontinuity-tagged segments with number < `cycle_start_k`). First manifest: 0. |
| `prev` | object, optional | The manifest that was live before this one, same shape (needs its own `cycle_start_k`, `cycle_start_dseq`, `blocks`; **no** `prev` inside it). The Worker plays `prev` for `k < cycle_start_k`. |
| `loop_from` | int >= 0, optional | Index (among the non-empty blocks) of the first block of the fallback loop. Blocks before it play **once** from `cycle_start_k`; blocks from it on loop afterwards. Default 0 = the whole cycle loops (Day 1 and pool manifests). The loop region may not be empty. |

Discontinuity tags (Worker-computed): every block start, the loop wrap (the start of block `loop_from`), and `cycle_start_k` itself (it is cycle[0], a block start). Never on `k = 0`.

## Fresh footage first (`loop_from`, hourly cadence)

Trevor's rule: the channel never repeats old footage because the new footage is too short. With `loop_from = F`, local offset `c = k - cycle_start_k` plays `cycle[c]` for `0 <= c < N` (the F fresh bulletins in order, then the loop region's first pass) and `cycle[L + (c - N) mod (N - L)]` after that (`L` = first local index of block `F`): slate + replays loop only once the fresh footage is exhausted. `indexAt`/`tagsUpTo` in `playlist.js` (`index_at`/`_tags_up_to` in `channel.py`) implement the mapping and the tag count under it; with `L = 0` both are exactly the old modulo arithmetic.

The hourly uploader (`newsbot/publish.py publish_many`, workflow `hourly-bulletins`) publishes blocks `[fresh bulletins of this run in slice order, slate, up to 6 replays = the previous hour's bulletins, newest first]` with `loop_from = number of fresh blocks`. A `day1-episode` dispatch publishes `[bulletin, slate, replays]` with `loop_from 1`.

## Uploader rule (each publish, after all `.ts` objects are uploaded; `manifest.json` last, one atomic PUT)

1. Read the currently published `cur = manifest.json` from R2 (none -> first manifest: `cycle_start_k=0`, `cycle_start_dseq=0`, `epoch` = fixed constant, no `prev`).
2. `K = floor((now - epoch) / segment_seconds)` (live segment now).
3. `want = K + MARGIN`, `MARGIN >= 10` segments (60 s: covers the 10 s Worker cache, R2 propagation, the 5-segment client window).
4. If `cur.cycle_start_k > want` (cur has not started yet): new `cycle_start_k = cur.cycle_start_k`, `prev = cur.prev`, `cycle_start_dseq = cur.cycle_start_dseq` (replace the pending manifest). The hourly uploader then puts cur's fresh blocks **in front of** its own fresh blocks (`loop_from` counts both), so fresh footage that has not aired is never dropped.
   Else if cur has no `loop_from` (whole-cycle loop): `cycle_start_k = cur.cycle_start_k + N_cur * ceil((want - cur.cycle_start_k) / N_cur)` (next loop boundary of cur, `N_cur` = segment count of `cur`'s cycle), `prev = cur` without its own `prev`.
   Else (cur has fresh blocks, `L_cur` = first local index of its loop region): `cycle_start_k = cur.cycle_start_k + L_cur` if `want` is still before that (cur's fresh footage finishes, nothing fresh is cut), otherwise `cycle_start_k = want` (cur is looping replays: take over right away; the swap point is tagged like any block start). `prev = cur` without its own `prev`.
5. `cycle_start_dseq` = tagged segments with number < `cycle_start_k` under cur. Tags per cycle `T` = number of non-empty blocks (each block start is tagged; the wrap is block 0). Reference: `swapDseq(cur, start)` in `worker/src/playlist.js`. Closed form when cur has started: `cur.cycle_start_dseq + (full loops since cur start) * T + tagged-in-partial-loop`, counting `cycle_start_k` itself as tagged, `k=0` never.
6. Keep every `.ts` referenced by `cur`/`prev` in R2 until `prev` is dropped (the next publish after `cycle_start_k` has passed), plus >= 1 hour so cached playlists still resolve. Never overwrite a key whose content changed: use fresh block ids per episode.
7. Write `manifest.json` **last and atomically** (single PutObject; the object is replaced whole), after segments are uploaded.

Worker reference implementations: `nextSwapStart(cur, K, margin)` and `swapDseq(cur, start)`. The Python port (`newsbot/channel.py`) gives identical results: `tests/test_publish.py` checks the legacy vectors (e.g. `cur` = 10-segment single block, `cycle_start_k=100`, `K=103`, margin 10 -> start 120) and `worker/test/fixtures/swap-v3-golden.json`, generated from the JS for two chained `loop_from` manifests (swap starts, dseq anchors and an 80-segment timeline of uri / tag / discontinuity sequence).

## Guarantees (tested)

- `EXT-X-MEDIA-SEQUENCE` and `EXT-X-DISCONTINUITY-SEQUENCE` never decrease across hourly swaps with changing N and block layout.
- A segment number, once listed, never changes URI on later reloads.
- The old cycle finishes (last segment of old cycle is `cycle_start_k - 1`) for whole-cycle manifests; with `loop_from`, the old fresh region finishes and only the replay loop can be cut. The first new segment is tagged `EXT-X-DISCONTINUITY`.
- With `loop_from`: every fresh segment of every on-time hourly manifest airs exactly once, in order, and the slate/replays never air while fresh footage is pending; a late publish fills the gap with slate + the previous hour's bulletins and takes over at `k + margin` (`swap.test.js`, "hourly runs of 6 fresh bulletins").
- Manifests without the new fields behave exactly as before (back-compat; `loop_from` absent or 0 = old modulo mapping, same tag counts).

## Limits

- A Worker isolate holding a stale manifest cache longer than `MARGIN` segments would play the old cycle past the boundary; the 10 s TTL makes this safe with margin >= 10.
- If the uploader publishes twice before the first has started, the second replaces the first (step 4); the hourly uploader inherits the first one's fresh blocks so they still air.
- A Worker deployed before this change ignores `loop_from` and loops fresh + replays together (degraded, still valid HLS); `deploy.yml` redeploys the Worker on merge, before the first hourly publish.
- Segment durations are assumed uniform (`segment_seconds`).
