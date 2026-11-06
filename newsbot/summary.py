"""Print the run report as Markdown (for $GITHUB_STEP_SUMMARY): python -m newsbot.summary out"""
import json
import sys
from pathlib import Path

r = json.loads((Path(sys.argv[1]) / "report.json").read_text())
ru, rn = r["runner"], r["render"]
print("## Day 0 bulletin run\n")
print(f"- Runner: {ru['cpu_count']} vCPU ({ru['cpu_model']}), {ru['mem_total_mb']} MB RAM, {ru['os']}, Python {ru['python']}")
print(f"- Script by: `{r['script_by']}`; TTS: `{r['tts_engine']}`" + (f" (fallback: {r['tts_fallback_reason']})" if r["tts_fallback_reason"] else ""))
print(f"- skia: {rn['skia_fps_draw_and_readback']} fps (draw + readback), whole render+encode pipeline {rn['pipeline_fps_incl_encode']} fps (real time = 30)")
print(f"- Segments: {r['segments']}, R2 files uploaded: {r['r2_files_uploaded']}\n")
print("| stage | seconds |\n|---|---|")
for k, v in r["stage_seconds"].items():
    print(f"| {k} | {v} |")
print(f"| **total (pipeline)** | **{r['total_seconds']}** |\n")
print("| feed | ok | robots | items | note |\n|---|---|---|---|---|")
for f in r["feeds"]:
    print(f"| {f['name']} | {f['ok']} | {f['robots']} | {f['items']} | {f['note']} |")
