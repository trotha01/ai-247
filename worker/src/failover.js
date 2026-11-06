// Replay-pool failover: pure logic (no Workers APIs), unit-tested with hls-parser in test/unit/failover.test.js.
// See docs/FAILOVER.md. Builds on the manifest-swap primitives in playlist.js (eras / tagsBeforeEras / layout).
//
// The Worker serves a "view": the live manifest chain (as published by the uploader) plus, during a failover, a
// window of global segment numbers [k0, r) that is served from the replay pool instead:
//   k <  k0      -> whatever was served before the failover (frozen snapshot `pre`), so listed numbers never change
//   k0 <= k < r  -> pool cycle, pool[0] at k0 (k0 is a block start => EXT-X-DISCONTINUITY at the switch)
//   k >= r       -> live chain again, in its own phase (idx = (k - cycle_start_k) mod N), forced tag at r
// MEDIA-SEQUENCE is always the clock-derived k of the first listed segment, so it is monotonic by construction.
// DISCONTINUITY-SEQUENCE is the count of tagged segments before the window under this composed mapping; after a
// return completes it collapses into a constant `offset` added to the live chain's own count forever.

import { eras, layout, tagsBefore, tagsBeforeEras } from "./playlist.js";

export const SOURCE = { LIVE: "live-manifest", POOL: "replay-pool", CACHED: "live-manifest-cached", NONE: "none" };

/** Fresh isolate: nothing served yet. chain = live manifest last served, offset = DISCONTINUITY-SEQUENCE correction
 * accumulated by completed failovers, fo = active or returning failover (null when none). */
export function initialState() {
  return { chain: null, offset: 0, fo: null };
}

const erasMemo = new WeakMap();
function erasOf(manifest) {
  let es = erasMemo.get(manifest);
  if (!es) { es = eras(manifest); erasMemo.set(manifest, es); }
  return es;
}
const layoutMemo = new WeakMap();
export function poolLayout(pool) {
  let L = layoutMemo.get(pool);
  if (!L) { const { segs, starts } = layout(pool); L = { segs, starts, n: segs.length }; layoutMemo.set(pool, L); }
  return L;
}

const eraFor = (es, k) => { let e = es[0]; for (const x of es) if (x.start <= k) e = x; return e; };

/** Segment the live chain plays at k, same rule as rollingPlaylist (tag at block starts, never at k=0). */
export function liveAt(manifest, k) {
  const es = erasOf(manifest);
  const e = eraFor(es, k);
  const idx = (((k - e.start) % e.n) + e.n) % e.n;
  const s = e.segs[idx];
  return { uri: s.uri, duration: s.duration, tag: k > 0 && e.starts.has(idx) };
}

/** Tagged pool segments with number in [k0, hi) when pool[0] plays at k0 (k=0 never tagged). */
export function poolTagsIn(P, k0, hi) {
  const c = hi - k0;
  if (c <= 0) return 0;
  return k0 > 0 ? tagsBefore(c, P.n, P.starts) + 1 : tagsBefore(c, P.n, P.starts);
}

function poolAt(fo, k) {
  const P = poolLayout(fo.pool);
  const idx = (((k - fo.k0) % P.n) + P.n) % P.n;
  const s = P.segs[idx];
  return { uri: s.uri, duration: s.duration, tag: k > 0 && P.starts.has(idx) };
}

/** What the composed view serves at global segment number k. */
export function segAt(view, k) {
  const fo = view.fo;
  if (!fo) return liveAt(view.chain, k);
  if (k < fo.k0) return segAt(fo.pre, k); // pre is never null when k0 > 0
  if (fo.r === null || k < fo.r) return poolAt(fo, k);
  const s = liveAt(view.chain, k);
  if (k === fo.r) s.tag = true; // the return is a timestamp reset whatever the live block layout says
  return s;
}

/** EXT-X-DISCONTINUITY-SEQUENCE for a window whose first segment is `first`: tagged numbers < first. */
export function dseqAt(view, first) {
  if (first <= 0) return 0;
  const fo = view.fo;
  if (!fo) return tagsBeforeEras(first, erasOf(view.chain)) + view.offset;
  if (first < fo.k0) return dseqAt(fo.pre, first);
  const P = poolLayout(fo.pool);
  if (fo.r === null || first <= fo.r) return fo.dseqAtK0 + poolTagsIn(P, fo.k0, first);
  const es = erasOf(view.chain);
  const forced = liveAt(view.chain, fo.r).tag ? 0 : 1;
  return fo.dseqAtK0 + poolTagsIn(P, fo.k0, fo.r) + forced + tagsBeforeEras(first, es) - tagsBeforeEras(fo.r, es);
}

