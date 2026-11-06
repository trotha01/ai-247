// R2-facing side of the replay-pool failover (docs/FAILOVER.md): loads and checks manifest.json and the pool
// manifest with short caches, runs the pure state machine in failover.js, and renders /live.m3u8 and /healthz.

import { eras, layout, liveEdge, manifestSegSeconds } from "./playlist.js";
import { SOURCE, canServe, composedPlaylist, describe, initialState, liveAt, sourceOf, step } from "./failover.js";

/** "" | "a/b" | "/a/b/" -> "" | "a/b/" so key = prefix + name is always well formed. */
export function normalizePrefix(p) {
  const t = String(p ?? "").replace(/^\/+|\/+$/g, "");
  return t ? `${t}/` : "";
}

export function config(env) {
  const num = (v, d) => { const n = Number(v); return Number.isFinite(n) && v !== undefined && v !== "" ? n : d; };
  return {
    prefix: normalizePrefix(env.PREFIX),
    window: num(env.WINDOW, 5),
    epochS: num(env.EPOCH, 0),
    poolKey: String(env.POOL_KEY ?? "pool/manifest.json"),
    maxAgeS: num(env.MAX_MANIFEST_AGE_S, 0), // 0 = never stale
    checkSegments: num(env.CHECK_SEGMENTS, 5), // upcoming live segments HEADed per manifest load; 0 = off
    ttlMs: num(env.MANIFEST_TTL_MS, 10_000),
    poolTtlMs: num(env.POOL_TTL_MS, 60_000),
    minPoolMs: num(env.FAILOVER_MIN_S, 30) * 1000,
  };
}

// Per-isolate state. Other isolates/colos decide independently (see docs/FAILOVER.md, "Limits").
const state = { view: initialState(), live: null, pool: null };
export const _state = state; // tests only

export function resetState() {
  state.view = initialState();
  state.live = null;
  state.pool = null;
}

const epochMsOf = (cfg, ...manifests) => {
  for (const m of manifests) if (m && m.epoch !== undefined) return Number(m.epoch) * 1000;
  return cfg.epochS * 1000;
};

async function readJson(bucket, key) {
  const obj = await bucket.get(key);
  if (!obj) return { obj: null, json: null, problem: `missing: ${key} is not in the bucket` };
  try {
    return { obj, json: await obj.json(), problem: null };
  } catch (e) {
    return { obj, json: null, problem: `invalid: ${key} is not JSON (${e.message})` };
  }
}

/** Load + check the live manifest. Cached for cfg.ttlMs. `nowMs` may be a test override (drives k);
 * `realNowMs` is the wall clock used for the age check. */
async function loadLive(env, cfg, nowMs, realNowMs, view) {
  const key = `${cfg.prefix}manifest.json`;
  const c = state.live;
  if (c && c.key === key && realNowMs - c.at < cfg.ttlMs) return c.value;
  const value = await checkLive(env, cfg, key, nowMs, realNowMs, view);
  state.live = { at: realNowMs, key, value };
  return value;
}

async function checkLive(env, cfg, key, nowMs, realNowMs, view) {
  const base = { key, manifest: null, ok: false, problem: null, age_s: null, uploaded: null, segments: 0, blocks: 0, checked_segments: 0, max_age_s: cfg.maxAgeS };
  const { obj, json, problem } = await readJson(env.BUCKET, key);
  if (problem) return { ...base, problem };
  const uploadedMs = obj.uploaded instanceof Date ? obj.uploaded.getTime() : Date.parse(obj.uploaded);
  const age_s = Number.isFinite(uploadedMs) ? Math.max(0, Math.round((realNowMs - uploadedMs) / 1000)) : null;
  const info = { ...base, age_s, uploaded: Number.isFinite(uploadedMs) ? new Date(uploadedMs).toISOString() : null };
  try {
    const { segs } = layout(json);
    eras(json); // validates cycle_start_k / prev chain too
    info.segments = segs.length;
    info.blocks = (json.blocks ?? [json]).filter((b) => b.segments?.length).length;
  } catch (e) {
    return { ...info, problem: `empty: ${e.message}` };
  }
  if (cfg.maxAgeS > 0 && age_s !== null && age_s > cfg.maxAgeS) {
    return { ...info, manifest: json, problem: `stale: manifest age ${age_s} s > MAX_MANIFEST_AGE_S ${cfg.maxAgeS}` };
  }
  if (cfg.checkSegments > 0) {
    // HEAD the segments the live mapping would list next (k+1 .. k+CHECK_SEGMENTS): a manifest that points at
    // objects that are not there is treated as broken before any client is sent a 404.
    const k = liveEdge(nowMs, epochMsOf(cfg, view.chain, json), manifestSegSeconds(json));
    const uris = [];
    for (let kk = k + 1; kk <= k + cfg.checkSegments; kk++) { const u = liveAt(json, kk).uri; if (!uris.includes(u)) uris.push(u); }
    const heads = await Promise.all(uris.map((u) => env.BUCKET.head(`${cfg.prefix}${u}`)));
    info.checked_segments = uris.length;
    const i = heads.findIndex((h) => !h);
    if (i >= 0) return { ...info, manifest: json, problem: `missing-segment: ${cfg.prefix}${uris[i]} (due within ${cfg.checkSegments} segments)` };
  }
  return { ...info, manifest: json, ok: true };
}

