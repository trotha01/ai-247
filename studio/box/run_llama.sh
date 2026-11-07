#!/bin/bash
# Qwen 3.8 27B for the producer and the showrunner: one shared 32k KV pool (--kv-unified) across 4 slots,
# so short producer requests and one long agent conversation fit together.
cd /hyperai/home
pkill -f llama-server; sleep 3
nohup models/llama.cpp/build/bin/llama-server -m models/qwen/Qwen3.8-27B-Uncensored-IQ4_XS.gguf \
  --mmproj models/qwen/mmproj-Qwen3.8-27B-Uncensored-f16.gguf -ngl 99 -c 32768 -np 4 --kv-unified -fa on \
  --host 127.0.0.1 --port 8080 >> /hyperai/home/loop/llama.log 2>&1 < /dev/null &
for i in $(seq 1 90); do curl -s -m 2 127.0.0.1:8080/health | grep -q ok && { echo "Qwen up after ${i}x2s"; exit 0; }; sleep 2; done
echo "Qwen did not come up"; tail -20 /hyperai/home/loop/llama.log; exit 1
