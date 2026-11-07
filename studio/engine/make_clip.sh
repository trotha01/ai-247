#!/bin/bash
# make_clip.sh scene.json out_dir  ->  out_dir/clip.mp4 (voices + Blender render), timings in out_dir/timing.txt
set -e
SCENE=$1; OUT=$2; HERE=$(cd "$(dirname "$0")" && pwd)
rm -rf "$OUT"; mkdir -p "$OUT"
T0=$(date +%s.%N)
/hyperai/home/venv/bin/python "$HERE/voice.py" "$SCENE" "$OUT" | tee "$OUT/voice.txt"
T1=$(date +%s.%N)
/hyperai/home/bl.sh -b --python "$HERE/puddle.py" -- "$OUT/scene.voiced.json" "$OUT" > "$OUT/blender.log" 2>&1
T2=$(date +%s.%N)
TW=$(python3 -c "import json;d=json.load(open('$OUT/scene.voiced.json'));print(d.get('step', 2 if d.get('on_twos') else 1))")
FPS=$(python3 -c "import json;print(json.load(open('$OUT/scene.voiced.json')).get('fps',30))")
ffmpeg -nostdin -loglevel error -y -framerate $(( FPS / TW )) -pattern_type glob -i "$OUT/frames/*.$(ls $OUT/frames | head -1 | sed s/.*[.]//)" -i "$OUT/voices.wav"   -r $FPS -c:v libx264 -pix_fmt yuv420p -crf 20 -c:a aac -b:a 128k -shortest "$OUT/clip.mp4"
T3=$(date +%s.%N)
python3 -c "print(f'voices {$T1-$T0:.1f}s  render {$T2-$T1:.1f}s  encode {$T3-$T2:.1f}s  total {$T3-$T0:.1f}s')" | tee "$OUT/timing.txt"
