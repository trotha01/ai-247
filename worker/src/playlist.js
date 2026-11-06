// Pure playlist logic (no Workers APIs) so it is unit-testable in plain Node.
// JS port of newsbot/playlist.py channel_playlist (Day 1), which is the tested reference.

export const DEFAULT_WINDOW = 5;

/** Normalise a manifest into blocks. Accepts the Day 0 shape ({segments:[{file,duration}]}) or a pool shape
 * ({blocks:[{id,segments:[{uri|file,duration}]}]}). Each block is encoded together, so every block start
 * (including the wrap back to block 0) is a timestamp reset => EXT-X-DISCONTINUITY. */
export function layout(manifest) {
  const blocks = manifest.blocks ?? [{ id: "main", segments: manifest.segments }];
  const segs = [];
  const starts = new Set();
  for (const b of blocks) {
    if (!b.segments?.length) continue;
    starts.add(segs.length);
    for (const s of b.segments) segs.push({ uri: s.uri ?? s.file, duration: Number(s.duration) });
  }
  if (!segs.length) throw new Error("manifest has no segments");
  for (const s of segs) if (!(s.duration > 0)) throw new Error("bad segment duration");
  return { segs, starts };
}

/** Count of discontinuity-tagged segments with global index < first (segment 0 is never tagged). */
export function tagsBefore(first, n, starts) {
  if (first <= 0) return 0;
  const full = Math.floor(first / n);
  const r = first % n;
  let count = full * starts.size;
  for (const b of starts) if (b < r) count++;
  return count - (starts.has(0) ? 1 : 0);
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
// (the manifest that was live before it, same shape). Segment k plays cycle[(k - cycle_start_k) mod N] of the
// newest manifest whose cycle_start_k <= k, so a swap only takes effect at the loop boundary the uploader chose.

/** Flatten manifest -> prev -> ... into eras sorted by start. The oldest era is extended backwards (phase kept). */
export function eras(manifest) {
  const chain = [];
  for (let m = manifest; m; m = m.prev) chain.unshift(m);
  const out = chain.map((m, i) => {
    const { segs, starts } = layout(m);
    const start = Number(m.cycle_start_k ?? 0);
    if (!Number.isInteger(start) || start < 0) throw new Error("bad cycle_start_k");
    const anchor = m.cycle_start_dseq;
    if (anchor !== undefined && !(Number.isInteger(anchor) && anchor >= 0)) throw new Error("bad cycle_start_dseq");
    return { start, segs, starts, n: segs.length, anchor };
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

const eraFor = (es, k) => { let e = es[0]; for (const x of es) if (x.start <= k) e = x; return e; };

/** Tagged (EXT-X-DISCONTINUITY) local-index count in [0, c). */
const tagsUpTo = (c, n, starts) => Math.floor(c / n) * starts.size + [...starts].filter((b) => b < c % n).length;

const taggedIn = (e, lo, hi) => (hi > lo ? tagsUpTo(hi - e.start, e.n, e.starts) - tagsUpTo(lo - e.start, e.n, e.starts) : 0);

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
    const e = eraFor(es, k);
    const idx = (((k - e.start) % e.n) + e.n) % e.n;
    const s = e.segs[idx];
    if (k > 0 && e.starts.has(idx)) out.push("#EXT-X-DISCONTINUITY");
    out.push(`#EXTINF:${s.duration.toFixed(3)},`, `${baseUrl}${s.uri}`);
  }
  return out.join("\n") + "\n";
}

/** Reference for the uploader rule: the `cycle_start_k` a new manifest must carry, given the manifest currently
 * published (`cur`, may be null) and the live segment number at publish time. `margin` segments of lead cover the
 * Worker's 10 s manifest cache, R2 propagation and the 5-segment client window. */
export function nextSwapStart(cur, publishK, margin = 10) {
  if (!cur) return publishK + margin; // first ever manifest: any k works, nothing to be continuous with
  const es = eras(cur);
  const e = es.at(-1);
  const want = publishK + margin;
  if (e.start > want) return e.start; // current manifest has not started yet: replace it at its own boundary
  return e.start + e.n * Math.ceil((want - e.start) / e.n);
}

/** Reference for `cycle_start_dseq` of a new manifest starting at `start` after `cur`. */
export function swapDseq(cur, start) {
  return tagsBeforeEras(start, eras(cur));
}
