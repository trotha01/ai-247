// Headless render check of site/puddle-architecture.html (the Puddle Park node graph).
// usage: node e2e-architecture.js [SCREENSHOT_DIR]      (needs `playwright`, python3)
// Checks: the graph draws every node and labelled edge without JS errors; nodes, lanes and edge labels do not
// overlap; every node opens a panel with its trigger, files and model; no horizontal scroll at phone width; dark mode
// switches the background; the site footer links the page; repo paths named on the page exist.
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const fs = require("fs"), os = require("os"), path = require("path");
const [shots] = process.argv.slice(2);
const repo = path.resolve(__dirname, "../..");
const SITE = "http://127.0.0.1:8822";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const check = (name, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`); if (!ok) fails++; };
const overlap = (a, b, pad = 0) => a.x < b.x + b.w - pad && b.x < a.x + a.w - pad && a.y < b.y + b.h - pad && b.y < a.y + a.h - pad;

(async () => {
  const empty = fs.mkdtempSync(path.join(os.tmpdir(), "ai247-empty-"));
  const srv = spawn("python3", [path.join(__dirname, "serve.py"), empty, "8822"], { stdio: "ignore", detached: true });
  for (let i = 0; i < 60; i++) { try { if ((await fetch(SITE + "/puddle-architecture.html")).ok) break; } catch {} await sleep(250); }
  let browser;
  try {
    browser = await chromium.launch();
    for (const [scheme, width] of [["light", 1100], ["dark", 360]]) {
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme });
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
      page.on("requestfailed", (r) => errors.push(`${r.url()} ${r.failure()?.errorText}`));
      await page.goto(`${SITE}/puddle-architecture.html`);
      const tag = `[${scheme} ${width}px]`;
      const g = await page.evaluate(() => {
        const box = (e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };
        return {
          nodes: [...document.querySelectorAll(".n")].map((n) => ({ id: n.dataset.id, ...box(n.querySelector("rect")) })),
          lanes: [...document.querySelectorAll(".lane")].map(box),
          edges: [...document.querySelectorAll("path.e")].length,
          labels: [...document.querySelectorAll("text.el")].map((t) => ({ text: t.textContent, a: t.dataset.a, b: t.dataset.b, ...box(t) })),
          svgW: box(document.getElementById("graph")).w,
          scrollW: document.documentElement.scrollWidth, innerW: innerWidth,
          bg: getComputedStyle(document.body).backgroundColor,
        };
      });
      const ids = g.nodes.map((n) => n.id);
      check(`${tag} all 15 nodes drawn`, g.nodes.length === 15 && ["qwen", "show", "eng", "chan", "writer", "moss", "tts", "blender", "enc", "pub", "r2", "wk", "link", "studio", "player"].every((i) => ids.includes(i)), ids.join(","));
      check(`${tag} 19 edges, each with a label`, g.edges === 19 && g.labels.length === 19 && g.labels.every((l) => l.text.trim()), `edges=${g.edges} labels=${g.labels.length}`);
      const nodeHits = [];
      g.nodes.forEach((a, i) => g.nodes.slice(i + 1).forEach((b) => { if (overlap(a, b)) nodeHits.push(`${a.id}/${b.id}`); }));
      check(`${tag} no nodes overlap`, nodeHits.length === 0, nodeHits.join(" "));
      const laneHits = [];
      g.lanes.forEach((a, i) => g.lanes.slice(i + 1).forEach((b) => { if (overlap(a, b)) laneHits.push(`${i}/${i + 1}`); }));
      check(`${tag} lanes do not overlap`, laneHits.length === 0, laneHits.join(" "));
      // A label may sit 1.5 px into a node border (text halo), not further.
      const labelHits = [];
      g.labels.forEach((l) => g.nodes.forEach((n) => { if (overlap(l, n, 1.5 * g.svgW / 368)) labelHits.push(`"${l.text}"x${n.id}`); }));
      check(`${tag} edge labels clear of nodes`, labelHits.length === 0, labelHits.join(" "));
      check(`${tag} no horizontal scroll`, g.scrollW <= g.innerW, `${g.scrollW} <= ${g.innerW}`);
      const dark = /rgb\((\d+), (\d+), (\d+)\)/.exec(g.bg).slice(1).map(Number).every((v) => v < 60);
      check(`${tag} background follows color scheme`, scheme === "dark" ? dark : !dark, g.bg);

      const empties = [];
      for (const id of ids) {
        await page.click(`.n[data-id="${id}"]`);
        const p = await page.evaluate(() => {
          const P = document.getElementById("panel"), dts = [...P.querySelectorAll("dt")];
          const val = (k) => { const dt = dts.find((d) => d.textContent === k); return dt ? dt.nextElementSibling.textContent.trim() : ""; };
          return { node: P.dataset.node, ...Object.fromEntries(["Runs on", "Triggered by", "Inputs", "Outputs", "Source files", "Model / runtime"].map((k) => [k, val(k)])),
                   on: document.querySelectorAll("path.e.on").length };
        });
        if (p.node !== id || Object.values(p).some((v) => v === "") || p.on === 0) empties.push(id);
      }
      check(`${tag} every node opens a full panel and highlights its edges`, empties.length === 0, empties.join(","));
      check(`${tag} no JS/console/request errors`, errors.length === 0, errors.join(" | "));
      if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.click('.n[data-id="writer"]'); await page.screenshot({ path: path.join(shots, `puddle-architecture-${scheme}-${width}.png`), fullPage: true }); }
      if (scheme === "light") {
        const files = await page.evaluate(() => [...new Set([...document.querySelectorAll("script")].map((s) => s.textContent.match(/"(?:studio|newsbot|worker|docs|site)\/[^"]+"/g) || []).flat().map((s) => s.slice(1, -1)))]);
        const missing = files.filter((f) => !fs.existsSync(path.join(repo, f)));
        check(`source files named on the page exist (${files.length})`, missing.length === 0, missing.join(" "));
      }
      await ctx.close();
    }
    const idx = fs.readFileSync(path.join(repo, "site/index.html"), "utf8");
    check("site footer links the architecture page", /<footer>[\s\S]*href="puddle-architecture\.html"[\s\S]*<\/footer>/.test(idx));
  } catch (e) {
    check("run", false, String(e));
  } finally {
    if (browser) await browser.close();
    try { process.kill(-srv.pid); } catch {}
  }
  console.log(fails ? `${fails} check(s) failed` : "all checks passed");
  process.exit(fails ? 1 : 0);
})();
