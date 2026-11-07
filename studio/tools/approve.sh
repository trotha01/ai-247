#!/bin/bash
# Approve the engineer's new puppet actions (owners only: needs root SSH to the box).
#   tools/approve.sh                    list requests and live actions
#   tools/approve.sh ID                 approve a "ready" request: the action goes on air
#   tools/approve.sh reject ID "why"    send it back
#   tools/approve.sh retire ACTION      take a live action off the air
# Look at the preview in the studio page's "New actions" panel first.
HERE=$(cd "$(dirname "$0")" && pwd)
case "$1" in
  "") echo '/hyperai/home/bin/channel proposals; echo; /hyperai/home/bin/channel actions' ;;
  reject) printf '/hyperai/home/bin/channel reject %q %q\n' "$2" "${3:-rejected by owner}" ;;
  retire) printf '/hyperai/home/bin/channel retire %q\n' "$2" ;;
  *) printf '/hyperai/home/bin/channel approve %q\n' "$1" ;;
esac | "$HERE/box.sh"
