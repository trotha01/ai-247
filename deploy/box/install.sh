#!/bin/bash
# Install (or update) a channel's always-on loops on this machine, all under one folder.
#
#   bash deploy/box/install.sh lang [ROOT]        # ROOT defaults to /srv/channels; REF=<branch> to test a branch
#
# Runs as the account that will own the services (not root); uses sudo only to create ROOT and turn on lingering.
# Layout: ROOT/src/ai-247 (code), ROOT/venv, ROOT/voices, ROOT/tools, ROOT/<channel>/{env,r2.env,run/}, ROOT/README.md.
# Services: systemd user units from deploy/box/<channel>/*.service (Restart=always, enabled; lingering = start at boot).
# Secrets: ROOT/<channel>/r2.env (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET=ai247-media),
# created by you, mode 600. Without it everything is installed but the services are not started.
set -euo pipefail
CH=${1:?usage: install.sh CHANNEL [ROOT]}
ROOT=${2:-/srv/channels}
SRC=$(cd "$(dirname "$0")/../.." && pwd)
[ -d "$SRC/deploy/box/$CH" ] || { echo "no deploy/box/$CH"; exit 2; }
log() { echo "[install $CH] $*"; }

# 1. the folder
if [ ! -w "$ROOT" ]; then sudo mkdir -p "$ROOT" && sudo chown "$(id -un):$(id -gn)" "$ROOT"; fi
mkdir -p "$ROOT"/{src,tools,voices} "$ROOT/$CH/run"

# 2. code: a clone of the same repository at REF (default main), detached so updates are a plain re-run
URL=$(git -C "$SRC" remote get-url origin)
[ -d "$ROOT/src/ai-247/.git" ] || git clone -q "$URL" "$ROOT/src/ai-247"
git -C "$ROOT/src/ai-247" fetch -q origin "${REF:-main}"
git -C "$ROOT/src/ai-247" checkout -q --detach FETCH_HEAD
CODE=$ROOT/src/ai-247

# 3. tools: ffmpeg + Chromium (nix when present, else what the system has / Playwright's own Chromium)
CHROMIUM=""
if command -v nix > /dev/null; then
  nix --extra-experimental-features 'nix-command flakes' build nixpkgs#ffmpeg-headless --out-link "$ROOT/tools/ffmpeg"
  nix --extra-experimental-features 'nix-command flakes' build nixpkgs#chromium --out-link "$ROOT/tools/chromium"
  TOOLPATH=$ROOT/tools/ffmpeg/bin; CHROMIUM=$ROOT/tools/chromium/bin/chromium
else
  command -v ffmpeg > /dev/null || sudo apt-get install -y -qq ffmpeg
  TOOLPATH=$(dirname "$(command -v ffmpeg)")
fi

# 4. python
[ -x "$ROOT/venv/bin/python" ] || python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install -q --upgrade pip
"$ROOT/venv/bin/pip" install -q -r "$CODE/$CH/requirements.txt"
[ -n "$CHROMIUM" ] || "$ROOT/venv/bin/python" -m playwright install chromium

# 5. channel extras + non-secret environment
if [ "$CH" = lang ]; then bash "$CODE/deploy/box/lang/fetch_voices.sh" "$ROOT/voices" > /dev/null; fi
{ echo "PATH=$TOOLPATH:$ROOT/venv/bin:/usr/bin:/bin:/run/current-system/sw/bin"
  echo "LANG_VOICES=$ROOT/voices"
  [ -z "$CHROMIUM" ] || echo "LANG_CHROMIUM=$CHROMIUM"
  [ -z "${NIX_LD:-}" ] || echo "NIX_LD=$NIX_LD"
  [ -z "${NIX_LD_LIBRARY_PATH:-}" ] || echo "NIX_LD_LIBRARY_PATH=$NIX_LD_LIBRARY_PATH"
} > "$ROOT/$CH/env"
cp "$CODE/deploy/box/README.channels.md" "$ROOT/README.md"

# 6. smoke test: render one lesson (no upload)
if [ "$CH" = lang ]; then
  ( cd "$CODE" && set -a && . "$ROOT/lang/env" && set +a && "$ROOT/venv/bin/python" -m lang.render 0 --out "$ROOT/lang/run/smoke" > /dev/null )
  log "smoke render ok: $(du -h "$ROOT/lang/run/smoke/clip.mp4" | cut -f1) clip"; rm -rf "$ROOT/lang/run/smoke"
fi

# 7. services
UD=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
mkdir -p "$UD"
UNITS=()
for f in "$CODE/deploy/box/$CH"/*.service; do
  sed "s|@ROOT@|$ROOT|g" "$f" > "$UD/$(basename "$f")"; UNITS+=("$(basename "$f")")
done
systemctl --user daemon-reload
[ "$(loginctl show-user "$(id -un)" -p Linger --value)" = yes ] || sudo loginctl enable-linger "$(id -un)"
if [ ! -s "$ROOT/$CH/r2.env" ]; then
  log "installed, NOT started: create $ROOT/$CH/r2.env (mode 600) with the R2_* keys, then re-run this script"; exit 3
fi
chmod 600 "$ROOT/$CH/r2.env"
systemctl --user enable "${UNITS[@]}" > /dev/null
systemctl --user restart "${UNITS[@]}"
systemctl --user --no-pager --lines=0 status "${UNITS[@]}" | grep -E "●|Active:"
log "running; logs: journalctl --user -fu ${UNITS[-1]%.service}"
