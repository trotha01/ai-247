// Replay-pool failover end to end under `wrangler dev --local` (workerd + Miniflare R2): the real Worker, the real
// R2 binding, objects deleted/re-put while it runs. Checks the playlist (hls-parser), the x-ai247-source header
// and /healthz for: manifest missing, manifest back, a referenced segment missing, an empty manifest, and (second
// Worker with MAX_MANIFEST_AGE_S=2) a stale manifest. Media sequence is checked monotonic across every fetch.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import HLS from "hls-parser";

const root = new URL("../../", import.meta.url).pathname;
const fixture = (p) => new URL(`../fixtures/${p}`, import.meta.url).pathname;
const scratch = mkdtempSync(join(tmpdir(), "ai247-fo-"));
const EPOCH = 1793000000;
const wr = (args) => execFileSync("npx", ["wrangler", ...args], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const procs = [];

const put = (state, key, file, ct) => wr(["r2", "object", "put", `ai247-media/${key}`, "--local", "--persist-to", state, "--file", file, "--content-type", ct]);
const del = (state, key) => wr(["r2", "object", "delete", `ai247-media/${key}`, "--local", "--persist-to", state]);
const seg = (name) => { const f = join(scratch, name.replace(/\//g, "_") + ".bin"); writeFileSync(f, Buffer.from(name.padEnd(64, "\0"))); return f; };

const POOL = {
  version: 2, kind: "replay-pool", segment_seconds: 6, epoch: EPOCH, built_at: "2026-11-06T12:00:00Z", built_from: { source: "test" },
  blocks: [
    { id: "pool-ep", kind: "replay", segments: Array.from({ length: 6 }, (_, i) => ({ uri: `pool/ep/seg_${String(i).padStart(3, "0")}.ts`, duration: 6 })) },
    { id: "pool-slate", kind: "slate", segments: Array.from({ length: 2 }, (_, i) => ({ uri: `pool/slate/slate_${String(i).padStart(3, "0")}.ts`, duration: 6 })) },
  ],
};
const poolUris = POOL.blocks.flatMap((b) => b.segments.map((s) => s.uri));

function seed(state) {
  put(state, "manifest.json", fixture("bulletin-day0/manifest.json"), "application/json");
  for (let i = 0; i < 10; i++) put(state, `seg_${String(i).padStart(3, "0")}.ts`, seg(`seg_${i}`), "video/mp2t");
  const pf = join(scratch, "pool.json"); writeFileSync(pf, JSON.stringify(POOL));
  put(state, "pool/manifest.json", pf, "application/json");
  for (const u of poolUris) put(state, u, seg(u), "video/mp2t");
}

async function start(state, port, vars) {
  const args = ["wrangler", "dev", "--local", "--port", String(port), "--persist-to", state, "--var", "ALLOW_TIME_OVERRIDE:1", "--var", "MANIFEST_TTL_MS:300", "--var", "POOL_TTL_MS:300", "--var", "FAILOVER_MIN_S:0"];
  for (const [k, v] of Object.entries(vars)) args.push("--var", `${k}:${v}`);
  const proc = spawn("npx", args, { cwd: root, detached: true, env: { ...process.env, CI: "1", WRANGLER_SEND_METRICS: "false" } });
  let log = "";
  proc.stdout.on("data", (d) => (log += d));
  proc.stderr.on("data", (d) => (log += d));
  procs.push(proc);
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 120; i++) {
    try { if ((await fetch(`${base}/healthz`)).ok) return base; } catch {}
    await sleep(500);
  }
  throw new Error("wrangler dev did not start:\n" + log);
}

afterAll(() => {
  for (const p of procs) try { process.kill(-p.pid, "SIGKILL"); } catch {}
  rmSync(scratch, { recursive: true, force: true });
});

class Client {
  constructor(base) { this.base = base; this.prevSeq = -1; this.prevDseq = -1; this.seen = new Map(); }
  async playlist(k) {
    const r = await fetch(`${this.base}/live.m3u8?now=${EPOCH + k * 6 + 1}`);
    expect(r.status).toBe(200);
    const pl = HLS.parse(await r.text());
    expect(pl.mediaSequenceBase).toBe(Math.max(0, k - 4));
    expect(pl.mediaSequenceBase).toBeGreaterThanOrEqual(this.prevSeq);
    expect(pl.discontinuitySequenceBase).toBeGreaterThanOrEqual(this.prevDseq);
    this.prevSeq = pl.mediaSequenceBase; this.prevDseq = pl.discontinuitySequenceBase;
    pl.segments.forEach((s, i) => { const kk = pl.mediaSequenceBase + i; if (this.seen.has(kk)) expect(this.seen.get(kk)).toBe(s.uri); this.seen.set(kk, s.uri); });
    return { pl, source: r.headers.get("x-ai247-source"), uris: pl.segments.map((s) => s.uri), tags: pl.segments.map((s) => !!s.discontinuity) };
  }
  async health(k) {
    const r = await fetch(`${this.base}/healthz?now=${EPOCH + k * 6 + 1}`);
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toBe("application/json");
    return r.json();
  }
}

describe("failover under wrangler dev --local", () => {
  let c;
  const state = mkdtempSync(join(tmpdir(), "ai247-r2fo-"));
  beforeAll(async () => { seed(state); c = new Client(await start(state, 8798, { MAX_MANIFEST_AGE_S: 0 })); }, 180_000);

  it("serves the live manifest and /healthz says so with the manifest age", async () => {
    const { source, uris } = await c.playlist(12);
    expect(source).toBe("live-manifest");
    expect(uris).toEqual(["seg/seg_008.ts", "seg/seg_009.ts", "seg/seg_000.ts", "seg/seg_001.ts", "seg/seg_002.ts"]);
    const h = await c.health(12);
    expect(h.ok).toBe(true);
    expect(h.source).toBe("live-manifest");
    expect(h.manifest.ok).toBe(true);
    expect(h.manifest.age_s).toBeGreaterThanOrEqual(0);
    expect(h.manifest.age_s).toBeLessThan(120);
    expect(h.manifest.uploaded).toMatch(/^\d{4}-/);
    expect(h.manifest.checked_segments).toBeGreaterThan(0);
    expect(h.pool.ok).toBe(true);
    expect(h.pool.segments).toBe(8);
    expect(h.failover).toBeNull();
    expect(h.live_k).toBe(12);
  });

  it("manifest.json deleted: the switch lands on the first number no client has seen, tagged", async () => {
    del(state, "manifest.json");
    await sleep(400); // > MANIFEST_TTL_MS
    let r = await c.playlist(13); // detection: the window 9..13 was already listed, so the switch is at 14
    expect(r.source).toBe("replay-pool");
    expect(r.uris).toEqual(["seg/seg_009.ts", "seg/seg_000.ts", "seg/seg_001.ts", "seg/seg_002.ts", "seg/seg_003.ts"]);
    r = await c.playlist(14);
    expect(r.uris.slice(0, 4)).toEqual(["seg/seg_000.ts", "seg/seg_001.ts", "seg/seg_002.ts", "seg/seg_003.ts"]); // unchanged
    expect(r.uris[4]).toBe("seg/pool/ep/seg_000.ts");
    expect(r.tags[4]).toBe(true);
    expect(r.pl.segments[4].discontinuitySequence).toBe(r.pl.segments[3].discontinuitySequence + 1);
    const h = await c.health(14);
    expect(h.source).toBe("replay-pool");
    expect(h.reason).toMatch(/^missing: manifest\.json/);
    expect(h.manifest.ok).toBe(false);
    expect(h.failover.since_k).toBe(14);
    expect(h.failover.return_k).toBeNull();
    expect(h.ok).toBe(true);
  });

  it("the pool keeps looping with its own block tags", async () => {
    const { source, uris, tags } = await c.playlist(22); // k0=14: 18..22 -> pool idx 4,5,6(slate 0),7,0(ep 0, wrap)
    expect(source).toBe("replay-pool");
    expect(uris).toEqual(["seg/pool/ep/seg_004.ts", "seg/pool/ep/seg_005.ts", "seg/pool/slate/slate_000.ts", "seg/pool/slate/slate_001.ts", "seg/pool/ep/seg_000.ts"]);
    expect(tags).toEqual([false, false, true, false, true]);
    const r = await fetch(`${c.base}/seg/pool/slate/slate_000.ts`);
    expect(r.status).toBe(200);
  });

  it("manifest.json back: returns to the live manifest in phase, tagged, then the state folds", async () => {
    put(state, "manifest.json", fixture("bulletin-day0/manifest.json"), "application/json");
    await sleep(400);
    let r = await c.playlist(23); // decision made here: return at 24
    expect(r.source).toBe("replay-pool");
    expect(r.uris[4]).toBe("seg/pool/ep/seg_001.ts");
    r = await c.playlist(24);
    expect(r.source).toBe("live-manifest");
    expect(r.uris[4]).toBe("seg/seg_004.ts"); // 24 % 10, the live manifest's own phase
    expect(r.tags[4]).toBe(true);
    let h = await c.health(24);
    expect(h.source).toBe("live-manifest");
    expect(h.failover.return_k).toBe(24);
    r = await c.playlist(30);
    expect(r.uris).toEqual(["seg/seg_006.ts", "seg/seg_007.ts", "seg/seg_008.ts", "seg/seg_009.ts", "seg/seg_000.ts"]);
    expect(r.tags).toEqual([false, false, false, false, true]);
    h = await c.health(30);
    expect(h.failover).toBeNull();
    expect(Number.isInteger(h.dseq_offset)).toBe(true);
  });

  it("a referenced segment missing from R2: fallback before any client is sent a 404", async () => {
    del(state, "seg_005.ts");
    await sleep(400);
    let r = await c.playlist(31); // upcoming 32..36 -> seg_002..seg_006 includes seg_005: detected now
    expect(r.source).toBe("replay-pool");
    expect(r.uris.every((u) => u !== "seg/seg_005.ts")).toBe(true);
    const h = await c.health(31);
    expect(h.reason).toMatch(/^missing-segment: seg_005\.ts/);
    r = await c.playlist(32);
    expect(r.uris[4]).toBe("seg/pool/ep/seg_000.ts");
    expect(r.tags[4]).toBe(true);
    put(state, "seg_005.ts", seg("seg_5"), "video/mp2t");
    await sleep(400);
    await c.playlist(33);
    const back = await c.playlist(34);
    expect(back.source).toBe("live-manifest");
    expect(back.uris[4]).toBe("seg/seg_004.ts");
    expect(back.tags[4]).toBe(true);
  });

  it("an empty manifest counts as broken", async () => {
    const f = join(scratch, "empty.json"); writeFileSync(f, JSON.stringify({ version: 1, segment_seconds: 6, segments: [] }));
    expect((await c.playlist(40)).source).toBe("live-manifest");
    put(state, "manifest.json", f, "application/json");
    await sleep(400);
    const r = await c.playlist(41);
    expect(r.source).toBe("replay-pool");
    const h = await c.health(41);
    expect(h.reason).toMatch(/^empty:/);
    put(state, "manifest.json", fixture("bulletin-day0/manifest.json"), "application/json");
    await sleep(400);
    await c.playlist(42);
    expect((await c.playlist(43)).source).toBe("live-manifest");
  });
});

describe("stale manifest (MAX_MANIFEST_AGE_S=2) under wrangler dev --local", () => {
  let c;
  const state = mkdtempSync(join(tmpdir(), "ai247-r2st-"));
  beforeAll(async () => { seed(state); c = new Client(await start(state, 8797, { MAX_MANIFEST_AGE_S: 2 })); }, 180_000);

  it("fresh manifest plays; once older than the limit the pool takes over; a re-upload brings live back", async () => {
    // The Worker booted on a manifest already older than 2 s (seeded before start), so it is on the pool (cold).
    expect((await c.health(0)).reason).toMatch(/^stale:/);
    put(state, "manifest.json", fixture("bulletin-day0/manifest.json"), "application/json");
    await sleep(400);
    await c.playlist(10); // return decided here
    expect((await c.playlist(11)).source).toBe("live-manifest");
    await sleep(2500);
    let r = await c.playlist(12); // stale again: detected
    expect(r.source).toBe("replay-pool");
    r = await c.playlist(13);
    expect(r.uris[4]).toBe("seg/pool/ep/seg_000.ts");
    expect(r.tags[4]).toBe(true);
    const h = await c.health(13);
    expect(h.reason).toMatch(/^stale: manifest age \d+ s > MAX_MANIFEST_AGE_S 2/);
    expect(h.manifest.age_s).toBeGreaterThanOrEqual(2);
    expect(h.manifest.max_age_s).toBe(2);
    put(state, "manifest.json", fixture("bulletin-day0/manifest.json"), "application/json");
    await sleep(400);
    await c.playlist(14);
    const back = await c.playlist(15);
    expect(back.source).toBe("live-manifest");
    expect(back.uris[4]).toBe("seg/seg_005.ts");
    expect(back.tags[4]).toBe(true);
    expect((await c.health(15)).manifest.ok).toBe(true);
  }, 30_000);
});
