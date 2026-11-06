import { describe, expect, it } from "vitest";
import HLS from "hls-parser";
import { rollingPlaylist, liveEdge, nextSwapStart, swapDseq, tagsBefore, layout } from "../../src/playlist.js";

// Hourly uploader simulation. Segment k plays at epoch + 6k. Each hour a new manifest (different N, different
// blocks) is published; it follows docs/MANIFEST-SWAP.md: cycle_start_k = next loop boundary, prev = live manifest.
const SEG = 6, EPOCH = 1_793_000_000, HOUR = 3600;
const block = (id, n) => ({ id, segments: Array.from({ length: n }, (_, i) => ({ uri: `${id}/seg_${String(i).padStart(3, "0")}.ts`, duration: SEG })) });
const strip = (m) => { const { prev, ...rest } = m; return rest; }; // prev.prev is always dropped (docs/MANIFEST-SWAP.md)

function publish(cur, nowS, id, sizes) {
  const k = liveEdge(nowS * 1000, EPOCH * 1000, SEG);
  const start = cur ? nextSwapStart(cur, k) : 0; // the very first manifest starts at 0
  // if cur has not started yet it is replaced; its own prev becomes ours
  const prev = cur ? (Number(cur.cycle_start_k ?? 0) > k ? cur.prev : strip({ ...cur, prev: undefined })) : undefined;
  const m = { version: 3, segment_seconds: SEG, epoch: EPOCH, cycle_start_k: start, cycle_start_dseq: cur ? swapDseq(cur, start) : 0, blocks: sizes.map((n, i) => block(`${id}-${i}`, n)) };
  if (prev) m.prev = prev;
  return m;
}

function simulate(hours, sizesFor, { reloadEvery = 3 } = {}) {
  let manifest = null, nextPub = 0, published = [];
  const seen = new Map(), log = [];
  let prevSeq = -1, prevDseq = -1;
  const total = hours * HOUR;
  for (let t = 0; t <= total; t += reloadEvery) {
    if (t >= nextPub) { manifest = publish(manifest, EPOCH + t, `h${published.length}`, sizesFor(published.length)); published.push(manifest); nextPub += HOUR; }
    const live = liveEdge((EPOCH + t) * 1000, EPOCH * 1000, SEG);
    const pl = HLS.parse(rollingPlaylist(manifest, live, { baseUrl: "seg/" }));
    log.push({ t, pl });
    expect(pl.mediaSequenceBase).toBeGreaterThanOrEqual(prevSeq);
    expect(pl.discontinuitySequenceBase).toBeGreaterThanOrEqual(prevDseq);
    prevSeq = pl.mediaSequenceBase; prevDseq = pl.discontinuitySequenceBase;
    pl.segments.forEach((s, i) => {
      const k = pl.mediaSequenceBase + i;
      // continuity: a segment number, once shown to any client, never changes URI on a later reload
      if (seen.has(k)) expect(seen.get(k)).toBe(s.uri);
      seen.set(k, s.uri);
    });
  }
  return { log, seen, published };
}

