# Puddle Park Blender pipeline: benchmark (2026-11-06)

Hardware: HyperAI RTX 3090 24 GB, 8 vCPU, 24 GB RAM, $0.10/h. Blender 5.2.3 LTS, Eevee, 1280x720,
24 fps output animated "on threes" (8 new poses per second), 8 samples, JPEG frames.
Scene: count3_8fps.json (2 felt puppets, set, 3 apples, numerals, 7 voiced lines), 15 s per clip.

## Throughput: N clips rendered at once (render only, voices excluded)

| Clips at once | Wall time | Video made | Video s per wall s | GPU busy | GPU memory |
|---|---|---|---|---|---|
| 1 | 14.5 s | 15 s | 1.04x | 55% | 1.2 GB |
| 2 | 21.0 s | 30 s | 1.43x | 94% | 2.4 GB |
| 4 | 39.9 s | 60 s | 1.50x | 100% | 4.1 GB |
| **6** | 49.9 s | 90 s | **1.80x (best)** | 100% | 6.6 GB |
| 8 | 68.7 s | 120 s | 1.75x | 100% | 9.4 GB |

Limit is GPU compute, not memory (~1.1 GB per render) or CPU.

## Latency: script in -> frames out (one clip)

| Step | Time |
|---|---|
| Blender cold start | 0.68 s |
| Voice model load (Kokoro) | 1.04 s |
| Voice synthesis | 0.74 s first line, ~0.4 s per later line |
| Build scene in code | 0.54 s |
| First frame (Eevee shader compile) | 0.92 s |
| Later frames | 0.11-0.14 s |
| Open same scene from saved .blend (0.4 MB) | 0.02 s, first frame then 0.13 s |
| Append both characters from asset file | 0.03 s |

Time to first frame ~4-5 s; full 15 s clip with voices ~20 s on an idle card.

## Producer (local Qwen3.8-27B Uncensored IQ4_XS on llama.cpp, RTX 3090, thinking off)

| Scenes at once | Valid | Video-seconds of script per second | Tokens/s total |
|---|---|---|---|
| 1 | 1/1 | 0.59 | 45 |
| 2 | 2/2 | 1.21 | 73 |
| 4 | 4/4 | 2.07 | 114 |

18 GB GPU memory with 32k context, 4 slots. Qwen3.8 must run with thinking disabled
(chat_template_kwargs.enable_thinking=false) or it spends the whole token budget reasoning.

## MOSS-Image in ComfyUI (RTX 3090, 1280x720)

| Model | Steps / CFG | Per image |
|---|---|---|
| MOSS-Image SFT INT8 | 25 / 2.5 | 56 s |
| MOSS-Image SFT Turbo INT8 (toxicdog) | 8 / 1.0 | 11 s |

Same quality; both rendered "PUDDLE PARK" text correctly.

## Contention: everything on one RTX 3090 (24 GB GPU, 23 GB RAM)

| Job | Alone | + Blender | All three |
|---|---|---|---|
| Blender, 2 clips at once | 1.43x | 0.95x | 0.98x |
| Qwen, 4 scenes at once | 2.07x | 0.95-1.53x | 1.19x |
| MOSS Turbo | 11 s/img | - | 13 s/img |
| GPU memory peak | - | 20.7 GB | 23.98 GB |
| RAM peak | - | 5.7 GB | 20.6 GB |

Qwen (18 GB) + MOSS kept loaded (13.4 GB) do not fit: MOSS must be unloaded or streamed from RAM.
Everything at once works but at the memory limit; one card ~= one real-time channel with no headroom.
