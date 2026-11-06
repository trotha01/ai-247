// Manifest loading, replay-pool failover and /healthz live in channel.js + failover.js (docs/FAILOVER.md).
import { health, normalizePrefix, playlistBody } from "./channel.js";

const CORS = { "access-control-allow-origin": "*", "access-control-expose-headers": "*" };

function text(body, status, extra = {}) {
  return new Response(body, { status, headers: { ...CORS, "content-type": "text/plain", ...extra } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...CORS, "access-control-allow-methods": "GET, HEAD", "access-control-allow-headers": "range, content-type", "access-control-max-age": "86400" } });
    if (request.method !== "GET" && request.method !== "HEAD") return text("method not allowed", 405);

    let nowMs = Date.now();
    // Test-only clock override; never enabled in wrangler.toml defaults.
    if (env.ALLOW_TIME_OVERRIDE === "1" && url.searchParams.has("now")) nowMs = Number(url.searchParams.get("now")) * 1000;

    if (url.pathname === "/healthz") {
      // Always 200 (liveness); the JSON says which source is on air (live-manifest / replay-pool) and the manifest age.
      const body = JSON.stringify(await health(env, nowMs), null, 2) + "\n";
      return new Response(request.method === "HEAD" ? null : body, { headers: { ...CORS, "content-type": "application/json", "cache-control": "no-store" } });
    }

    if (url.pathname === "/live.m3u8" || url.pathname === "/index.m3u8") {
      const r = await playlistBody(env, nowMs);
      if (r.status !== 200) return text(r.body, r.status, { "cache-control": "no-store" });
      return new Response(request.method === "HEAD" ? null : r.body, {
        headers: { ...CORS, "content-type": "application/vnd.apple.mpegurl", "cache-control": "public, max-age=1", "x-ai247-source": r.source },
      });
    }

    if (url.pathname.startsWith("/seg/")) {
      const rel = decodeURIComponent(url.pathname.slice(5));
      if (!/^[A-Za-z0-9_.\-\/]+\.ts$/.test(rel) || rel.includes("..") || rel.startsWith("/")) return text("bad segment path", 400);
      const obj = await env.BUCKET.get(`${normalizePrefix(env.PREFIX)}${rel}`);
      if (!obj) return text("segment not found", 404);
      return new Response(request.method === "HEAD" ? null : obj.body, {
        headers: { ...CORS, "content-type": "video/mp2t", "cache-control": "public, max-age=31536000, immutable", etag: obj.httpEtag },
      });
    }
    return text("not found", 404);
  },
};
