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

// ---- Fresh footage first (docs/MANIFEST-SWAP.md "Fresh footage first"): loop_from ---------------------------------
import { indexAt, tagsUpTo, eraSegment, eras } from "../../src/playlist.js";

describe("loop_from mapping (fresh blocks once, then the loop region)", () => {
  const m = { segment_seconds: SEG, cycle_start_k: 100, cycle_start_dseq: 7, loop_from: 2, blocks: [block("f0", 4), block("f1", 3), block("slate", 1), block("r0", 2)] }; // n=10, loopAt=7
  it("layout exposes loopAt and rejects an empty loop region", () => {
    expect(layout(m).loopAt).toBe(7);
    expect(layout({ ...m, loop_from: 0 }).loopAt).toBe(0);
    expect(() => layout({ ...m, loop_from: 4 })).toThrow(/loop_from/);
    expect(() => layout({ ...m, loop_from: -1 })).toThrow(/loop_from/);
    expect(() => layout({ ...m, loop_from: 1.5 })).toThrow(/loop_from/);
  });
  it("indexAt: the cycle once in order, then [loopAt, n) forever; loopAt 0 is the old modulo", () => {
    expect([...Array(16).keys()].map((c) => indexAt(c, 10, 7))).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 7, 8, 9, 7, 8, 9]);
    for (let c = -25; c < 60; c++) expect(indexAt(c, 10, 0)).toBe(((c % 10) + 10) % 10);
    expect(indexAt(-1, 10, 7)).toBe(9);
  });
  it("tagsUpTo counts tags under that mapping and equals the legacy count for loopAt 0", () => {
    const starts = new Set([0, 4, 7, 8]);
    const brute = (c) => { let n = 0; for (let i = 0; i < c; i++) if (starts.has(indexAt(i, 10, 7))) n++; return n; };
    for (let c = 0; c <= 60; c++) expect(tagsUpTo(c, 10, starts, 7)).toBe(brute(c));
    const legacy = (c) => { const full = Math.floor(c / 10); let n = full * starts.size; for (const b of starts) if (b < c % 10) n++; return n; };
    for (let c = -30; c <= 60; c++) expect(tagsUpTo(c, 10, starts, 0)).toBe(legacy(c));
  });
  it("rollingPlaylist plays the fresh blocks exactly once and then loops slate + replay, tagging block starts", () => {
    const uris = [];
    for (let k = 100; k < 100 + 10 + 9; k++) uris.push(HLS.parse(rollingPlaylist(m, k, { window: 1 })).segments[0].uri);
    const names = uris.map((u) => u.split("/")[0]);
    expect(names.slice(0, 10)).toEqual(["f0", "f0", "f0", "f0", "f1", "f1", "f1", "slate", "r0", "r0"]);
    expect(names.slice(10)).toEqual(["slate", "r0", "r0", "slate", "r0", "r0", "slate", "r0", "r0"]);
    expect(uris.filter((u) => u.startsWith("f")).length).toBe(7); // each fresh segment once
    const [e] = eras(m);
    expect(eraSegment(e, 100).tag).toBe(true);
    expect(eraSegment(e, 110).tag).toBe(true); // loop wrap to slate
    expect(eraSegment(e, 111).tag).toBe(true); // r0 block start
    expect(eraSegment(e, 112).tag).toBe(false);
    // discontinuity sequence per segment is consistent with the tags listed, reload after reload
    for (let live = 100; live < 160; live++) {
      const pl = HLS.parse(rollingPlaylist(m, live));
      expect(pl.segments.at(-1).discontinuitySequence - pl.discontinuitySequenceBase).toBe(pl.segments.filter((s) => s.discontinuity).length);
    }
  });
  it("nextSwapStart: finish the fresh region if it is still ahead, otherwise take over at k + margin", () => {
    expect(nextSwapStart(m, 95, 10)).toBe(107); // 105 < freshEnd 107
    expect(nextSwapStart(m, 50, 10)).toBe(100); // not started yet: keep the pending start
    expect(nextSwapStart(m, 97, 10)).toBe(107);
    expect(nextSwapStart(m, 98, 10)).toBe(108); // in the loop region: right away
    expect(nextSwapStart(m, 500, 10)).toBe(510);
    expect(swapDseq(m, 107)).toBe(7 + 2); // tags at 100 (f0) and 104 (f1); 107 itself (slate start) is not < 107
    expect(swapDseq(m, 108)).toBe(7 + 3);
  });
});

