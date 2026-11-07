// Password gate in front of the showrunner (dsh web). No dependencies: node gate.js
//
//   browser --https--> Cloudflare tunnel --> gate (127.0.0.1:3080) --> dsh web (127.0.0.1:3081)
//
// One shared password (file GATE_PASSWORD_FILE). A correct password sets a signed 30-day cookie. Every other request,
// including the WebSocket upgrade, needs it.
//   /          the studio page: the live channel, the producer's standing directions and latest scenes, and the chat
//   /dsh/...   dsh web, prefix stripped (dsh runs with --public-url https://PUBLIC_HOST/dsh/). The studio's chat frame
//              first loads /dsh/?token=<launch token from DSH_LOG>, which dsh exchanges for its own session cookie.
//   /__status  JSON for the studio page (channel notes + recent scenes, via the root-side channel service)
// Requests reach dsh with Host set to PUBLIC_HOST: dsh only trusts that authority and checks it against the Origin.
"use strict";
const http = require("http");
const net = require("net");
const fs = require("fs");
const crypto = require("crypto");
const { execFile } = require("child_process");

const PORT = +(process.env.GATE_PORT || 3080);
const UP_PORT = +(process.env.DSH_PORT || 3081);
const PUBLIC_HOST = process.env.PUBLIC_HOST;
const DSH_LOG = process.env.DSH_LOG;
const PASSWORD = fs.readFileSync(process.env.GATE_PASSWORD_FILE, "utf8").trim();
const SECRET = crypto.randomBytes(32); // new on every start: everyone logs in again after a restart
const COOKIE = "sr_gate";
const STREAM = "https://aitv-live.mychalsimka.workers.dev/live.m3u8";
const CHANNEL = ["/hyperai/home/venv/bin/python", "/hyperai/home/bin/channel"];
const PROPOSALS = "/hyperai/home/loop/puddle/proposals";
const ID_RE = /^[0-9]{8}-[0-9]{6}-[a-z0-9_]{1,40}$/;
const MAX_AGE_S = 30 * 24 * 3600;
if (!PUBLIC_HOST || !DSH_LOG || PASSWORD.length < 4) throw new Error("PUBLIC_HOST, DSH_LOG and a 4+ char password are required");

function sign(issued) {
  return issued + "." + crypto.createHmac("sha256", SECRET).update(String(issued)).digest("base64url");
}
function authed(req) {
  const m = (req.headers.cookie || "").match(new RegExp("(?:^|;\\s*)" + COOKIE + "=([^;]+)"));
  if (!m) return false;
  const [issued] = m[1].split(".");
  const good = sign(issued);
  const a = Buffer.from(m[1]), b = Buffer.from(good);
  return a.length === b.length && crypto.timingSafeEqual(a, b) && Date.now() / 1000 - +issued < MAX_AGE_S;
}
function launchToken() {
  const log = fs.readFileSync(DSH_LOG, "utf8");
  const all = [...log.matchAll(/[?&]token=([A-Za-z0-9_\-.~%]+)/g)];
  return all.length ? all[all.length - 1][1] : null;
}

// lockout: 10 wrong passwords from one address in 10 minutes blocks it for the rest of the window
const fails = new Map();
function clientIp(req) { return req.headers["cf-connecting-ip"] || req.socket.remoteAddress; }
function locked(ip) {
  const f = fails.get(ip);
  if (!f || Date.now() - f.since > 600000) { fails.delete(ip); return false; }
  return f.n >= 10;
}
function failed(ip) {
  const f = fails.get(ip);
  if (!f || Date.now() - f.since > 600000) fails.set(ip, { n: 1, since: Date.now() });
  else f.n++;
}

const PAGE = (msg) => `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Puddle Park showrunner</title>
<style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:grid;place-items:center;min-height:100vh;margin:0}
form{background:#1c1c1c;padding:2rem;border-radius:12px;width:min(22rem,90vw)}h1{font-size:1.3rem;margin:0 0 .4rem}
p{color:#aaa;font-size:.9rem;margin:0 0 1.2rem}input,button{width:100%;box-sizing:border-box;font-size:1rem;padding:.7rem;border-radius:8px;border:1px solid #333}
input{background:#0d0d0d;color:#eee;margin-bottom:.8rem}button{background:#e85d75;color:#fff;border:0;cursor:pointer}.err{color:#ff8a8a}</style></head>
<body><form method="post" action="/__login"><h1>Puddle Park showrunner</h1>
<p>Talk to the AI that runs the channel. Watch it at <a href="https://puddle-park.pages.dev" style="color:#9cf">puddle-park.pages.dev</a>.</p>
${msg ? `<p class="err">${msg}</p>` : ""}
<input type="password" name="password" placeholder="Password" autofocus required>
<button>Enter</button></form></body></html>`;

