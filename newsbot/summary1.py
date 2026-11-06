"""Day 1 run report as Markdown (for $GITHUB_STEP_SUMMARY): python -m newsbot.summary1 out1"""
import json
import sys
from pathlib import Path

r = json.loads((Path(sys.argv[1]) / "report.json").read_text())
ru, au, ll = r["runner"], r["audit"], r["llm"]
print("## Day 1 episode run\n")
print(f"- Runner: {ru['cpu_count']} vCPU ({ru['cpu_model']}), {ru['mem_total_mb']} MB RAM, Python {ru['python']}")
print(f"- Episode: **{r['episode_seconds']} s** in {r['segments']} segments; rundown {r['rundown_stories']} stories from {len(r['rundown_sources'])} sources; "
      f"pad {r['plan']['pad_seconds']} s; replay blocks in channel loop: {r['replay_blocks']}")
print(f"- Script by `{r['script_by']}`; TTS `{r['tts_engine']}`")
tp = r.get("topic") or {}
if tp.get("mode") == "topic":
    print(f"- Topic: **{tp.get('name')}** (`{tp.get('id')}`, lane {tp.get('lane')}); primary sources read: {tp.get('fetched_sources')}; "
          f"plan model `{tp.get('plan_model')}`; discovery: {tp.get('discovery')}")
else:
    print(f"- Topic: none (general rundown, mode `{tp.get('mode')}`)")
print(f"- Aired sentences: {au['aired_sentences']}; supported by cited source: **{au['supported_pct']}%**; deterministic grounding: {au['grounded_pct']}%; unsourced items aired: **{au['unsourced_items']}**")
if ll.get("used"):
    print(f"- Claude `{ll['model']}`: {ll['api_calls']} calls, {ll['tokens_in']} in / {ll['tokens_out']} out tokens, "
          f"**estimated cost {ll['cost_usd_estimate']} USD** (cap {ll['max_run_usd']}; {ll['price_in_per_mtok']}/{ll['price_out_per_mtok']} USD per MTok); "
          f"first-pass supported {ll['supported_first_pass']}/{ll['drafted']}, rewritten {ll['rewritten']} (supported {ll['rewritten_supported']}), "
          f"dropped {ll['dropped']}, LLM stories {ll['llm_stories']}, extractive fallbacks {ll['fallback_stories']}, budget abort {ll['budget_abort']}, api error {ll['api_error']}")
    if ll.get("cost_by_kind"):
        print("- Cost by call kind (USD): " + ", ".join(f"{k} {v}" for k, v in ll["cost_by_kind"].items()))
else:
    print("- Claude not used (no ANTHROPIC_API_KEY): extractive script, 0 USD")
print(f"- skia {r['render']['skia_fps_draw_and_readback']} fps draw+readback; pipeline {r['render']['pipeline_fps_incl_encode']} fps incl. encode (30 = real time)\n")
print("| stage | seconds |\n|---|---|")
for k, v in r["stage_seconds"].items():
    print(f"| {k} | {v} |")
print(f"| **total (pipeline)** | **{r['total_seconds']}** |\n")
print("| feed | ok | robots | items | note |\n|---|---|---|---|---|")
for f in r["feeds"]:
    print(f"| {f.get('name')} | {f.get('ok')} | {f.get('robots')} | {f.get('items')} | {f.get('note')} |")