describe("hourly runs of 6 fresh bulletins with loop_from (fresh airs once, in order, before any replay)", () => {
  // 6 fresh blocks of 10 segments per "hour" of 60 segments; loop region = slate (1) + the previous hour's bulletins.
  const FRESH = 6, BLK = 10, HOURK = FRESH * BLK;
  function publishV3(cur, k, id, fresh = FRESH) {
    const start = cur ? nextSwapStart(cur, k) : 0;
    const pending = cur && Number(cur.cycle_start_k ?? 0) > k + 10;
    const prev = cur ? (pending ? cur.prev : strip(cur)) : undefined;
    const freshBlocks = Array.from({ length: fresh }, (_, i) => block(`${id}-f${i}`, BLK));
    const replays = cur ? cur.blocks.filter((b) => /-f\d$/.test(b.id)).slice(0, 6) : [];
    const m = { version: 3, segment_seconds: SEG, epoch: EPOCH, cycle_start_k: start, cycle_start_dseq: cur ? swapDseq(cur, start) : 0, loop_from: fresh, blocks: [...freshBlocks, block(`${id}-slate`, 1), ...replays] };
    if (prev) m.prev = prev;
    return m;
  }
  function run(publishAt, endK) {
    let manifest = null; const published = [], seen = new Map(), flags = new Map(); let prevSeq = -1, prevDseq = -1;
    for (let k = 0; k <= endK; k++) {
      if (published.length < publishAt.length && k === publishAt[published.length]) { manifest = publishV3(manifest, k, `h${published.length}`); published.push(manifest); }
      const pl = HLS.parse(rollingPlaylist(manifest, k, { baseUrl: "seg/" }));
      expect(pl.mediaSequenceBase).toBeGreaterThanOrEqual(prevSeq); expect(pl.discontinuitySequenceBase).toBeGreaterThanOrEqual(prevDseq);
      prevSeq = pl.mediaSequenceBase; prevDseq = pl.discontinuitySequenceBase;
      expect(pl.segments.at(-1).discontinuitySequence - pl.discontinuitySequenceBase).toBe(pl.segments.filter((s) => s.discontinuity).length);
      pl.segments.forEach((s, i) => {
        const kk = pl.mediaSequenceBase + i;
        if (seen.has(kk)) expect(seen.get(kk)).toBe(s.uri);
        if (flags.has(kk)) expect(flags.get(kk)).toBe(!!s.discontinuity);
        seen.set(kk, s.uri); flags.set(kk, !!s.discontinuity);
        if (kk === 0) expect(s.discontinuity).toBeFalsy();
      });
    }
    return { published, seen, flags };
  }
  const freshUris = (m) => m.blocks.slice(0, m.loop_from).flatMap((b) => b.segments.map((s) => `seg/${s.uri}`));

  it("published on time (every 60 segments, 40 in): each hour's fresh region airs once, contiguously, in order, and the next starts exactly where it ends", () => {
    const { published, seen } = run([0, 40, 100, 160, 220], 299); // h4 starts at 240; stop before its fresh region ends
    const timeline = [...seen.entries()].sort((a, b) => a[0] - b[0]).map(([, u]) => u);
    for (let i = 0; i < published.length; i++) {
      const m = published[i], f = freshUris(m);
      const at = timeline.indexOf(f[0]);
      expect(at).toBe(m.cycle_start_k);
      expect(timeline.slice(at, at + f.length)).toEqual(f);
      expect(timeline.filter((u) => f.includes(u)).length).toBe(f.length); // every fresh segment exactly once
      if (i > 0) expect(m.cycle_start_k).toBe(published[i - 1].cycle_start_k + HOURK); // fresh end of the previous hour
    }
    expect(timeline.some((u) => u.includes("-slate"))).toBe(false); // on time: the loop region never aired
  });

  it("published late: the previous hour's slate + replays fill the gap and the new fresh region starts at k + margin, tagged", () => {
    const { published, seen, flags } = run([0, 40, 130], 220); // h1 (start 60) fresh ends at 120; h2 lands at 130
    const h2 = published[2];
    expect(h2.cycle_start_k).toBe(140);
    expect(flags.get(140)).toBe(true);
    const gap = [...Array(20).keys()].map((i) => seen.get(120 + i));
    expect(gap[0]).toContain("h1-slate");
    expect(gap.slice(1, 11).every((u) => u.includes("h0-f0"))).toBe(true); // newest replay first: h0's bulletins loop
    expect(gap.filter((u) => u.includes("h1-f")).length).toBe(0); // no fresh h1 footage is repeated
    expect(seen.get(140)).toContain("h2-f0");
    // the segment numbers 100..139 keep their (replay) URIs after the swap: nothing listed ever changed
    expect(seen.get(139)).toBe(gap[19]);
  });

  it("legacy manifests (no loop_from) still swap at loop boundaries only", () => {
    const old = { segment_seconds: SEG, cycle_start_k: 100, cycle_start_dseq: 0, blocks: [block("a", 10), block("s", 2)] };
    expect(nextSwapStart(old, 103, 10)).toBe(124);
    expect(nextSwapStart(old, 115, 10)).toBe(136);
  });
});