function login(req, res) {
  const ip = clientIp(req);
  let body = "";
  req.on("data", (c) => { body += c; if (body.length > 4096) req.destroy(); });
  req.on("end", () => {
    if (locked(ip)) { res.writeHead(429, { "content-type": "text/html" }); return res.end(PAGE("Too many tries. Wait 10 minutes.")); }
    const pw = new URLSearchParams(body).get("password") || "";
    const a = crypto.createHash("sha256").update(pw).digest(), b = crypto.createHash("sha256").update(PASSWORD).digest();
    if (!crypto.timingSafeEqual(a, b)) {
      failed(ip);
      return setTimeout(() => { res.writeHead(401, { "content-type": "text/html" }); res.end(PAGE("Wrong password.")); }, 800);
    }
    const cookie = `${COOKIE}=${sign(Math.floor(Date.now() / 1000))}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${MAX_AGE_S}`;
    res.writeHead(303, { "set-cookie": cookie, location: "/" });
    res.end();
  });
}


function studio(res) {
  const tok = launchToken();
  const chatSrc = tok ? `/dsh/?token=${encodeURIComponent(tok)}` : "/dsh/";
  res.writeHead(200, { "content-type": "text/html", "cache-control": "no-store" });
  res.end(`<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Puddle Park studio</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:#111;color:#eee;height:100vh;display:grid;grid-template-columns:minmax(0,1.25fr) minmax(360px,1fr)}
.left{overflow:auto;padding:14px;display:flex;flex-direction:column;gap:12px}
h1{font-size:1.05rem;margin:0;display:flex;align-items:center;gap:.6rem}.badge{background:#e85d75;color:#fff;font-size:.7rem;padding:.15rem .45rem;border-radius:4px}
video{width:100%;aspect-ratio:16/9;background:#000;border-radius:8px}
.panel{background:#1b1b1b;border-radius:8px;padding:10px 12px}.panel h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#999;margin:0 0 6px}
.panel pre{margin:0;white-space:pre-wrap;font:13px/1.45 ui-monospace,monospace;color:#ddd}
.row{display:flex;justify-content:space-between;align-items:center;font-size:.8rem;color:#999}
a{color:#9cf}iframe{width:100%;height:100vh;border:0;border-left:1px solid #222;background:#fff}
@media (max-width:900px){body{grid-template-columns:1fr;height:auto}iframe{height:85vh;border-left:0;border-top:1px solid #222}}
</style></head><body>
<div class="left">
  <h1>Puddle Park <span class="badge">AI-GENERATED</span></h1>
  <video id="v" controls muted playsinline autoplay></video>
  <div class="row"><span id="st">connecting…</span><span>Click the speaker for sound · <a href="/__logout">log out</a></span></div>
  <div class="panel"><h2>Producer's standing directions</h2><pre id="notes">…</pre></div>
  <div class="panel"><h2>Latest scenes written (newest last)</h2><pre id="recent">…</pre></div>
  <div class="panel"><h2>New actions (engineer)</h2><div id="props" style="font-size:13px;line-height:1.5">…</div>
    <div style="color:#888;font-size:12px;margin-top:6px">Ask the showrunner for something the puppets can't do yet. The engineer builds and tests it; an owner approves it before it airs.</div></div>
  <div class="row"><span>New directions take 2-3 minutes to reach the screen: scenes already queued air first.</span></div>
</div>
<iframe src="${chatSrc}" title="Showrunner chat" allow="clipboard-write"></iframe>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.6.15/dist/hls.min.js" integrity="sha384-iZBI1/lW9u8FcBjxuQ8nPTsU7TXhZNtzkV8H3gQHSTgz+VYQoKWqGlBHqhO84alJ" crossorigin="anonymous"></script>
<script>
(function(){
  var v=document.getElementById('v'),st=document.getElementById('st'),src=${JSON.stringify(STREAM)},hls,last=-1,lastT=Date.now();
  function start(){ if(hls){hls.destroy();hls=null}
    if(window.Hls&&Hls.isSupported()){hls=new Hls();hls.on(Hls.Events.ERROR,function(e,d){if(d.fatal){st.textContent='reconnecting…';setTimeout(start,4000)}});hls.loadSource(src);hls.attachMedia(v)}
    else if(v.canPlayType('application/vnd.apple.mpegurl')){v.src=src}
    v.play().catch(function(){}); }
  v.addEventListener('playing',function(){st.textContent='● on air'});
  setInterval(function(){ if(v.paused){lastT=Date.now();return} if(v.currentTime!==last){last=v.currentTime;lastT=Date.now()} else if(Date.now()-lastT>15000){st.textContent='stalled, reconnecting…';lastT=Date.now();start()} },1000);
  start();
  function poll(){ fetch('/__status',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
      document.getElementById('notes').textContent=d.notes||'(none)';document.getElementById('recent').textContent=d.recent||'(none)';
      var el=document.getElementById('props'); el.textContent='';
      if(!d.proposals||!d.proposals.length){el.textContent='(no requests yet)';}
      (d.proposals||[]).forEach(function(p){ var row=document.createElement('div');
        var b=document.createElement('b'); b.textContent='['+p.status+'] '; row.appendChild(b);
        row.appendChild(document.createTextNode(p.title+(p.action?' → '+p.action:'')+(p.reason?' ('+p.reason+')':'')));
        if(p.review){ var a=document.createElement('a'); a.href='/__review/'+p.id+'.jpg'; a.target='_blank'; a.textContent=' preview';
          row.appendChild(a); }
        el.appendChild(row); }); }).catch(function(){}); }
  poll(); setInterval(poll,10000);
})();
</script></body></html>`);
}

