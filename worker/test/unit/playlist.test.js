import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import HLS from "hls-parser";
import { liveEdge, rollingPlaylist, tagsBefore, layout } from "../../src/playlist.js";

const fx = (p) => JSON.parse(readFileSync(new URL(`../fixtures/${p}`, import.meta.url), "utf8"));
const day0 = fx("bulletin-day0/manifest.json");
const pool = fx("pool-manifest.json");
const golden = fx("python-golden.json");

const parse = (t) => HLS.parse(t);

describe("Day 0 fixture (bulletin-day0 manifest layout)", () => {
  it("has 10 x 6 s segments", () => {
    expect(day0.segments).toHaveLength(10);
    expect(day0.segments.every((s) => s.duration === 6)).toBe(true);
  });

  it("emits a valid media playlist that hls-parser accepts", () => {
    const pl = parse(rollingPlaylist(day0, 3));
    expect(pl.isMasterPlaylist).toBe(false);
    expect(pl.targetDuration).toBe(6);
    expect(pl.segments.map((s) => s.uri)).toEqual(["seg_000.ts", "seg_001.ts", "seg_002.ts", "seg_003.ts"]);
    expect(pl.endlist).toBeFalsy();
  });

  it("window of 5 slides and media sequence = first listed global segment number", () => {
    const pl = parse(rollingPlaylist(day0, 7));
    expect(pl.mediaSequenceBase).toBe(3);
    expect(pl.segments.map((s) => s.uri)).toEqual(["seg_003.ts", "seg_004.ts", "seg_005.ts", "seg_006.ts", "seg_007.ts"]);
  });

  it("tags the loop wrap with EXT-X-DISCONTINUITY and never the first segment", () => {
    const pl = parse(rollingPlaylist(day0, 11));
    const idx = pl.segments.findIndex((s) => s.uri === "seg_000.ts");
    expect(pl.segments[idx].discontinuitySequence).toBe(1);
    expect(pl.segments[idx - 1].discontinuitySequence).toBe(0);
    expect(rollingPlaylist(day0, 0)).not.toContain("DISCONTINUITY\n");
  });
});

describe("sequence invariants across many reloads and loops", () => {
  for (const [name, m] of [["day0", day0], ["pool", pool]]) {
    it(`${name}: media/discontinuity sequence never decrease, uri stable per absolute number`, () => {
      const seen = new Map();
      let prevSeq = -1, prevDseq = -1;
      for (let live = 0; live < 600; live++) {
        const pl = parse(rollingPlaylist(m, live));
        expect(pl.mediaSequenceBase).toBeGreaterThanOrEqual(prevSeq);
        expect(pl.discontinuitySequenceBase).toBeGreaterThanOrEqual(prevDseq);
        // each reload slides by at most the window
        pl.segments.forEach((s, i) => {
          const k = pl.mediaSequenceBase + i;
          if (seen.has(k)) expect(seen.get(k)).toBe(s.uri);
          seen.set(k, s.uri);
        });
        // discontinuity sequence advances exactly by the tagged segments that left the window
        const tagged = pl.segments.filter((s) => s.discontinuity).length;
        expect(pl.segments.at(-1).discontinuitySequence - pl.discontinuitySequenceBase).toBe(tagged);
        prevSeq = pl.mediaSequenceBase;
        prevDseq = pl.discontinuitySequenceBase;
      }
    });
  }

  it("sequence keeps rising across the wrap (no reset to 0)", () => {
    const a = parse(rollingPlaylist(day0, 9)).mediaSequenceBase;
    const b = parse(rollingPlaylist(day0, 10)).mediaSequenceBase;
    const c = parse(rollingPlaylist(day0, 14)).mediaSequenceBase;
    expect([a, b, c]).toEqual([5, 6, 10]);
  });

  it("tagsBefore matches brute force", () => {
    const { segs, starts } = layout(pool);
    const n = segs.length;
    for (let first = 0; first < 4 * n; first++) {
      let c = 0;
      for (let k = 1; k < first; k++) if (starts.has(k % n)) c++;
      expect(tagsBefore(first, n, starts)).toBe(c);
    }
  });
});

describe("pool manifest (bulletin, slate, replay blocks)", () => {
  it("tags every block boundary and the wrap", () => {
    const text = rollingPlaylist(pool, 10 + 3 + 10 + 2, { window: 30 }); // through the wrap
    const pl = parse(text);
    const discUris = pl.segments.filter((s) => s.discontinuity).map((s) => s.uri);
    expect(discUris).toEqual(["slate/seg_000.ts", "ep-old/seg_000.ts", "ep-new/seg_000.ts"]);
  });
});

describe("matches the Python reference (newsbot.playlist.channel_playlist)", () => {
  for (const [name, m] of [["pool", pool], ["single", { blocks: [{ id: "main", segments: day0.segments.map((s) => ({ uri: s.file, duration: s.duration })) }] }]]) {
    for (const live of Object.keys(golden[name])) {
      it(`${name} live=${live}`, () => {
        expect(rollingPlaylist(m, Number(live), { baseUrl: "seg/" })).toBe(golden[name][live]);
      });
    }
  }
});

describe("clock", () => {
  it("live edge is floor((now-epoch)/6) and monotone", () => {
    expect(liveEdge(1000 * 6, 0, 6)).toBe(1);
    expect(liveEdge(1000 * 5.99, 0, 6)).toBe(0);
    expect(liveEdge(-5000, 0, 6)).toBe(0);
    let prev = 0;
    for (let t = 0; t < 10_000_000; t += 777_777) { const l = liveEdge(t, 0, 6); expect(l).toBeGreaterThanOrEqual(prev); prev = l; }
  });
  it("rejects empty or invalid manifests", () => {
    expect(() => rollingPlaylist({ segments: [] }, 0)).toThrow();
    expect(() => rollingPlaylist({ segments: [{ file: "a.ts", duration: 0 }] }, 0)).toThrow();
  });
});
