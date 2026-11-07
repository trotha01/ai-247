#!/bin/bash
cd /hyperai/home/kids-test/blender
nohup /hyperai/home/venv/bin/python -u producer_loop.py --root /hyperai/home/loop/puddle "$@" >> /hyperai/home/loop/puddle/producer.log 2>&1 < /dev/null &
echo "producer pid $!"
