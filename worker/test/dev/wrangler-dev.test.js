// Runs the real Worker under `wrangler dev --local` (workerd + miniflare R2) with the Day 0 fixture seeded
// into local R2. Verifies the HTTP surface end to end: playlist, segments, headers, errors.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import HLS from "hls-parser";

const root = new URL("../../", import.meta.url).pathname;
const fixture = (p) => new URL(`../fixtures/${p}`, import.meta.url).pathname;
const state = mkdtempSync(join(tmpdir(), "ai247-r2-"));
const scratch = mkdtempSync(join(tmpdir(), "ai247-seg-"));
const PORT = 8799;
const base = `http://127.0.0.1:${PORT}`;
const wr = (args, opts = {}) => execFileSync("npx", ["wrangler", ...args], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], ...opts });
let proc, log = "";

function put(key, file, ct) {
  wr(["r2", "object", "put", `ai247-media/${key}`, "--local", "--persist-to", state, "--file", file, "--content-type", ct]);
}

beforeAll(async () => {
  put("manifest.json", fixture("bulletin-day0/manifest.json"), "application/json");
  for (let i = 0; i < 10; i++) {
    const f = join(scratch, `seg_${i}.bin`);
    writeFileSync(f, Buffer.from(`SEG${i}`.padEnd(64, "\0")));
    put(`seg_${String(i).padStart(3, "0")}.ts`, f, "video/mp2t");
  }
  proc = spawn("npx", ["wrangler", "dev", "--local", "--port", String(PORT), "--persist-to", state, "--var", "ALLOW_TIME_OVERRIDE:1"], { cwd: root, detached: true, env: { ...process.env, CI: "1", WRANGLER_SEND_METRICS: "false" } });
  proc.stdout.on("data", (d) => (log += d));
  proc.stderr.on("data", (d) => (log += d));
  for (let i = 0; i < 120; i++) {
    try { if ((await fetch(`${base}/healthz`)).ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("wrangler dev did not start:\n" + log);
}, 90_000);

afterAll(() => {
  if (process.env.DEBUG_WRANGLER) writeFileSync(process.env.DEBUG_WRANGLER, log);
  try { process.kill(-proc.pid, "SIGKILL"); } catch {} // whole process group, including workerd
  rmSync(state, { recursive: true, force: true });
  rmSync(scratch, { recursive: true, force: true });
});

const EPOCH = 1793000000; // from wrangler.toml
const at = (live) => `${base}/live.m3u8?now=${EPOCH + live * 6 + 1}`;

describe("wrangler dev --local", () => {
  it("serves a valid rolling playlist computed from the clock", async () => {
    const r = await fetch(at(12));
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toBe("application/vnd.apple.mpegurl");
    expect(r.headers.get("access-control-allow-origin")).toBe("*");
    const pl = HLS.parse(await r.text());
    expect(pl.mediaSequenceBase).toBe(8);
    expect(pl.segments.map((s) => s.uri)).toEqual(["seg/seg_008.ts", "seg/seg_009.ts", "seg/seg_000.ts", "seg/seg_001.ts", "seg/seg_002.ts"]);
    expect(pl.segments[2].discontinuity).toBe(true);
    expect(pl.discontinuitySequenceBase).toBe(0);
  });

  it("media sequence never decreases over successive fetches across loops", async () => {
    let prev = -1;
    for (let live = 0; live < 45; live++) {
      const pl = HLS.parse(await (await fetch(at(live))).text());
      expect(pl.mediaSequenceBase).toBeGreaterThanOrEqual(prev);
      prev = pl.mediaSequenceBase;
    }
  }, 60_000);

  it("real clock works without override param being needed", async () => {
    const rr = await fetch(`${base}/live.m3u8`, { headers: { accept: "text/plain" } }); const bodyText = await rr.text(); if (rr.status !== 200) throw new Error(rr.status + " " + bodyText.slice(0, 900));
    const pl = HLS.parse(bodyText);
    expect(pl.segments).toHaveLength(5);
    const expectLive = Math.floor((Date.now() / 1000 - EPOCH) / 6);
    expect(Math.abs(pl.mediaSequenceBase + 4 - expectLive)).toBeLessThanOrEqual(2);
  });

  it("serves segments from R2 with immutable caching", async () => {
    const r = await fetch(`${base}/seg/seg_003.ts`);
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toBe("video/mp2t");
    expect(r.headers.get("cache-control")).toContain("immutable");
    expect((await r.text()).startsWith("SEG3")).toBe(true);
  });

  it("404s a missing segment, 400s traversal, 404s unknown routes", async () => {
    expect((await fetch(`${base}/seg/nope.ts`)).status).toBe(404);
    expect((await fetch(`${base}/seg/..%2Fmanifest.json`)).status).toBe(400);
    expect((await fetch(`${base}/seg/manifest.json`)).status).toBe(400);
    expect((await fetch(`${base}/other`)).status).toBe(404);
    expect((await fetch(`${base}/live.m3u8`, { method: "POST" })).status).toBe(405);
  });
});
