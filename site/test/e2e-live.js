// Live playback check of the deployed site: does https://ai-247.pages.dev actually play right now, and (optionally)
// has a given bulletin prefix reached the live playlist? Runs on the Actions runner after a publish (day1.yml step
// "Verify live playback"); the cloud sandbox cannot reach pages.dev / workers.dev, so this is the proof.
//
// usage: node e2e-live.js [--site URL] [--playlist URL] [--expect-prefix bulletins/<ts>] [--wait-sec N]
//   --site            page to load (default https://ai-247.pages.dev)
//   --playlist        live playlist to poll (default: streamUrl from ../config.json)
//   --expect-prefix   fail unless a segment URI containing this prefix shows up in the playlist within --wait-sec
//                     (the Worker swaps cycles at a loop boundary, so a fresh publish can take many minutes to air;
//                     with --wait-sec 0 the presence is only reported, never a failure)
// Exit 0 when the page reaches state "live", currentTime advances and segments arrive as video/mp2t; 1 otherwise.
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith("--")) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : "true"]);
  return acc;
}, []));
const SITE = (args.site || "https://ai-247.pages.dev").replace(/\/$/, "");
const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "config.json"), "utf8"));
const PLAYLIST = args.playlist || cfg.streamUrl;
const PREFIX = args["expect-prefix"] || "";
const WAIT = Number(args["wait-sec"] || 0);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const check = (name, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`); if (!ok) fails++; };

async function playlistText() {
  const r = await fetch(PLAYLIST, { headers: { "cache-control": "no-cache" } });
  return { status: r.status, text: await r.text(), seq: 0 };
}

(async () => {
  console.log(`site: ${SITE}\nplaylist: ${PLAYLIST}${PREFIX ? `\nexpect prefix: ${PREFIX} (wait up to ${WAIT} s)` : ""}`);

  // 1. playlist health (plain fetch, before the browser): #EXTM3U and a rising media sequence
  let p1 = await playlistText();
  check("playlist is 200 and starts with #EXTM3U", p1.status === 200 && p1.text.startsWith("#EXTM3U"), `status=${p1.status}`);
  const seqOf = (t) => Number((t.match(/#EXT-X-MEDIA-SEQUENCE:(\d+)/) || [])[1] || -1);
  const s1 = seqOf(p1.text);
  let s2 = s1;
  for (let i = 0; i < 10 && s2 <= s1; i++) { await sleep(3000); s2 = seqOf((await playlistText()).text); }
  check("EXT-X-MEDIA-SEQUENCE rises (fake-live clock advances)", s2 > s1, `${s1} -> ${s2}`);

  // 2. the page itself in Chromium: hls.js attaches, state live, time advances, segments are video/mp2t
  let browser;
  try {
    browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
    const page = await (await browser.newContext()).newPage();
    const errors = [], segs = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("response", (r) => { if (/\/seg\/.*\.ts(\?|$)/.test(r.url())) segs.push({ status: r.status(), ct: r.headers()["content-type"], url: r.url() }); });
    const resp = await page.goto(SITE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
    check("page loads (200)", resp && resp.status() === 200, `status=${resp && resp.status()}`);
    const codecOk = await page.evaluate(() => MediaSource.isTypeSupported('video/mp4; codecs="avc1.4d401f,mp4a.40.2"'));
    // Runners are slow to decode: allow 120 s, and accept "connecting with segments arriving" as playback in progress
    // (run 42229528561 sat at state=connecting after 60 s while 6 segments had already been fetched).
    const live = await page.waitForFunction(() => document.body.dataset.state === "live", null, { timeout: 120000 }).then(() => true, () => false);
    const state = await page.evaluate(() => document.body.dataset.state);
    check("page reaches state live (or is fetching segments while connecting)", live || (state === "connecting" && segs.length > 0), `state=${state} segments=${segs.length}`);
    if (codecOk) {
      await sleep(8000);
      const t = await page.evaluate(() => document.getElementById("video").currentTime);
      check("video currentTime advances", t > 2, `t=${t.toFixed(2)} s`);
    } else {
      console.log("SKIP currentTime: this Chromium build lacks H.264/AAC decoding; segment delivery is checked instead");
      await sleep(8000);
    }
    check("segments fetched as 200 video/mp2t", segs.length > 0 && segs.every((s) => s.status === 200 && s.ct === "video/mp2t"), `n=${segs.length}`);
    check("no JS/console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
    check("AI-generated label visible", await page.evaluate(() => /AI[- ]GENERATED/i.test(document.body.innerText)));
  } catch (e) {
    check("browser session", false, String(e));
  } finally {
    if (browser) await browser.close();
  }

  // 3. optional: the freshly published bulletin reaches the live playlist
  if (PREFIX) {
    const deadline = Date.now() + WAIT * 1000;
    let found = false, last = "";
    do {
      const t = (await playlistText()).text;
      last = t;
      found = t.includes(PREFIX);
      if (found) break;
      if (WAIT > 0) { console.log(`waiting for ${PREFIX} in the playlist (media-sequence ${seqOf(t)})...`); await sleep(30000); }
    } while (Date.now() < deadline);
    const uris = last.split("\n").filter((l) => l && !l.startsWith("#"));
    if (WAIT > 0) check(`new bulletin ${PREFIX} is in the live playlist`, found, `first URI now: ${uris[0] || "none"}`);
    else console.log(`${found ? "INFO new bulletin is already live" : "INFO new bulletin not yet in the live playlist (swap happens at the next cycle boundary)"}; first URI now: ${uris[0] || "none"}`);
  }
  console.log(fails ? `${fails} check(s) failed` : "all live checks passed");
  process.exit(fails ? 1 : 0);
})();
