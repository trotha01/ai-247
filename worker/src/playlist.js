// Pure playlist logic (no Workers APIs) so it is unit-testable in plain Node.
// JS port of newsbot/playlist.py channel_playlist (Day 1), which is the tested reference.

export const DEFAULT_WINDOW = 5;

/** Normalise a manifest into blocks. Accepts the Day 0 shape ({segments:[{file,duration}]}) or a pool shape
 * ({blocks:[{id,segments:[{uri|file,duration}]}]}). Each block is encoded together, so every block start
 * (including the wrap back to block 0) is a timestamp reset => EXT-X-DISCONTINUITY.
 *
 * `loop_from` (optional, docs/MANIFEST-SWAP.md "Fresh footage first"): index, among the non-empty blocks, of the
 * first block of the fallback loop. The blocks before it (fresh bulletins) play exactly once from `cycle_start_k`;
 * then the blocks from `loop_from` on loop until a newer manifest takes over. `loopAt` is that block's first local
 * segment index. Default 0: the whole cycle loops (the Day 1 / pool behaviour). The loop region may not be empty. */
export function layout(manifest) {
  const blocks = manifest.blocks ?? [{ id: "main", segments: manifest.segments }];
  const segs = [];
  const starts = new Set();
  const blockStarts = [];
  for (const b of blocks) {
    if (!b.segments?.length) continue;
    starts.add(segs.length);
    blockStarts.push(segs.length);
    for (const s of b.segments) segs.push({ uri: s.uri ?? s.file, duration: Number(s.duration) });
  }
  if (!segs.length) throw new Error("manifest has no segments");
  for (const s of segs) if (!(s.duration > 0)) throw new Error("bad segment duration");
  const loopFrom = manifest.loop_from === undefined ? 0 : Number(manifest.loop_from);
  if (!Number.isInteger(loopFrom) || loopFrom < 0 || loopFrom >= blockStarts.length) throw new Error("bad loop_from (nothing left to loop)");
  return { segs, starts, loopAt: blockStarts[loopFrom] };
}

/** Count of discontinuity-tagged segments with global index < first (segment 0 is never tagged). Whole-cycle loop
 * (pool manifests, loop_from 0). */
export function tagsBefore(first, n, starts) {
  if (first <= 0) return 0;
  const full = Math.floor(first / n);
  const r = first % n;
  let count = full * starts.size;
  for (const b of starts) if (b < r) count++;
  return count - (starts.has(0) ? 1 : 0);
}

/** Local segment index played at offset c = k - cycle_start_k. [0, n) plays the cycle once in order (fresh blocks
 * first), then the loop region [loopAt, n) repeats. Negative c (only an unanchored oldest era, before its start)
 * extends the whole cycle backwards, phase kept, as before. loopAt 0 is exactly the old `c mod n`. */
export function indexAt(c, n, loopAt = 0) {
  if (c < 0) return ((c % n) + n) % n;
  if (c < n) return c;
  const m = n - loopAt;
  return loopAt + ((c - n) % m);
}

/** Tagged (EXT-X-DISCONTINUITY) local positions in [0, c) under indexAt's mapping (block starts; the loop wrap is
 * the start of block `loop_from`, which is in `starts`). Same numbers as before for loopAt 0. */
export function tagsUpTo(c, n, starts, loopAt = 0) {
  if (c < 0) return Math.floor(c / n) * starts.size + [...starts].filter((b) => b < c % n).length; // legacy arithmetic (truncated %)
  if (c <= n) return [...starts].filter((b) => b < c).length;
  const m = n - loopAt;
  const tail = [...starts].filter((b) => b >= loopAt);
  const q = Math.floor((c - n) / m), r = (c - n) % m;
  return starts.size + q * tail.length + tail.filter((b) => b - loopAt < r).length;
}

/** Global live-edge segment number for wall-clock `nowMs`. The clock only ever moves it forward. */
export function liveEdge(nowMs, epochMs, segSeconds) {
  return Math.max(0, Math.floor((nowMs - epochMs) / 1000 / segSeconds));
}

export function manifestSegSeconds(manifest) {
  return Number(manifest.segment_seconds ?? 6);
}

// ---- Manifest swaps (see docs/MANIFEST-SWAP.md) -------------------------------------------------------------
// A manifest may carry `cycle_start_k` (global segment number at which its cycle[0] plays; default 0) and `prev`
// (the manifest that was live before it, same shape). Segment k plays indexAt(k - cycle_start_k) of the newest
// manifest whose cycle_start_k <= k, so a swap only takes effect at the point the uploader chose.

