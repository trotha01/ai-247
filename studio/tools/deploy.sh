#!/bin/bash
# Put this checkout's studio/ code on the GPU box (owners). Copies files to where the box runs them (see README,
# "Where things live on the box"), then restarts what changed.
#   tools/deploy.sh             copy only
#   tools/deploy.sh --restart   copy, then restart producer, worker, channel service and engineer loop
#                               (the showrunner web page is restarted separately: box/../showrunner/start_showrunner.sh,
#                               because that also gives it a new tunnel address)
# It never touches secrets, the channel's data (queue, library, directions, approved actions) or the brief.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE"
PAYLOAD=$(COPYFILE_DISABLE=1 tar --no-xattrs -czf - engine pipeline showrunner engineer box | base64 | tr -d '\n')
RESTART=$([ "$1" = "--restart" ] && echo 1 || echo 0)
cat <<SCRIPT | "$HERE/tools/box.sh"
set -e
T=\$(mktemp -d); echo "$PAYLOAD" | base64 -d | tar --no-same-owner -xzf - -C \$T
chown -R root:root \$T; chmod -R go-w \$T   # root runs this code: never keep the laptop's file owners
H=/hyperai/home; E=\$H/kids-test/blender
cp \$T/engine/puddle.py \$T/engine/voice.py \$T/engine/make_clip.sh \$T/pipeline/*.py \$E/
sed '1s|.*|#!/hyperai/home/venv/bin/python|' \$T/showrunner/channel > \$H/bin/channel
sed '1s|.*|#!/hyperai/home/venv/bin/python|' \$T/engineer/eng-test > \$H/bin/eng-test
chmod 755 \$H/bin/channel \$H/bin/eng-test
mkdir -p \$H/showrunner/agents \$H/showrunner/profile \$H/engineer/agents \$H/engineer/examples
cp \$T/showrunner/gate.js \$T/showrunner/start_showrunner.sh \$H/showrunner/
cp -r \$T/showrunner/agents/. \$H/showrunner/agents/ ; cp \$T/showrunner/profile/* \$H/showrunner/profile/
cp \$T/engineer/engineer_loop.py \$H/engineer/ ; cp -r \$T/engineer/agents/. \$H/engineer/agents/ ; cp \$T/engineer/examples/* \$H/engineer/examples/
cp \$T/engineer/profile/cordis.patch.yml /output/eng/.dsh/profiles/headless/ && chown eng:eng /output/eng/.dsh/profiles/headless/cordis.patch.yml
cp \$T/box/run_*.sh \$T/box/status.sh \$H/loop/ ; cp \$T/box/bl.sh \$T/box/install_dsh.sh \$H/
chmod -R a+rX \$H/showrunner/agents \$H/engineer; chmod 700 \$H/showrunner/start_showrunner.sh
rm -rf \$T; echo "copied"
if [ $RESTART = 1 ]; then
  pkill -f '^/hyperai/home/venv/bin/python /hyperai/home/bin/channel serve\$' || true  # the supervisor restarts it
  pkill -f producer_loop.py || true; pkill -f channel_worker.py || true; sleep 2
  \$H/loop/run_producer.sh; \$H/loop/run_worker.sh --block 4 --renders 4
  pkill -f engineer_loop.py || true
  nohup \$H/venv/bin/python -u \$H/engineer/engineer_loop.py >> \$H/loop/puddle/engineer.log 2>&1 < /dev/null &
  echo "restarted producer, worker, channel service, engineer loop"
fi
SCRIPT