function maxDuration(view) {
  let m = 0;
  if (view.chain) for (const e of erasOf(view.chain)) for (const s of e.segs) m = Math.max(m, s.duration);
  for (let fo = view.fo; fo; fo = fo.pre?.fo ?? null) for (const s of poolLayout(fo.pool).segs) m = Math.max(m, s.duration);
  return m;
}

/** True when the view can serve something (a live chain or an active pool failover). */
export const canServe = (view) => Boolean(view.chain || view.fo);

/** Rolling playlist of the composed view. With no failover and offset 0 it is byte-identical to rollingPlaylist. */
export function composedPlaylist(view, live, { window = 5, baseUrl = "" } = {}) {
  const first = Math.max(0, live - window + 1);
  const out = [
    "#EXTM3U",
    "#EXT-X-VERSION:3",
    `#EXT-X-TARGETDURATION:${Math.ceil(maxDuration(view))}`,
    `#EXT-X-MEDIA-SEQUENCE:${first}`,
    `#EXT-X-DISCONTINUITY-SEQUENCE:${dseqAt(view, first)}`,
  ];
  for (let k = first; k <= live; k++) {
    const s = segAt(view, k);
    if (s.tag) out.push("#EXT-X-DISCONTINUITY");
    out.push(`#EXTINF:${s.duration.toFixed(3)},`, `${baseUrl}${s.uri}`);
  }
  return out.join("\n") + "\n";
}

/** Which source the view serves at live edge k. */
export function sourceOf(view, liveOk, k) {
  const fo = view.fo;
  if (fo && (fo.r === null || k < fo.r)) return SOURCE.POOL;
  if (liveOk) return SOURCE.LIVE;
  if (view.chain) return SOURCE.CACHED;
  return SOURCE.NONE;
}

/** One decision step. Pure: returns the next view (never mutates `view`).
 * input.live = { manifest, ok, problem }; input.pool = pool manifest or null (must pass layout() if non-null);
 * input.k = live edge; input.nowMs = wall clock; input.minPoolMs = minimum time to stay on the pool (hysteresis). */
export function step(view, { k, nowMs, window = 5, live, pool, minPoolMs = 0 }) {
  let v = { ...view };
  if (live.ok) v.chain = live.manifest;
  const first = Math.max(0, k - window + 1);

  // A return is complete once the window no longer lists r: fold the failover into a constant offset.
  if (v.fo && v.fo.r !== null && first > v.fo.r) {
    const fo = v.fo, es = erasOf(v.chain);
    const forced = liveAt(v.chain, fo.r).tag ? 0 : 1;
    v.offset = fo.dseqAtK0 + poolTagsIn(poolLayout(fo.pool), fo.k0, fo.r) + forced - tagsBeforeEras(fo.r, es);
    v.fo = null;
  }

  const onPool = v.fo && v.fo.r === null;
  if (!onPool && !live.ok && pool) {
    // Enter failover. k0 = k + 1 is the first number no client has been shown yet, so nothing listed changes URI.
    // A cold isolate with no history plays the pool from k = 0: deterministic across isolates, no synthetic switch.
    const pre = canServe(v) ? { chain: v.chain, offset: v.offset, fo: v.fo } : null;
    const k0 = pre ? k + 1 : 0;
    v.fo = { k0, reason: live.problem, since: nowMs, pre, dseqAtK0: pre ? dseqAt(pre, k0) : 0, pool, r: null };
  } else if (onPool && live.ok && nowMs - v.fo.since >= minPoolMs) {
    v.fo = { ...v.fo, r: k + 1 }; // return at the first number not yet listed, tagged
  }
  return v;
}

/** Health summary of the failover state (no secrets, no R2 access). */
export function describe(view, k) {
  const fo = view.fo;
  return {
    dseq_offset: view.offset,
    failover: fo ? { since: new Date(fo.since).toISOString(), since_k: fo.k0, reason: fo.reason, return_k: fo.r, returning: fo.r !== null && k >= fo.r } : null,
  };
}
