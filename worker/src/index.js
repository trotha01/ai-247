import { liveEdge, manifestSegSeconds, rollingPlaylist } from "./playlist.js";

const CORS = { "access-control-allow-origin": "*", "access-control-expose-headers": "*" };

// PREFIX is the R2 key prefix under which manifest.json and the segments live. Accept "bulletins/x", "/bulletins/x/"
// and "" and normalise to "" or "dir/sub/" so key = prefix + name is always well formed.
export function normalizePrefix(p) {
  const t = String(p ?? "").replace(/^\/+|\/+$/g, "");
  return t ? `${t}/` : "";
}
const MANIFEST_TTL_MS = 10_000;
let cached = { at: 0, key: "", value: null };

async function loadManifest(env, nowMs) {
  const key = `${normalizePrefix(env.PREFIX)}manifest.json`;
  if (cached.value && cached.key === key && nowMs - cached.at < MANIFEST_TTL_MS) return cached.value;
  const obj = await env.BUCKET.get(key);
  if (!obj) return null;
  const value = await obj.json();
  cached = { at: nowMs, key, value };
  return value;
}

function text(body, status, extra = {}) {
  return new Response(body, { status, headers: { ...CORS, "content-type": "text/plain", ...extra } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...CORS, "access-control-allow-methods": "GET, HEAD", "access-control-allow-headers": "range, content-type", "access-control-max-age": "86400" } });
    if (request.method !== "GET" && request.method !== "HEAD") return text("method not allowed", 405);

    if (url.pathname === "/healthz") return text("ok", 200);

    if (url.pathname === "/live.m3u8" || url.pathname === "/index.m3u8") {
      let nowMs = Date.now();
      // Test-only clock override; never enabled in wrangler.toml defaults.
      if (env.ALLOW_TIME_OVERRIDE === "1" && url.searchParams.has("now")) nowMs = Number(url.searchParams.get("now")) * 1000;
      const manifest = await loadManifest(env, nowMs);
      if (!manifest) return text("manifest.json not found in bucket", 503, { "cache-control": "no-store" });
      const epochMs = Number(manifest.epoch ?? env.EPOCH ?? 0) * 1000;
      const live = liveEdge(nowMs, epochMs, manifestSegSeconds(manifest));
      const body = rollingPlaylist(manifest, live, { window: Number(env.WINDOW ?? 5), baseUrl: "seg/" });
      return new Response(request.method === "HEAD" ? null : body, {
        headers: { ...CORS, "content-type": "application/vnd.apple.mpegurl", "cache-control": "public, max-age=1" },
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
