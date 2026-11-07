#!/bin/bash
# Talk to the producer from your computer (owners).
#   tools/direct.sh "more songs, and let Wren lead them"   -> a standing direction (read within seconds)
#   tools/direct.sh                                         -> standing directions, last scenes, last block on air
HERE=$(cd "$(dirname "$0")" && pwd)
if [ $# -gt 0 ]; then
  printf '/hyperai/home/bin/channel direct %q\n' "$*" | "$HERE/box.sh"
else
  echo '/hyperai/home/bin/channel notes; echo; /hyperai/home/bin/channel recent 10; echo; /hyperai/home/bin/channel status' | "$HERE/box.sh"
fi
