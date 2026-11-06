// Full chain in a browser: real uploader layout -> local R2 -> Worker (wrangler dev --local) -> site/ with ?src=.
// usage: node e2e-worker.js HLSJS_FILE      (needs `playwright`, python3, ffmpeg, `npm ci` in worker/)
// The site is served from one origin (serve.py, :8821) and the Worker from another (:8820), so a passing run
// also proves CORS. The jsDelivr URL is routed to the local hls.js copy; the SRI hash is still enforced.
const { chromium } = require("playwright");
const { spawn, execFileSync } = require("child_process");
const fs = require("fs"), os = require("os"), path = require("path");
const [hlsFile] = process.argv.slice(2);
const repo = path.resolve(__dirname, "../..");
const workerDir = path.join(repo, "worker");
const PREFIX = "bulletins/20261106T120000Z";
const WORKER = "http://127.0.0.1:8820", SITE = "http://127.0.0.1:8821";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const check = (name, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`); if (!ok) fails++; };

(async () => {
  const store = fs.mkdtempSync(path.join(os.tmpdir(), "ai247-store-"));
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "ai247-r2-"));
  execFileSync("python3", ["-I", path.join(workerDir, "test/e2e/stage_bucket.py"), store, PREFIX], { stdio: "inherit" });
  const puts = JSON.parse(fs.readFileSync(path.join(store, "_puts.json"))).puts;
  for (const p of puts) {
    execFileSync("npx", ["wrangler", "r2", "object", "put", `ai247-media/${p.key}`, "--local", "--persist-to", state, "--file", path.join(store, p.key), "--content-type", p.content_type], { cwd: workerDir, stdio: "ignore" });
  }
  const spawned = [];
  const run = (cmd, args, opts) => { const p = spawn(cmd, args, { detached: true, stdio: "ignore", ...opts }); spawned.push(p); return p; };
  run("npx", ["wrangler", "dev", "--local", "--port", "8820", "--persist-to", state, "--var", `PREFIX:${PREFIX}`], { cwd: workerDir, env: { ...process.env, CI: "1", WRANGLER_SEND_METRICS: "false" } });
  const empty = fs.mkdtempSync(path.join(os.tmpdir(), "ai247-empty-"));
  run("python3", [path.join(__dirname, "serve.py"), empty, "8821"]);
  for (let i = 0; i < 120; i++) { try { if ((await fetch(WORKER + "/healthz")).ok) break; } catch {} await sleep(500); }

  let browser;
  try {
    browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
    const page = await (await browser.newContext()).newPage();
    await page.route("**/cdn.jsdelivr.net/npm/hls.js@1.6.15/dist/hls.min.js", (r) => r.fulfill({ path: hlsFile, contentType: "application/javascript" }));
    const errors = [], bad = [], segs = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("requestfailed", (r) => bad.push(`${r.url()} ${r.failure()?.errorText}`));
    page.on("response", (r) => { if (r.url().startsWith(WORKER + "/seg/")) segs.push(r); });

    await page.goto(`${SITE}/?src=${WORKER}/live.m3u8`);
    const codecOk = await page.evaluate(() => MediaSource.isTypeSupported('video/mp4; codecs="avc1.4d401f,mp4a.40.2"'));
    // Playlist through the browser (cross-origin XHR): proves CORS for the playlist.
    const lvl = await page.evaluate((u) => new Promise((res) => { const h = new Hls(); h.on(Hls.Events.MANIFEST_PARSED, (_e, d) => res(d.levels.length)); h.on(Hls.Events.ERROR, (_e, d) => d.fatal && res("ERR " + d.details)); h.loadSource(u); }), `${WORKER}/live.m3u8`);
    check("hls.js parses the Worker playlist cross-origin (CORS ok)", lvl === 1, String(lvl));

    if (codecOk) {
      check("page reaches state live", await page.waitForFunction(() => document.body.dataset.state === "live", null, { timeout: 30000 }).then(() => true, () => false));
      await sleep(3000);
      const t = await page.evaluate(() => document.getElementById("video").currentTime);
      check("currentTime advances", t > 1, `t=${t.toFixed(2)}`);
      check("segments fetched from Worker with CORS + video/mp2t", segs.length > 0 && segs.every((r) => r.status() === 200 && r.headers()["content-type"] === "video/mp2t" && r.headers()["access-control-allow-origin"] === "*"), `n=${segs.length}`);
    } else {
      console.log("SKIP playback: this Chromium lacks H.264/AAC (Playwright build); fetching segments via fetch() instead");
      const r = await page.evaluate(async (u) => { const t = await (await fetch(u)).text(); const seg = t.split("\n").find((l) => l.endsWith(".ts")); const s = await fetch(new URL(seg, u)); return { st: s.status, ct: s.headers.get("content-type"), n: (await s.arrayBuffer()).byteLength }; }, `${WORKER}/live.m3u8`);
      check("segment fetch cross-origin ok, video/mp2t, non-empty", r.st === 200 && r.ct === "video/mp2t" && r.n > 1000, JSON.stringify(r));
    }
    check("no JS/console errors", errors.length === 0, errors.join(" | "));
    check("no failed requests", bad.length === 0, bad.join(" | "));
  } finally {
    if (browser) await browser.close();
    for (const p of spawned) try { process.kill(-p.pid, "SIGKILL"); } catch {}
    fs.rmSync(store, { recursive: true, force: true }); fs.rmSync(state, { recursive: true, force: true });
  }
  console.log(fails ? `${fails} FAILED` : "ALL PASSED");
  process.exit(fails ? 1 : 0);
})();
