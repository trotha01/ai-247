#!/bin/bash
export LD_LIBRARY_PATH=/hyperai/home/blibs/root/usr/lib/x86_64-linux-gnu:/usr/local/lib:$LD_LIBRARY_PATH
exec /hyperai/home/blender/blender "$@"
