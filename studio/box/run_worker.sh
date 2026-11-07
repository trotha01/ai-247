#!/bin/bash
# start the channel worker in the background: run_worker.sh [extra args]
cd /hyperai/home/kids-test/blender
set -a; . /hyperai/home/.r2.env; set +a
export PATH=/hyperai/home/venv/bin:$PATH
nohup /hyperai/home/venv/bin/python -u channel_worker.py --root /hyperai/home/loop/puddle --prefix puddle/ "$@" >> /hyperai/home/loop/puddle/worker.log 2>&1 < /dev/null &
echo "worker pid $!"