describe("hourly manifest swap", () => {
  const sizes = [[10, 3, 6], [12, 3], [7, 5, 4, 3], [10, 3, 6, 6]];
  const sim = simulate(4, (i) => sizes[i % sizes.length]);

  it("media sequence and discontinuity sequence stay monotonic, URIs stable per number (checked each reload)", () => {
    expect(sim.published.length).toBe(5);
    expect(sim.log.length).toBeGreaterThan(4000);
  });

  it("discontinuity tags: exactly at block starts (+ swap) and never inside a block, per hls-parser", () => {
    const tagged = new Map(); // k -> bool, then compare to uri pattern
    for (const { pl } of sim.log) pl.segments.forEach((s, i) => tagged.set(pl.mediaSequenceBase + i, [s.uri, !!s.discontinuity]));
    for (const [k, [uri, d]] of tagged) {
      const isBlockStart = /\/seg_000\.ts$/.test(uri);
      if (k === 0) expect(d).toBe(false);
      else expect(d).toBe(isBlockStart);
    }
  });

  it("discontinuitySequence of each listed segment = tagged segments before it (global count)", () => {
    const tagsUpTo = new Map(); // k -> count of tagged segments with number <= k, built from the union of playlists
    const flags = new Map();
    for (const { pl } of sim.log) pl.segments.forEach((s, i) => flags.set(pl.mediaSequenceBase + i, !!s.discontinuity));
    let n = 0; const maxK = Math.max(...flags.keys());
    for (let k = 0; k <= maxK; k++) { if (flags.get(k)) n++; tagsUpTo.set(k, n); }
    for (const { pl } of sim.log) pl.segments.forEach((s, i) => expect(s.discontinuitySequence).toBe(tagsUpTo.get(pl.mediaSequenceBase + i)));
  });

  it("each new manifest starts exactly at a loop boundary of the one it replaces", () => {
    for (let i = 1; i < sim.published.length; i++) {
      const old = sim.published[i - 1], nw = sim.published[i];
      const n = layout(old).segs.length;
      expect((nw.cycle_start_k - Number(old.cycle_start_k)) % n).toBe(0);
      expect(nw.cycle_start_k).toBeGreaterThan(Number(old.cycle_start_k));
    }
  });

  it("the old cycle completes (no cut mid-loop) before the new one starts", () => {
    // the last segment before the swap is the last segment of the old cycle
    for (let i = 1; i < sim.published.length; i++) {
      const s = sim.published[i].cycle_start_k;
      if (!sim.seen.has(s)) continue; // last manifest published at the very end never took effect
      const before = sim.seen.get(s - 1).replace(/^seg\//, ""), at = sim.seen.get(s).replace(/^seg\//, "");
      const oldLayout = layout(sim.published[i - 1]).segs;
      expect(before).toBe(oldLayout.at(-1).uri);
      expect(at).toBe(sim.published[i].blocks[0].segments[0].uri);
    }
  });

  it("naive swap (no cycle_start_k, no prev) is what broke: sequence is monotonic but URI behind a number changes", () => {
    const a = { segment_seconds: SEG, blocks: [block("a", 10)] }, b = { segment_seconds: SEG, blocks: [block("b", 7)] };
    const uriAt = (m, k) => HLS.parse(rollingPlaylist(m, k)).segments.at(-1).uri;
    expect(uriAt(a, 25)).not.toBe(uriAt(b, 25));
  });
});

describe("cycle_start_k semantics", () => {
  const m = { segment_seconds: SEG, cycle_start_k: 23, blocks: [block("x", 4), block("y", 2)] }; // N=6
  it("manifest without prev is phase-aligned: cycle[0] plays at k = cycle_start_k, earlier k extend the loop backwards", () => {
    expect(HLS.parse(rollingPlaylist(m, 23, { window: 1 })).segments[0].uri).toBe("x/seg_000.ts");
    expect(HLS.parse(rollingPlaylist(m, 22, { window: 1 })).segments[0].uri).toBe("y/seg_001.ts");
    expect(HLS.parse(rollingPlaylist(m, 4, { window: 1 })).segments[0].uri).toBe("y/seg_001.ts"); // 4 = 22 - 18
  });
  it("discontinuity sequence for a phase-shifted manifest matches counting tags per reload", () => {
    for (let live = 0; live < 100; live++) {
      const pl = HLS.parse(rollingPlaylist(m, live));
      const tagged = pl.segments.filter((s) => s.discontinuity).length;
      expect(pl.segments.at(-1).discontinuitySequence - pl.discontinuitySequenceBase).toBe(tagged);
    }
    expect(tagsBefore(0, 6, new Set([0, 4]))).toBe(0);
  });
  it("back-compat: no cycle_start_k and no prev == old behaviour", () => {
    const old = { segment_seconds: SEG, blocks: [block("x", 4), block("y", 2)] };
    const shifted = { ...old, cycle_start_k: 0 };
    for (let l = 0; l < 40; l++) expect(rollingPlaylist(shifted, l)).toBe(rollingPlaylist(old, l));
  });
  it("rejects a prev chain whose starts do not increase", () => {
    expect(() => rollingPlaylist({ ...m, cycle_start_k: 6, prev: { ...m, cycle_start_k: 6 } }, 10)).toThrow();
  });
});

describe("nextSwapStart", () => {
  const cur = { segment_seconds: SEG, cycle_start_k: 100, blocks: [block("a", 10)] };
  it("rounds up to the next boundary with margin", () => {
    expect(nextSwapStart(cur, 103, 10)).toBe(120);
    expect(nextSwapStart(cur, 110, 10)).toBe(120);
    expect(nextSwapStart(cur, 111, 10)).toBe(130);
  });
  it("keeps the pending start when the current manifest has not started", () => {
    expect(nextSwapStart(cur, 50)).toBe(100);
  });
});
