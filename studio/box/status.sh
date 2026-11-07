#!/bin/bash
R=/hyperai/home/loop/puddle
echo "== standing directions =="; cat $R/producer/notes.md; [ -s $R/producer/notes.md ] || echo "(none yet)"
echo; echo "== last 10 scenes =="
tail -10 $R/producer/history.jsonl | python3 -c 'import sys,json
for d in map(json.loads, sys.stdin): print("-", d["segment"], "|", d["title"])'
echo; echo "== last block on air =="; grep "ON AIR" $R/worker.log | tail -1
