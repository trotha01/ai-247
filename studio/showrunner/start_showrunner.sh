#!/bin/bash
# Start (or restart) the public, password-protected showrunner. Run as root on the GPU box.
#   Cloudflare quick tunnel (user gate) -> gate.js password page (user gate, :3080) -> dsh web (user show, :3081)
# The tunnel address changes on every start; it is saved to R2 (showrunner/url.txt) for the fixed redirect link.
set -euo pipefail
H=/hyperai/home
SR=$H/showrunner            # root-owned: scripts, instructions, skill, password
RUN=$SR/run                 # logs (readable by gate and show)
SHOW=$H/show                # the agent user's home (its dsh state and work folder)
export PATH=$H/node/bin:$H/dsh-global/bin:$H/bin:$PATH

id show >/dev/null 2>&1 || useradd -u 1001 -M -d $SHOW -s /bin/bash show
id gate >/dev/null 2>&1 || useradd -u 1002 -M -d /nonexistent -s /usr/sbin/nologin gate
mkdir -p $RUN $SHOW/work $SHOW/.dsh/profiles/web
chmod 755 $SR $SR/agents $SR/agents/skills $SR/agents/skills/showrunner
chmod 644 $SR/agents/AGENTS.md $SR/agents/skills/showrunner/SKILL.md $SR/gate.js
chown root:gate $SR/password && chmod 640 $SR/password
chmod 755 $RUN
cp $SR/profile/* $SHOW/.dsh/profiles/web/
chown -R show:show $SHOW && chmod 700 $SHOW

# cloudflared: a pinned release, checked against its sha256 before it is ever run
CF_VERSION=2026.10.7
CF_SHA256=1f99fb518b83dec2ba8d870a7cc991d82a77e6196295a3d2754ba17ab9f91872
if ! echo "$CF_SHA256  $H/bin/cloudflared" | sha256sum -c --status 2>/dev/null; then
  curl -sL https://github.com/cloudflare/cloudflared/releases/download/$CF_VERSION/cloudflared-linux-amd64 -o $H/bin/cloudflared.tmp
  echo "$CF_SHA256  $H/bin/cloudflared.tmp" | sha256sum -c --status || { echo "cloudflared checksum mismatch"; rm -f $H/bin/cloudflared.tmp; exit 1; }
  chmod 755 $H/bin/cloudflared.tmp && mv $H/bin/cloudflared.tmp $H/bin/cloudflared
fi

pkill -f "cloudflared tunnel" || true
pkill -f "$SR/gate.js" || true
pkill -u show -f "dsh" || true
sleep 2

# 1. tunnel
rm -f $RUN/*.log
touch $RUN/cloudflared.log $RUN/gate.log && chown gate:gate $RUN/cloudflared.log $RUN/gate.log
touch $RUN/dsh.log && chown show:gate $RUN/dsh.log && chmod 640 $RUN/dsh.log  # launch tokens: show writes, gate reads
su gate -s /bin/bash -c "nohup $H/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:3080 >> $RUN/cloudflared.log 2>&1 < /dev/null &"
URL=""
for i in $(seq 1 60); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' $RUN/cloudflared.log | head -1 || true)
  [ -n "$URL" ] && break; sleep 2
done
[ -n "$URL" ] || { echo "tunnel did not come up"; tail -20 $RUN/cloudflared.log; exit 1; }
HOST=${URL#https://}
echo "tunnel: $URL"

# 2. dsh web as the limited user, trusting only the tunnel's host name
# cd to the real path: /hyperai/home links to /output, and dsh keys workspaces by the real path
su show -c "cd $(readlink -f $SHOW/work) && HOME=$SHOW DSH_HOME=$SHOW/.dsh DSH_AGENTS_HOME=$SR/agents LLAMA_API_KEY=none PATH=$PATH \
  nohup dsh --profile web --no-open --host 127.0.0.1 --port 3081 --public-url $URL/dsh/ --trusted-host $HOST \
  >> $RUN/dsh.log 2>&1 < /dev/null &"
for i in $(seq 1 90); do grep -q "token=" $RUN/dsh.log && break; sleep 2; done
grep -q "token=" $RUN/dsh.log || { echo "dsh did not start"; tail -30 $RUN/dsh.log; exit 1; }
echo "dsh: up"

# 3. password gate
su gate -s /bin/bash -c "PUBLIC_HOST=$HOST DSH_LOG=$RUN/dsh.log GATE_PASSWORD_FILE=$SR/password \
  nohup $H/node/bin/node $SR/gate.js >> $RUN/gate.log 2>&1 < /dev/null &"
sleep 2
curl -s -o /dev/null -w "gate: %{http_code}\n" -H "Accept: text/html" http://127.0.0.1:3080/

# 4. publish the current address for the fixed redirect link
$H/venv/bin/python - "$URL" <<'Y'
import sys, boto3
from pathlib import Path
env = dict(l.split("=", 1) for l in Path("/hyperai/home/.r2.env").read_text().split() if "=" in l)
c = boto3.client("s3", endpoint_url=f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                 aws_access_key_id=env["R2_ACCESS_KEY_ID"], aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"], region_name="auto")
c.put_object(Bucket=env["R2_BUCKET"], Key="showrunner/url.txt", Body=sys.argv[1].encode(), ContentType="text/plain")
print("saved address to R2 showrunner/url.txt")
Y
echo "SHOWRUNNER UP: $URL"
