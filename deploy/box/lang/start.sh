#!/bin/bash
# Install and start the language channel on the HyperAI box as two always-on systemd services
# (Restart=always, enabled at boot). Run as root from the ai-247 checkout:  bash deploy/box/lang/start.sh
# Needs /hyperai/home/lang/r2.env with R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET=ai247-media
# (mode 600; a key that can write ai247-media). Stop: systemctl stop lang-worker lang-producer (a STOP file only pauses: systemd restarts them).
set -eu
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
HOME_DIR=/hyperai/home/lang
mkdir -p "$HOME_DIR" /hyperai/home/loop/lang
[ -f "$HOME_DIR/r2.env" ] || { echo "missing $HOME_DIR/r2.env (see the comment at the top)"; exit 1; }
chmod 600 "$HOME_DIR/r2.env"
command -v ffmpeg > /dev/null || apt-get install -y -qq ffmpeg
[ -x "$HOME_DIR/venv/bin/python" ] || python3 -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/pip" install -q -r "$REPO/requirements.txt" -r "$REPO/lang/requirements.txt"
"$HOME_DIR/venv/bin/python" -m playwright install --with-deps chromium > /dev/null
bash "$REPO/deploy/box/lang/fetch_voices.sh" "$HOME_DIR/voices"
for u in lang-producer lang-worker; do
  sed "s|@REPO@|$REPO|g; s|@HOME@|$HOME_DIR|g" "$REPO/deploy/box/lang/$u.service" > /etc/systemd/system/$u.service
done
rm -f /hyperai/home/loop/lang/STOP
systemctl daemon-reload
systemctl enable --now lang-producer lang-worker
systemctl --no-pager status lang-producer lang-worker | head -20
echo "logs: journalctl -fu lang-worker"
