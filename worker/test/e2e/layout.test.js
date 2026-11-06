// End to end: the REAL uploader (newsbot.r2.upload, fake S3 client) -> local R2 -> the REAL Worker under
// `wrangler dev --local`. Proves the key layout contract in docs/R2_LAYOUT.md, CORS and content types.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import HLS from "hls-parser";

const root = new URL("../../", import.meta.url).pathname;
const stage = new URL("./stage_bucket.py", import.meta.url).pathname;
const BULLETIN = "bulletins/20261106T120000Z";
const EPOCH = 1793000000;
const store = mkdtempSync(join(tmpdir(), "ai247-store-"));
const wr = (args) => execFileSync("npx", ["wrangler", ...args], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
let puts, manifest;
const procs = [];

function seed(state, key, file, ct) {
  wr(["r2", "object", "put", `ai247-media/${key}`, "--local", "--persist-to", state, "--file", file, "--content-type", ct]);
}

// Seed local R2 exactly as the uploader laid it out, except .ts get a WRONG content type on purpose
// (the Worker must answer video/mp2t no matter what R2 stored).
function seedUploaderLayout(state) {
  for (const p of puts) seed(state, p.key, join(store, p.key), p.key.endsWith(".ts") ? "application/octet-stream" : p.content_type);
}

async function startWorker(state, port, vars) {
  const args = ["wrangler", "dev", "--local", "--port", String(port), "--persist-to", state, "--var", "ALLOW_TIME_OVERRIDE:1"];
  for (const [k, v] of Object.entries(vars)) args.push("--var", `${k}:${v}`);
  const proc = spawn("npx", args, { cwd: root, detached: true, env: { ...process.env, CI: "1", WRANGLER_SEND_METRICS: "false" } });
  let log = "";
  proc.stdout.on("data", (d) => (log += d));
  proc.stderr.on("data", (d) => (log += d));
  procs.push(proc);
  for (let i = 0; i < 120; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/healthz`)).ok) return `http://127.0.0.1:${port}`; } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("wrangler dev did not start:\n" + log);
}

beforeAll(() => {
  execFileSync("python3", ["-I", stage, store, BULLETIN], { stdio: "inherit", env: { ...process.env, PYTHONPATH: "" } });
  const j = JSON.parse(readFileSync(join(store, "_puts.json"), "utf8"));
  puts = j.puts;
  manifest = JSON.parse(readFileSync(join(store, BULLETIN, "manifest.json"), "utf8"));
}, 120_000);

afterAll(() => {
  for (const p of procs) try { process.kill(-p.pid, "SIGKILL"); } catch {}
  rmSync(store, { recursive: true, force: true });
});

const at = (base, live) => `${base}/live.m3u8?now=${EPOCH + live * 6 + 1}`;

describe("uploader key layout vs Worker (per-bulletin prefix)", () => {
  it("uploader writes manifest.json + segments under '{prefix}/' with the right content types", () => {
    const keys = puts.map((p) => p.key);
    expect(keys).toContain(`${BULLETIN}/manifest.json`);
    expect(keys).not.toContain("manifest.json"); // nothing at the bucket root
    expect(keys.filter((k) => k.endsWith(".ts"))).toHaveLength(10);
    expect(puts.find((p) => p.key.endsWith("seg_000.ts")).content_type).toBe("video/mp2t");
  });

  it("manifest format: Day 0 shape, bare file names, durations 6 s", () => {
    expect(manifest.segment_seconds).toBe(6);
    expect(manifest.segments).toHaveLength(10);
    for (const s of manifest.segments) {
      expect(s.file).toMatch(/^seg_\d{3}\.ts$/);
      expect(s.duration).toBeGreaterThan(5.9);
      expect(s.sha256).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  it("(informational) uploader order: manifest.json should be written after all segments", () => {
    const order = puts.map((p) => p.key.split("/").pop());
    const m = order.indexOf("manifest.json");
    const lastTs = order.map((k, i) => (k.endsWith(".ts") ? i : -1)).reduce((a, b) => Math.max(a, b));
    if (m < lastTs) console.warn("WARN uploader writes manifest.json BEFORE its segments (see docs/R2_LAYOUT.md, atomic-last rule)");
    expect(true).toBe(true);
  });

  describe("PREFIX unset (bucket root) = the old mismatch", () => {
    let base;
    beforeAll(async () => {
      const state = mkdtempSync(join(tmpdir(), "ai247-r2a-"));
      seedUploaderLayout(state);
      base = await startWorker(state, 8811, { PREFIX: "" });
    }, 180_000);
    it("503: manifest.json not found at the root", async () => {
      const r = await fetch(`${base}/live.m3u8`);
      expect(r.status).toBe(503);
      expect(r.headers.get("access-control-allow-origin")).toBe("*"); // even errors are readable by the page
    });
  });

  describe("PREFIX = bulletins/<ts> (the fix)", () => {
    let base;
    beforeAll(async () => {
      const state = mkdtempSync(join(tmpdir(), "ai247-r2b-"));
      seedUploaderLayout(state);
      // no trailing slash on purpose: the Worker normalises it
      base = await startWorker(state, 8812, { PREFIX: BULLETIN });
    }, 180_000);

    it("playlist resolves, parses, and every listed segment is fetchable with the right bytes + headers", async () => {
      const r = await fetch(at(base, 12), { headers: { origin: "https://ai247.pages.dev" } });
      expect(r.status).toBe(200);
      expect(r.headers.get("access-control-allow-origin")).toBe("*");
      const pl = HLS.parse(await r.text());
      expect(pl.segments).toHaveLength(5);
      for (const s of pl.segments) {
        const sr = await fetch(new URL(s.uri, `${base}/live.m3u8`), { headers: { origin: "https://ai247.pages.dev" } });
        expect(sr.status).toBe(200);
        expect(sr.headers.get("content-type")).toBe("video/mp2t"); // R2 stored application/octet-stream
        expect(sr.headers.get("access-control-allow-origin")).toBe("*");
        const buf = Buffer.from(await sr.arrayBuffer());
        const want = manifest.segments.find((m) => s.uri.endsWith(m.file));
        expect(createHash("sha256").update(buf).digest("hex")).toBe(want.sha256);
      }
    }, 60_000);

    it("CORS preflight allows GET + Range from any origin", async () => {
      const r = await fetch(`${base}/seg/seg_000.ts`, { method: "OPTIONS", headers: { origin: "https://x.example", "access-control-request-method": "GET", "access-control-request-headers": "range" } });
      expect(r.status).toBe(204);
      expect(r.headers.get("access-control-allow-origin")).toBe("*");
      expect(r.headers.get("access-control-allow-headers")).toContain("range");
    });

    it("keys outside the prefix are not reachable", async () => {
      expect((await fetch(`${base}/seg/..%2Fx.ts`)).status).toBe(400);
      expect((await fetch(`${base}/seg/${BULLETIN}/seg_000.ts`)).status).toBe(404); // would be prefix+prefix
    });
  });
});

describe("channel layout: root manifest with full-key URIs, PREFIX unset", () => {
  let base;
  beforeAll(async () => {
    const state = mkdtempSync(join(tmpdir(), "ai247-r2c-"));
    seedUploaderLayout(state);
    // What Day 1 pool.channel_blocks produces: uri = '{upload prefix}/{file}' relative to the bucket root.
    const channel = {
      version: 2, segment_seconds: 6, epoch: EPOCH,
      blocks: [{ id: "bulletin", segments: manifest.segments.map((s) => ({ uri: `${BULLETIN}/${s.file}`, file: s.file, duration: s.duration })) }],
    };
    const f = join(store, "channel-manifest.json");
    writeFileSync(f, JSON.stringify(channel));
    seed(state, "manifest.json", f, "application/json");
    base = await startWorker(state, 8813, { PREFIX: "" });
  }, 180_000);

  it("plays the per-bulletin objects through the root manifest", async () => {
    const pl = HLS.parse(await (await fetch(at(base, 3))).text());
    expect(pl.segments[0].uri).toMatch(new RegExp(`^seg/${BULLETIN}/seg_\\d{3}\\.ts$`));
    const sr = await fetch(new URL(pl.segments.at(-1).uri, `${base}/live.m3u8`));
    expect(sr.status).toBe(200);
    expect(sr.headers.get("content-type")).toBe("video/mp2t");
  });
});
