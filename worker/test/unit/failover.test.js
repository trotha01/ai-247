import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import HLS from "hls-parser";
import { liveEdge, nextSwapStart, rollingPlaylist, swapDseq } from "../../src/playlist.js";
import { SOURCE, composedPlaylist, initialState, liveAt, sourceOf, step } from "../../src/failover.js";

// Simulated channel: a live manifest (optionally re-published hourly per docs/MANIFEST-SWAP.md), a replay pool,
// and a scenario that says per reload whether the live manifest is usable. Every playlist is parsed with
// hls-parser and the RFC 8216 6.2.x invariants are checked on every reload, then scenario-specific facts.
const SEG = 6, EPOCH = 1_793_000_000;
const fx = (p) => JSON.parse(readFileSync(new URL(`../fixtures/${p}`, import.meta.url), "utf8"));
const day0 = fx("bulletin-day0/manifest.json");
const poolFixture = fx("pool-manifest.json");
const replayPool = fx("replay-pool.json");

const block = (id, n) => ({ id, segments: Array.from({ length: n }, (_, i) => ({ uri: `${id}/seg_${String(i).padStart(3, "0")}.ts`, duration: SEG })) });
const liveM = (id, sizes, extra = {}) => ({ version: 3, segment_seconds: SEG, epoch: EPOCH, blocks: sizes.map((n, i) => block(`${id}-${i}`, n)), ...extra });
const strip = (m) => { const { prev, ...rest } = m; return rest; };

function publish(cur, nowS, id, sizes) {
  const k = liveEdge(nowS * 1000, EPOCH * 1000, SEG);
  const start = cur ? nextSwapStart(cur, k) : 0;
  const prev = cur ? (Number(cur.cycle_start_k ?? 0) > k ? cur.prev : strip(cur)) : undefined;
  const m = liveM(id, sizes, { cycle_start_k: start, cycle_start_dseq: cur ? swapDseq(cur, start) : 0 });
  if (prev) m.prev = prev;
  return m;
}

/** Run the state machine over `seconds` of wall clock, reloading every 3 s. `scenario(t, k)` returns the live
 * input {manifest, ok, problem}; `onTick` may re-publish. Returns the per-reload log plus the union maps. */
function simulate({ seconds, scenario, pool = replayPool, window = 5, minPoolMs = 0, reloadEvery = 3 }) {
  let view = initialState();
  const log = [], seen = new Map(), flags = new Map();
  let prevSeq = -1, prevDseq = -1;
  for (let t = 0; t <= seconds; t += reloadEvery) {
    const nowMs = (EPOCH + t) * 1000;
    const k = liveEdge(nowMs, EPOCH * 1000, SEG);
    const live = scenario(t, k);
    const before = JSON.stringify(view);
    const next = step(view, { k, nowMs, window, live, pool, minPoolMs });
    expect(JSON.stringify(view)).toBe(before); // step is pure
    view = next;
    const text = composedPlaylist(view, k, { window, baseUrl: "seg/" });
    const pl = HLS.parse(text);
    expect(pl.isMasterPlaylist).toBe(false);
    expect(pl.targetDuration).toBe(6);
    expect(pl.mediaSequenceBase).toBe(Math.max(0, k - window + 1));
    expect(pl.mediaSequenceBase).toBeGreaterThanOrEqual(prevSeq);
    expect(pl.discontinuitySequenceBase).toBeGreaterThanOrEqual(prevDseq);
    prevSeq = pl.mediaSequenceBase; prevDseq = pl.discontinuitySequenceBase;
    const tagged = pl.segments.filter((s) => s.discontinuity).length;
    expect(pl.segments.at(-1).discontinuitySequence - pl.discontinuitySequenceBase).toBe(tagged);
    pl.segments.forEach((s, i) => {
      const kk = pl.mediaSequenceBase + i;
      if (seen.has(kk)) expect(seen.get(kk), `uri of segment ${kk} changed at t=${t}`).toBe(s.uri);
      seen.set(kk, s.uri);
      if (flags.has(kk)) expect(flags.get(kk), `tag of segment ${kk} changed at t=${t}`).toBe(!!s.discontinuity);
      flags.set(kk, !!s.discontinuity);
      if (kk === 0) expect(s.discontinuity).toBeFalsy();
    });
    log.push({ t, k, pl, text, view, source: sourceOf(view, live.ok, k) });
  }
  // DISCONTINUITY-SEQUENCE of every listed segment = number of tagged segments before it, counted over the union
  // of everything ever listed (the stream as a client that followed every reload would have seen it).
  const maxK = Math.max(...flags.keys());
  const upTo = new Map(); let n = 0;
  for (let kk = 0; kk <= maxK; kk++) { if (flags.get(kk)) n++; upTo.set(kk, n); }
  for (const { pl, t } of log) pl.segments.forEach((s, i) => expect(s.discontinuitySequence, `dseq of segment ${pl.mediaSequenceBase + i} at t=${t}`).toBe(upTo.get(pl.mediaSequenceBase + i)));
  return { log, seen, flags, view };
}

