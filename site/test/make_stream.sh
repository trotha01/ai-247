#!/usr/bin/env bash
# Stand-in for the Day 0 bulletin (artifact 'bulletin-day0' of run 42187611180) when it cannot be downloaded:
# ten 6 s MPEG-TS segments, H.264 720p30, closed 2 s GOP, AAC 48 kHz mono, independent_segments.
# To test with the real artifact instead, unzip it and pass its directory to serve.py.
set -euo pipefail
out="${1:?usage: make_stream.sh OUTDIR}"
mkdir -p "$out"
ffmpeg -loglevel error -y \
  -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=60" \
  -f lavfi -i "sine=frequency=440:sample_rate=48000:duration=60" \
  -c:v libx264 -preset veryfast -profile:v main -pix_fmt yuv420p -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
  -force_key_frames "expr:gte(t,n_forced*2)" -c:a aac -ar 48000 -ac 1 -b:a 96k \
  -f hls -hls_time 6 -hls_playlist_type vod -hls_flags independent_segments \
  -hls_segment_filename "$out/seg_%03d.ts" "$out/index.m3u8"
echo "wrote $(ls "$out"/seg_*.ts | wc -l) segments to $out"
