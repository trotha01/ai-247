#!/bin/bash
# tools/box.sh: run a bash script (stdin) on the GPU box as root, retrying the SSH gateway's occasional refusals.
#   echo 'uptime' | studio/tools/box.sh
HERE=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$HERE/.env.box" ] || { echo "missing $HERE/.env.box (copy .env.box.example)" >&2; exit 2; }
. "$HERE/.env.box"
IN=$(cat)
for i in 1 2 3 4 5; do
  OUT=$(printf '%s' "$IN" | $BOX_SSH "bash -s" 2>&1); RC=$?
  if [ $RC -eq 255 ] && grep -q "Permission denied\|Connection\|timed out" <<<"$OUT"; then sleep 4; continue; fi
  printf '%s\n' "$OUT"; exit $RC
done
printf '%s\n' "$OUT"; exit 255
