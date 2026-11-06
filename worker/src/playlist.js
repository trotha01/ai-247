// Pure playlist logic (no Workers APIs) so it is unit-testable in plain Node.
// JS port of newsbot/playlist.py channel_playlist (Day 1), which is the tested reference.

export const DEFAULT_WINDOW = 5;

/** Normalise a manifest into blocks. Accepts the Day 0 shape ({segments:[{file,duration}]}) or a pool shape
 * ({blocks:[{id,segments:[{uri|file,duration}]}]}). Each block is encoded together, so every block start
 * (including the wrap back to block 0) is a timestamp reset => EXT-X-DISCONTINUITY. */
export function layout(manifest) {
  const blocks = manifest.blocks ?? [{ id: "main", segments: manifest.segments }];
  const segs = [];
  const starts = new Set();
  for (const b of blocks) {
    if (!b.segments?.length) continue;
    starts.add(segs.length);
    for (const s of b.segments) segs.push({ uri: s.uri ?? s.file, duration: Number(s.duration) });
  }
  if (!segs.length) throw new Error("manifest has no segments");
  for (const s of segs) if (!(s.duration > 0)) throw new Error("bad segment duration");
  return { segs, starts };
}

/** Count of discontinuity-tagged segments with global index < first (segment 0 is never tagged). */
export function tagsBefore(first, n, starts) {
  if (first <= 0) return 0;
  const full = Math.floor(first / n);
  const r = first % n;
  let count = full * starts.size;
  for (const b of starts) if (b < r) count++;
  return count - (starts.has(0) ? 1 : 0);
}

/** Global live-edge segment number for wall-clock `nowMs`. The clock only ever moves it forward. */
export function liveEdge(nowMs, epochMs, segSeconds) {
  return Math.max(0, Math.floor((nowMs - epochMs) / 1000 / segSeconds));
}

export function manifestSegSeconds(manifest) {
  return Number(manifest.segment_seconds ?? 6);
}

export function rollingPlaylist(manifest, live, { window = DEFAULT_WINDOW, baseUrl = "" } = {}) {
  const { segs, starts } = layout(manifest);
  const n = segs.length;
  const first = Math.max(0, live - window + 1);
  const target = Math.ceil(Math.max(...segs.map((s) => s.duration)));
  const out = [
    "#EXTM3U",
    "#EXT-X-VERSION:3",
    `#EXT-X-TARGETDURATION:${target}`,
    `#EXT-X-MEDIA-SEQUENCE:${first}`,
    `#EXT-X-DISCONTINUITY-SEQUENCE:${tagsBefore(first, n, starts)}`,
  ];
  for (let k = first; k <= live; k++) {
    const s = segs[k % n];
    if (k > 0 && starts.has(k % n)) out.push("#EXT-X-DISCONTINUITY");
    out.push(`#EXTINF:${s.duration.toFixed(3)},`, `${baseUrl}${s.uri}`);
  }
  return out.join("\n") + "\n";
}
