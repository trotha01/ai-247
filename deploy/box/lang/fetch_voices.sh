#!/bin/bash
# Download the Piper voices the language channel uses into DIR (default /hyperai/home/lang/voices).
# Licences (model cards checked 2026-11-07, see lang/LICENSES.md): paola CC0 data, rapunzelina CC0 data,
# ljspeech public-domain data. Not used: el_GR-joy (CC BY-NC), he_IL-saspeech (non-commercial data).
set -eu
DIR=${1:-/hyperai/home/lang/voices}
mkdir -p "$DIR"
B=https://huggingface.co/rhasspy/piper-voices/resolve/main
for p in it/it_IT/paola/medium/it_IT-paola-medium el/el_GR/rapunzelina/medium/el_GR-rapunzelina-medium \
         en/en_US/ljspeech/medium/en_US-ljspeech-medium; do
  for e in onnx onnx.json; do
    f="$DIR/$(basename $p).$e"
    [ -s "$f" ] || curl -fsSL --retry 3 -o "$f" "$B/$p.$e"
  done
done
ls -la "$DIR"
