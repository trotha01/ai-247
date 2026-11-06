#!/usr/bin/env bash
# Post-deploy smoke test for the fake-live HLS Worker (worker/src/index.js).
# Usage: scripts/smoke.sh https://ai247-live.<account>.workers.dev
# Checks: /healthz is "ok" (plain) or JSON with "ok": true (replay-pool failover build, docs/FAILOVER.md); /live.m3u8 starts with #EXTM3U and has CORS; EXT-X-MEDIA-SEQUENCE rises
# between two fetches (the edge advances every segment_seconds, default 6 s); the first segment URL
# returns 200 with a video content type. Exit 1 on any failure.
set -euo pipefail

base="${1:-${WORKER_URL:-}}"
if [ -z "$base" ]; then echo "usage: $0 <worker base url>" >&2; exit 2; fi
base="${base%/}"
# Longest wait for the media sequence to advance (segment_seconds + slack).
SEQ_WAIT="${SMOKE_SEQ_WAIT:-25}"

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
# get <url> <out-file> -> prints HTTP code; headers go to <out-file>.h
get() { curl -sS -L --max-time 20 -D "$2.h" -o "$2" -w '%{http_code}' "$1" || echo 000; }
header() { tr -d '\r' < "$1" | awk -v k="$2" 'BEGIN{IGNORECASE=1} tolower($1)==tolower(k)":" {sub(/^[^:]*: */,""); print; exit}'; }

echo "smoke: $base"

# 1. /healthz
code=$(get "$base/healthz" "$tmp/h")
[ "$code" = 200 ] || fail "/healthz returned HTTP $code"
grep -Eq '^ok|"ok": *true' "$tmp/h" || fail "/healthz body is not ok: $(head -c 200 "$tmp/h")"
echo "ok: /healthz $(sed -n 's/^ *"source": *"\([^"]*\)".*/(source=\1)/p' "$tmp/h" | head -1)"

# 2. /live.m3u8 (retry briefly: a fresh deploy can take a few seconds to propagate)
for i in 1 2 3 4 5 6; do
  code=$(get "$base/live.m3u8" "$tmp/p1")
  [ "$code" = 200 ] && break
  echo "  /live.m3u8 -> HTTP $code (attempt $i), retrying in 5 s"; sleep 5
done
[ "$code" = 200 ] || fail "/live.m3u8 returned HTTP $code: $(head -c 200 "$tmp/p1")"
head -1 "$tmp/p1" | grep -q '^#EXTM3U' || fail "/live.m3u8 does not start with #EXTM3U"
cors=$(header "$tmp/p1.h" access-control-allow-origin)
[ -n "$cors" ] || fail "/live.m3u8 has no Access-Control-Allow-Origin header"
ctype=$(header "$tmp/p1.h" content-type)
case "$ctype" in *mpegurl*|*mpegURL*) ;; *) fail "/live.m3u8 content-type is '$ctype'";; esac
seq1=$(sed -n 's/^#EXT-X-MEDIA-SEQUENCE:\([0-9]*\).*/\1/p' "$tmp/p1" | head -1)
[ -n "$seq1" ] || fail "/live.m3u8 has no EXT-X-MEDIA-SEQUENCE"
echo "ok: /live.m3u8 (#EXTM3U, CORS=$cors, media-sequence=$seq1)"

# 3. first segment URL (relative to the playlist)
seg=$(grep -v '^#' "$tmp/p1" | grep -v '^[[:space:]]*$' | head -1)
[ -n "$seg" ] || fail "/live.m3u8 lists no segments"
case "$seg" in http://*|https://*) segurl="$seg";; /*) segurl="$base$seg";; *) segurl="$base/$seg";; esac
code=$(get "$segurl" "$tmp/s")
[ "$code" = 200 ] || fail "first segment $segurl returned HTTP $code"
sct=$(header "$tmp/s.h" content-type)
case "$sct" in video/*) ;; *) fail "first segment content-type is '$sct', expected video/*";; esac
[ -s "$tmp/s" ] || fail "first segment body is empty"
[ -n "$(header "$tmp/s.h" access-control-allow-origin)" ] || fail "segment has no Access-Control-Allow-Origin header"
echo "ok: segment $seg ($sct, $(wc -c < "$tmp/s" | tr -d ' ') bytes)"

# 4. media sequence rises across two fetches a few seconds apart
start=$(date +%s)
while :; do
  sleep 3
  code=$(get "$base/live.m3u8?smoke=$RANDOM" "$tmp/p2")
  [ "$code" = 200 ] || fail "second /live.m3u8 fetch returned HTTP $code"
  seq2=$(sed -n 's/^#EXT-X-MEDIA-SEQUENCE:\([0-9]*\).*/\1/p' "$tmp/p2" | head -1)
  if [ -n "$seq2" ] && [ "$seq2" -gt "$seq1" ]; then
    echo "ok: media-sequence rose $seq1 -> $seq2"; break
  fi
  if [ $(( $(date +%s) - start )) -ge "$SEQ_WAIT" ]; then
    fail "EXT-X-MEDIA-SEQUENCE did not rise within ${SEQ_WAIT}s (stayed at ${seq2:-?}, first $seq1): the live edge is not advancing"
  fi
done

echo "SMOKE OK: $base"
