#!/bin/bash
set -e
cd /hyperai/home
V=$(curl -s https://nodejs.org/dist/index.json | python3 -c 'import sys,json;print([r["version"] for r in json.load(sys.stdin) if r["version"].startswith("v24.")][0])')
echo "node $V"
curl -sL https://nodejs.org/dist/$V/node-$V-linux-x64.tar.xz -o /tmp/node.tar.xz
rm -rf node && mkdir node && tar xJf /tmp/node.tar.xz -C node --strip-components=1 && rm /tmp/node.tar.xz
export PATH=/hyperai/home/node/bin:$PATH
node --version
npm install -g --prefix /hyperai/home/dsh-global @deepseek-ai/dsh@0.2.1-rc.5 --no-fund --no-audit 2>&1 | tail -5
/hyperai/home/dsh-global/bin/dsh --version || /hyperai/home/dsh-global/bin/dsh --help | head -5
echo INSTALLDONE