/** Flatten manifest -> prev -> ... into eras sorted by start. The oldest era is extended backwards (phase kept). */
export function eras(manifest) {
  const chain = [];
  for (let m = manifest; m; m = m.prev) chain.unshift(m);
  const out = chain.map((m, i) => {
    const { segs, starts, loopAt } = layout(m);
    const start = Number(m.cycle_start_k ?? 0);
    if (!Number.isInteger(start) || start < 0) throw new Error("bad cycle_start_k");
    const anchor = m.cycle_start_dseq;
    if (anchor !== undefined && !(Number.isInteger(anchor) && anchor >= 0)) throw new Error("bad cycle_start_dseq");
    return { start, segs, starts, n: segs.length, anchor, loopAt };
  });
  for (let i = 1; i < out.length; i++) if (out[i].start <= out[i - 1].start) throw new Error("cycle_start_k must increase along prev chain");
  // base = DISCONTINUITY-SEQUENCE at max(start,1): the manifest's anchor, else derived from the older era / zero.
  out.forEach((e, i) => {
    if (e.anchor !== undefined) e.base = e.anchor;
    else if (i === 0) e.base = taggedIn(e, 1, e.start); // unanchored oldest era: history counted from k=0 (phase-extended backwards)
    else {
      const p = out[i - 1];
      e.base = p.base + taggedIn(p, Math.max(p.start, 1), e.start);
    }
  });
  return out;
}

export const eraFor = (es, k) => { let e = es[0]; for (const x of es) if (x.start <= k) e = x; return e; };

const taggedIn = (e, lo, hi) => (hi > lo ? tagsUpTo(hi - e.start, e.n, e.starts, e.loopAt) - tagsUpTo(lo - e.start, e.n, e.starts, e.loopAt) : 0);

/** The segment era `e` plays at global number k, with its EXT-X-DISCONTINUITY flag (block starts; never k = 0). */
export function eraSegment(e, k) {
  const idx = indexAt(k - e.start, e.n, e.loopAt);
  const s = e.segs[idx];
  return { uri: s.uri, duration: s.duration, tag: k > 0 && e.starts.has(idx) };
}

/** EXT-X-DISCONTINUITY-SEQUENCE for a window starting at `first`: tagged segments with number < first
 * (k=0 is never tagged). Uses the era's cycle_start_dseq anchor, so history older than `prev` is not needed. */
export function tagsBeforeEras(first, es) {
  if (first <= 0) return 0;
  const e = eraFor(es, first);
  if (first < e.start) return 0; // only the oldest era, only before its start: the first manifest should use cycle_start_k 0
  return e.base + taggedIn(e, Math.max(e.start, 1), first);
}

export function rollingPlaylist(manifest, live, { window = DEFAULT_WINDOW, baseUrl = "" } = {}) {
  const es = eras(manifest);
  const first = Math.max(0, live - window + 1);
  const target = Math.ceil(Math.max(...es.flatMap((e) => e.segs.map((s) => s.duration))));
  const out = [
    "#EXTM3U",
    "#EXT-X-VERSION:3",
    `#EXT-X-TARGETDURATION:${target}`,
    `#EXT-X-MEDIA-SEQUENCE:${first}`,
    `#EXT-X-DISCONTINUITY-SEQUENCE:${tagsBeforeEras(first, es)}`,
  ];
  for (let k = first; k <= live; k++) {
    const s = eraSegment(eraFor(es, k), k);
    if (s.tag) out.push("#EXT-X-DISCONTINUITY");
    out.push(`#EXTINF:${s.duration.toFixed(3)},`, `${baseUrl}${s.uri}`);
  }
  return out.join("\n") + "\n";
}

/** Reference for the uploader rule: the `cycle_start_k` a new manifest must carry, given the manifest currently
 * published (`cur`, may be null) and the live segment number at publish time. `margin` segments of lead cover the
 * Worker's 10 s manifest cache, R2 propagation and the 5-segment client window.
 *  - cur has not started yet: keep its start (the pending manifest is replaced).
 *  - cur loops its whole cycle (no loop_from): the next loop boundary, so no loop is cut.
 *  - cur has fresh blocks (loop_from > 0): never cut footage that has not aired; the swap lands at the end of cur's
 *    fresh region if that is still ahead, otherwise right away (k + margin, inside cur's replay loop, tagged). */
export function nextSwapStart(cur, publishK, margin = 10) {
  if (!cur) return publishK + margin; // first ever manifest: any k works, nothing to be continuous with
  const es = eras(cur);
  const e = es.at(-1);
  const want = publishK + margin;
  if (e.start > want) return e.start; // current manifest has not started yet: replace it at its own boundary
  if (e.loopAt === 0) return e.start + e.n * Math.ceil((want - e.start) / e.n);
  const freshEnd = e.start + e.loopAt;
  return want < freshEnd ? freshEnd : want;
}

/** Reference for `cycle_start_dseq` of a new manifest starting at `start` after `cur`. */
export function swapDseq(cur, start) {
  return tagsBeforeEras(start, eras(cur));
}