async function loadPool(env, cfg, realNowMs) {
  const key = `${cfg.prefix}${cfg.poolKey}`;
  const c = state.pool;
  if (c && c.key === key && realNowMs - c.at < cfg.poolTtlMs) return c.value;
  const base = { key, manifest: null, ok: false, problem: null, segments: 0, blocks: 0, built_at: null, built_from: null };
  const { json, problem } = await readJson(env.BUCKET, key);
  let value;
  if (problem) value = { ...base, problem };
  else {
    try {
      const { segs } = layout(json);
      value = { ...base, manifest: json, ok: true, segments: segs.length, blocks: (json.blocks ?? [json]).filter((b) => b.segments?.length).length, built_at: json.built_at ?? null, built_from: json.built_from ?? null };
    } catch (e) {
      value = { ...base, problem: `empty: ${e.message}` };
    }
  }
  state.pool = { at: realNowMs, key, value };
  return value;
}

/** Load both manifests, advance the state machine, and return everything the handlers need. */
export async function tick(env, nowMs, realNowMs = Date.now()) {
  const cfg = config(env);
  const live = await loadLive(env, cfg, nowMs, realNowMs, state.view);
  const pool = await loadPool(env, cfg, realNowMs);
  const chainOrLive = live.manifest ?? state.view.chain;
  const epochMs = epochMsOf(cfg, state.view.chain, live.manifest, pool.manifest);
  const segS = manifestSegSeconds(chainOrLive ?? pool.manifest ?? {});
  const k = liveEdge(nowMs, epochMs, segS);
  state.view = step(state.view, { k, nowMs: realNowMs, window: cfg.window, live: { manifest: live.manifest, ok: live.ok, problem: live.problem }, pool: pool.ok ? pool.manifest : null, minPoolMs: cfg.minPoolMs });
  return { cfg, live, pool, k, view: state.view, source: sourceOf(state.view, live.ok, k) };
}

export async function playlistBody(env, nowMs) {
  const t = await tick(env, nowMs);
  if (!canServe(t.view)) return { status: 503, body: `${t.live.problem ?? "no manifest"}; no replay pool (${t.pool.problem ?? "unusable"})` };
  return { status: 200, body: composedPlaylist(t.view, t.k, { window: t.cfg.window, baseUrl: "seg/" }), source: t.source };
}

/** JSON for /healthz: which source is live, manifest age, pool state. Status 200 always (liveness); `ok` says
 * whether something is being served. */
export async function health(env, nowMs) {
  const t = await tick(env, nowMs);
  const { manifest: _m, ...live } = t.live;
  const { manifest: _p, ...pool } = t.pool;
  const chainEpoch = t.view.chain?.epoch, poolEpoch = t.pool.manifest?.epoch;
  return {
    ok: canServe(t.view),
    source: t.source,
    reason: t.source === SOURCE.POOL ? t.view.fo?.reason : t.source === SOURCE.CACHED ? `${t.live.problem} (serving the last good manifest from memory)` : null,
    live_k: t.k,
    now: new Date().toISOString(),
    manifest: live,
    pool,
    ...describe(t.view, t.k),
    epoch_mismatch: chainEpoch !== undefined && poolEpoch !== undefined && Number(chainEpoch) !== Number(poolEpoch) ? { manifest: Number(chainEpoch), pool: Number(poolEpoch) } : null,
  };
}