function proposalsJson() {
  try {
    return fs.readdirSync(PROPOSALS).filter((d) => ID_RE.test(d)).sort().slice(-8).map((d) => {
      const r = JSON.parse(fs.readFileSync(`${PROPOSALS}/${d}/request.json`, "utf8"));
      return { id: r.id, title: r.title, status: r.status, action: r.action || null, reason: r.reason || null,
               review: fs.existsSync(`${PROPOSALS}/${d}/review.jpg`) };
    });
  } catch (e) { return []; }
}

function review(req, res) {
  const id = decodeURIComponent(req.url.slice("/__review/".length)).replace(/\.jpg$/, "");
  const f = `${PROPOSALS}/${id}/review.jpg`;
  if (!ID_RE.test(id) || !fs.existsSync(f)) { res.writeHead(404); return res.end("no preview"); }
  res.writeHead(200, { "content-type": "image/jpeg", "cache-control": "no-store" });
  fs.createReadStream(f).pipe(res);
}

function status(res) {
  let out = { proposals: proposalsJson() }, left = 2;
  const done = () => { if (--left === 0) { res.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" }); res.end(JSON.stringify(out)); } };
  execFile(CHANNEL[0], [CHANNEL[1], "notes"], { timeout: 20000 }, (e, so) => { out.notes = (so || "").trim(); done(); });
  execFile(CHANNEL[0], [CHANNEL[1], "recent", "8"], { timeout: 20000 }, (e, so) => {
    out.recent = (so || "").split("\n").map((l) => l.replace(/\s+\S+\.json\s*$/, "")).join("\n").trim(); done(); });
}

function fixHeaders(h) {
  const o = { ...h };
  delete o["x-frame-options"];
  if (o["content-security-policy"]) o["content-security-policy"] = String(o["content-security-policy"]).replace(/frame-ancestors[^;]*;?/g, "");
  if (o.location && String(o.location).startsWith("/") && !String(o.location).startsWith("/dsh/")) o.location = "/dsh" + o.location;
  return o;
}
function upstreamPath(url) { return url.startsWith("/dsh/") ? url.slice(4) : url === "/dsh" ? "/" : url; }

function forwardHeaders(req) {
  const h = { ...req.headers, host: PUBLIC_HOST };
  // strip the gate cookie so dsh never sees it
  if (h.cookie) h.cookie = h.cookie.split(/;\s*/).filter((c) => !c.startsWith(COOKIE + "=")).join("; ") || undefined;
  if (!h.cookie) delete h.cookie;
  return h;
}

const server = http.createServer((req, res) => {
  if (req.method === "POST" && req.url === "/__login") return login(req, res);
  if (req.url === "/__logout") {
    res.writeHead(303, { "set-cookie": `${COOKIE}=; Path=/; Max-Age=0`, location: "/" });
    return res.end();
  }
  if (!authed(req)) {
    const isPage = req.method === "GET" && (req.headers.accept || "").includes("text/html");
    res.writeHead(isPage ? 200 : 401, { "content-type": isPage ? "text/html" : "text/plain", "cache-control": "no-store" });
    return res.end(isPage ? PAGE("") : "login required");
  }
  if (req.method === "GET" && (req.url === "/" || req.url.startsWith("/?"))) return studio(res);
  if (req.method === "GET" && req.url === "/__status") return status(res);
  if (req.method === "GET" && req.url.startsWith("/__review/")) return review(req, res);
  const up = http.request({ host: "127.0.0.1", port: UP_PORT, method: req.method, path: upstreamPath(req.url), headers: forwardHeaders(req) }, (r) => {
    res.writeHead(r.statusCode, fixHeaders(r.headers));
    r.pipe(res);
  });
  up.on("error", () => { if (!res.headersSent) { res.writeHead(502, { "content-type": "text/plain" }); } res.end("the showrunner is restarting, try again in a minute"); });
  req.pipe(up);
});

server.on("upgrade", (req, socket, head) => {
  if (!authed(req)) { socket.end("HTTP/1.1 401 Unauthorized\r\n\r\n"); return; }
  const up = net.connect(UP_PORT, "127.0.0.1", () => {
    const h = forwardHeaders(req);
    let raw = `${req.method} ${upstreamPath(req.url)} HTTP/1.1\r\n`;
    for (const [k, v] of Object.entries(h)) for (const vv of [].concat(v)) raw += `${k}: ${vv}\r\n`;
    up.write(raw + "\r\n");
    if (head && head.length) up.write(head);
    socket.pipe(up).pipe(socket);
  });
  up.on("error", () => socket.destroy());
  socket.on("error", () => up.destroy());
});

server.listen(PORT, "127.0.0.1", () => console.log(`gate on 127.0.0.1:${PORT} -> dsh 127.0.0.1:${UP_PORT} as ${PUBLIC_HOST}`));
