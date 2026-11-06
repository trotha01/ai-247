// Browser test: node e2e.js STREAMDIR HLSJS_FILE   (needs `playwright`; serves with serve.py)
// The CDN URL is routed to a local copy of hls.js@1.6.15 so the SRI hash in index.html is still verified.
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const path = require("path");
const [streamDir, hlsFile] = process.argv.slice(2);
const PORT = 8765, BASE = `http://127.0.0.1:${PORT}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const check = (name, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`); if (!ok) fails++; };

(async () => {
  const srv = spawn("python3", [path.join(__dirname, "serve.py"), streamDir, PORT], { stdio: "inherit" });
  await sleep(800);
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const newPage = async () => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.route("**/cdn.jsdelivr.net/npm/hls.js@1.6.15/dist/hls.min.js", (r) => r.fulfill({ path: hlsFile, contentType: "application/javascript" }));
    page.errors = [];
    page.on("pageerror", (e) => page.errors.push(String(e)));
    return page;
  };
  const state = (p) => p.evaluate(() => document.body.dataset.state);
  const waitState = (p, s, t) => p.waitForFunction((s) => document.body.dataset.state === s, s, { timeout: t }).then(() => true, () => false);

  try {
    // 1. static content
    let p = await newPage();
    await p.goto(BASE + "/");
    await p.waitForFunction(() => document.querySelectorAll("#sources li").length > 0);
    check("AI-GENERATED label visible", await p.locator("#ai-label").isVisible() && (await p.locator("#ai-label").innerText()) === "AI-GENERATED");
    check("source list has 8 links", (await p.locator("#sources li a").count()) === 8);
    check("hls.js loaded (SRI ok)", await p.evaluate(() => typeof window.Hls === "function"));
    check("no page errors", p.errors.length === 0, p.errors.join(";"));
    check("empty config => offline message", (await waitState(p, "offline", 3000)) && await p.locator("#status").isVisible());

    // 2. play Day 0-style segments
    const codecOk = await p.evaluate(() => MediaSource.isTypeSupported('video/mp4; codecs="avc1.4d401f,mp4a.40.2"'));
    console.log("browser H.264/AAC MSE support:", codecOk);
    p = await newPage();
    await p.goto(`${BASE}/?src=${BASE}/stream/index.m3u8`);
    if (codecOk) {
      check("plays stream (state live)", await waitState(p, "live", 20000));
      await sleep(3000);
      const t = await p.evaluate(() => document.getElementById("video").currentTime);
      check("currentTime advances", t > 1, `t=${t.toFixed(2)}`);
      check("fallback hidden while live", !(await p.locator("#status").isVisible()));
    } else {
      console.log("SKIP playback: this Chromium build lacks H.264/AAC (Playwright chromium); verify in Chrome/Safari/Firefox");
      const lvl = await p.evaluate(() => new Promise((res) => { const h = new Hls(); h.on(Hls.Events.MANIFEST_PARSED, (_e, d) => res(d.levels.length)); h.loadSource(location.search.slice(5)); }));
      check("hls.js parses the Day 0-style playlist", lvl === 1);
    }

    // 3. offline: playlist 404
    await fetch(BASE + "/__mode/404");
    p = await newPage();
    await p.goto(`${BASE}/?src=${BASE}/stream/index.m3u8&retry=2000`);
    check("404 playlist => offline fallback", (await waitState(p, "offline", 20000)) && await p.locator("#status").isVisible());
    await fetch(BASE + "/__mode/ok");
    if (codecOk) check("recovers after playlist returns", await waitState(p, "live", 20000));

    // 4. stalled: segments hang
    if (codecOk) {
      await fetch(BASE + "/__mode/freeze");
      p = await newPage();
      await p.goto(`${BASE}/?src=${BASE}/stream/index.m3u8&stall=4000&retry=2000`);
      check("hanging segments => stalled/offline fallback", (await waitState(p, "stalled", 40000)) || (await waitState(p, "offline", 20000)));
      await fetch(BASE + "/__mode/ok");
    }
  } finally {
    await browser.close(); srv.kill();
  }
  console.log(fails ? `${fails} FAILED` : "ALL PASSED");
  process.exit(fails ? 1 : 0);
})();
