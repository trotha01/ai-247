#!/bin/bash
if [ "$1" = loop ]; then
  while true; do /hyperai/home/bin/channel serve >> /hyperai/home/loop/channel_service.log 2>&1; echo "$(date +%T) service exited, restarting" >> /hyperai/home/loop/channel_service.log; sleep 2; done
fi
# keeps the root-side channel service up: restarts it within 2 s if it ever exits
pkill -f "channel serve"; pkill -f "run_channel_service.sh loop"
nohup bash /hyperai/home/loop/run_channel_service.sh loop > /dev/null 2>&1 < /dev/null &