const uriOf = (seen, k) => seen.get(k)?.replace(/^seg\//, "");
const poolSeg = (pool, i) => { const segs = pool.blocks.flatMap((b) => b.segments); return segs[((i % segs.length) + segs.length) % segs.length].uri; };
const poolN = (pool) => pool.blocks.flatMap((b) => b.segments).length;

describe("no failover: composedPlaylist == rollingPlaylist (golden path untouched)", () => {
  for (const [name, m] of [["day0", day0], ["pool", poolFixture], ["replay-pool", replayPool]]) {
    it(name, () => {
      let view = initialState();
      for (let k = 0; k < 300; k++) {
        view = step(view, { k, nowMs: 0, live: { manifest: m, ok: true, problem: null }, pool: null });
        expect(composedPlaylist(view, k, { baseUrl: "seg/" })).toBe(rollingPlaylist(m, k, { baseUrl: "seg/" }));
      }
    });
  }
});

describe("live manifest disappears, replay pool takes over, live returns", () => {
  const live = liveM("ep", [10, 3, 6]);
  const DOWN = 300, UP = 900; // seconds
  const sim = simulate({ seconds: 1800, scenario: (t) => (t >= DOWN && t < UP ? { manifest: null, ok: false, problem: "missing" } : { manifest: live, ok: true, problem: null }) });
  const k0 = sim.log.find((l) => l.source === SOURCE.POOL).view.fo.k0;
  const r = sim.log.find((l) => l.view.fo?.r !== null && l.view.fo).view.fo.r;

  it("switches to the pool at the first number never listed before, tagged, and the pool starts at its first segment", () => {
    const kDown = liveEdge((EPOCH + DOWN) * 1000, EPOCH * 1000, SEG);
    expect(k0).toBe(kDown + 1);
    expect(sim.flags.get(k0)).toBe(true);
    expect(uriOf(sim.seen, k0)).toBe(poolSeg(replayPool, 0));
    for (let k = k0; k < r; k++) expect(uriOf(sim.seen, k)).toBe(poolSeg(replayPool, k - k0));
    // everything before the switch is still the live manifest, untouched
    for (let k = 0; k < k0; k++) expect(uriOf(sim.seen, k)).toBe(liveAt(live, k).uri);
  });

  it("returns to the live manifest in its own phase at the first unlisted number, tagged", () => {
    const kUp = liveEdge((EPOCH + UP) * 1000, EPOCH * 1000, SEG);
    expect(r).toBe(kUp + 1);
    expect(sim.flags.get(r)).toBe(true);
    for (let k = r; k <= Math.max(...sim.seen.keys()); k++) {
      expect(uriOf(sim.seen, k)).toBe(liveAt(live, k).uri); // same as if there had never been a failover
      if (k > r) expect(sim.flags.get(k)).toBe(liveAt(live, k).tag);
    }
  });

  it("after the return completes the failover state is folded into a constant offset", () => {
    expect(sim.view.fo).toBeNull();
    expect(Number.isInteger(sim.view.offset)).toBe(true); // may be negative: pool and live have different tag densities
    const last = sim.log.at(-1);
    expect(last.source).toBe(SOURCE.LIVE);
    // dseq now = live manifest's own count + offset
    const own = HLS.parse(rollingPlaylist(live, last.k)).discontinuitySequenceBase;
    expect(last.pl.discontinuitySequenceBase).toBe(own + sim.view.offset);
  });

  it("reports the source per reload", () => {
    const srcs = sim.log.map((l) => l.source);
    expect(srcs[0]).toBe(SOURCE.LIVE);
    expect(srcs.filter((s) => s === SOURCE.POOL).length).toBeGreaterThan(150);
    expect(srcs.at(-1)).toBe(SOURCE.LIVE);
  });
});

describe("cold start without a live manifest", () => {
  it("plays the pool from k = 0 exactly like a plain manifest would (deterministic across isolates), then returns", () => {
    const live = liveM("ep", [10, 3]);
    const sim = simulate({ seconds: 900, scenario: (t) => (t < 400 ? { manifest: null, ok: false, problem: "missing" } : { manifest: live, ok: true, problem: null }) });
    const first = sim.log[0];
    expect(first.source).toBe(SOURCE.POOL);
    expect(first.view.fo.k0).toBe(0);
    for (const l of sim.log.filter((x) => x.source === SOURCE.POOL)) expect(l.text).toBe(rollingPlaylist(replayPool, l.k, { baseUrl: "seg/" }));
    const r = sim.log.find((l) => l.view.fo?.r != null).view.fo.r;
    expect(sim.flags.get(r)).toBe(true);
    expect(uriOf(sim.seen, r)).toBe(liveAt(live, r).uri);
    expect(sim.log.at(-1).source).toBe(SOURCE.LIVE);
  });

  it("nothing to serve when there is neither a manifest nor a pool", () => {
    const v = step(initialState(), { k: 5, nowMs: 0, live: { manifest: null, ok: false, problem: "missing" }, pool: null });
    expect(v.chain).toBeNull();
    expect(v.fo).toBeNull();
    expect(sourceOf(v, false, 5)).toBe(SOURCE.NONE);
  });

  it("a broken manifest with no pool keeps serving the last good copy", () => {
    const live = liveM("ep", [4]);
    let v = step(initialState(), { k: 5, nowMs: 0, live: { manifest: live, ok: true, problem: null }, pool: null });
    v = step(v, { k: 6, nowMs: 0, live: { manifest: null, ok: false, problem: "missing" }, pool: null });
    expect(sourceOf(v, false, 6)).toBe(SOURCE.CACHED);
    expect(composedPlaylist(v, 6)).toBe(rollingPlaylist(live, 6));
  });
});

describe("hysteresis and flapping", () => {
  const live = liveM("ep", [10, 3]);
  it("stays on the pool at least minPoolMs even if the manifest is back", () => {
    const sim = simulate({ seconds: 600, minPoolMs: 120_000, scenario: (t) => (t >= 60 && t < 66 ? { manifest: null, ok: false, problem: "blip" } : { manifest: live, ok: true, problem: null }) });
    const onPool = sim.log.filter((l) => l.source === SOURCE.POOL);
    expect(onPool.at(-1).t - onPool[0].t).toBeGreaterThanOrEqual(120);
  });

  it("fails again right after a return (window still straddling r): valid, nested snapshot", () => {
    const sim = simulate({ seconds: 900, scenario: (t) => {
      const down = (t >= 100 && t < 200) || (t >= 206 && t < 400); // back for 6 s, down again
      return down ? { manifest: null, ok: false, problem: "missing" } : { manifest: live, ok: true, problem: null };
    } });
    const entries = sim.log.filter((l, i) => l.source === SOURCE.POOL && (i === 0 || sim.log[i - 1].source !== SOURCE.POOL));
    expect(entries.length).toBe(2);
    expect(sim.log.at(-1).source).toBe(SOURCE.LIVE);
    expect(sim.view.fo).toBeNull();
  });

  it("many short outages: every reload stays valid and the final offset equals the tags actually inserted minus the manifest's own", () => {
    const sim = simulate({ seconds: 3600, scenario: (t) => (t % 300 >= 150 && t % 300 < 190 ? { manifest: null, ok: false, problem: "missing" } : { manifest: live, ok: true, problem: null }) });
    const last = sim.log.at(-1);
    const own = HLS.parse(rollingPlaylist(live, last.k)).discontinuitySequenceBase;
    expect(last.pl.discontinuitySequenceBase - own).toBe(sim.view.offset);
  });
});

describe("failover across hourly manifest swaps (docs/MANIFEST-SWAP.md uploader) and the Day 0 shape", () => {
  it("uploader keeps publishing while the pool is on air; the return lands in the newest manifest's phase", () => {
    let manifest = null, nextPub = 0, n = 0;
    const sizes = [[10, 3, 6], [12, 3], [7, 5, 4, 3]];
    const published = [];
    const sim = simulate({ seconds: 4 * 3600, scenario: (t) => {
      if (t >= nextPub) { manifest = publish(manifest, EPOCH + t, `h${n}`, sizes[n % sizes.length]); published.push(manifest); n++; nextPub += 3600; }
      const down = t >= 3000 && t < 4300; // outage spans the 1 h publish at t=3600
      return down ? { manifest: null, ok: false, problem: "missing" } : { manifest, ok: true, problem: null };
    } });
    expect(published.length).toBe(5);
    const r = sim.log.find((l) => l.view.fo?.r != null).view.fo.r;
    const cur = sim.log.find((l) => l.view.fo?.r != null).view.chain; // the manifest live at the return
    expect(cur.blocks[0].id).toBe("h1-0");
    for (let k = r; k < r + 200; k++) if (sim.seen.has(k)) expect(uriOf(sim.seen, k)).toBe(liveAt(cur, k).uri);
    expect(sim.log.at(-1).source).toBe(SOURCE.LIVE);
    expect(sim.view.fo).toBeNull();
  });

  it("Day 0 manifest shape (flat segments) as the live manifest and as the pool", () => {
    const sim = simulate({ seconds: 900, pool: day0, scenario: (t) => (t >= 200 && t < 500 ? { manifest: null, ok: false, problem: "stale" } : { manifest: day0, ok: true, problem: null }) });
    const k0 = sim.log.find((l) => l.source === SOURCE.POOL).view.fo.k0;
    expect(sim.flags.get(k0)).toBe(true);
    expect(uriOf(sim.seen, k0)).toBe("seg_000.ts");
    expect(sim.log.at(-1).source).toBe(SOURCE.LIVE);
  });

  it("pool loops: block starts inside the pool are tagged while on air (long outage)", () => {
    const live = liveM("ep", [10, 3]);
    const sim = simulate({ seconds: 3600, scenario: (t) => (t >= 60 && t < 3000 ? { manifest: null, ok: false, problem: "missing" } : { manifest: live, ok: true, problem: null }) });
    const k0 = sim.log.find((l) => l.source === SOURCE.POOL).view.fo.k0;
    const N = poolN(replayPool);
    const starts = []; let acc = 0;
    for (const b of replayPool.blocks) { starts.push(acc); acc += b.segments.length; }
    for (let k = k0; k < k0 + 3 * N; k++) expect(sim.flags.get(k), `tag at ${k}`).toBe(starts.includes((k - k0) % N));
  });
});
