# ai-247 proof-of-concept plan (rev 4)

Faithful copy of the brief given to the Day 0 worker (Gate A approved by Trevor on 2026-11-06), so later workers can read it from this repo. Section "Reality log" at the bottom is amended with measured facts.

Goal: a website-first PoC of a code-made, 24/7 AI-news channel. No YouTube, no VPS, nothing runs 24/7 in the PoC.

## Architecture (rev 4)

1. A scheduled GitHub Actions workflow in this public repo fetches 8 primary-source feeds (company blogs, release notes, GitHub releases, arXiv; keep 5-8 that work after checking robots.txt/terms).
2. Claude Haiku 5.5 writes short scripts with on-screen source citations, plus a fact-check pass against the cited source.
3. Python + skia-python templates (headline card, scrolling ticker, source-citation card, one bar chart) + TTS + ffmpeg render a bulletin, cut into 6 s HLS segments: H.264 720p30, AAC 48 kHz, closed 2 s GOP, identical codec/audio parameters.
4. Segments are uploaded with a `manifest.json` to Cloudflare R2.
5. A Cloudflare Worker (later days) serves a rolling "fake-live" HLS playlist computed from the clock.
6. A static Cloudflare Pages page plays it with hls.js.

Caps: Anthropic prepaid 20 USD, monthly limit 10 USD, per-run abort at 0.05 USD. Day 0 spends nothing.

## Schedule

- **Day 0**: one `workflow_dispatch`-only Actions run (no cron) renders ONE 60-second bulletin from real feed items as ten 6 s segments plus manifest. Built to work WITHOUT the Anthropic key or R2 secrets: deterministic extractive script (no LLM) as stand-in; Claude Haiku step is a pluggable function that runs only when `ANTHROPIC_API_KEY` exists (never printed or logged); segments uploaded as a workflow artifact (and to R2 only if R2 secrets exist). TTS: Kokoro-82M on runner CPU; fallback espeak-ng/piper if the model cannot be fetched. No rendered media or secrets are committed.
- **Day 1**: Anthropic key + R2 secrets set by Trevor; enable Haiku script + fact-check; upload to R2; hourly bulletin rendering (cron).
- **Day 2**: Cloudflare Worker serving the rolling fake-live playlist from the manifest + clock; bootstrap pool of pre-rendered bulletins so the channel never goes dark.
- **Day 3**: Cloudflare Pages page with hls.js, AI-generated label, source list; end-to-end soak test.

## Day 0 acceptance tests (automated where possible, in `tests/`)

- (a) ffprobe shows H.264 720p30, AAC 48 kHz stereo/mono as chosen, closed 2 s GOP, each segment 6.0 s +/- 0.05.
- (b) 0 numbers or named entities in the script missing from the source text (simple automated check).
- (c) every on-screen claim has a visible source citation card.
- (d) `manifest.json` lists the 10 segments with durations and hashes.
- (e) the playlist checker validates a generated media playlist (target duration, media sequence, discontinuity tags).
- (f) the workflow prints runner CPU/RAM, wall-clock per stage and total (proves the render time budget; also report skia fps on the runner) and amends this file where reality differs (cron granularity, runner specs, job time limit).

## Security rules

Public repo. Never commit keys, tokens, stream keys, account IDs or private notes; never print environment variables; secrets only via `${{ secrets.* }}`. Do not enable Pages, Actions secrets, branch protection or any repo setting; do not purchase anything.

## Design choices made on Day 0 (see Reality log for measured values)

- Bulletin layout (10 x 6 s): segment 1 intro + bar chart (items per source), segments 2-9 = 4 stories x (headline card, source-citation card), segment 10 outro. A scrolling ticker (each entry tagged with its source) and an "AI-GENERATED" badge are on every segment.
- Encode once, then split with ffmpeg's HLS muxer (`-hls_time 6`, keyframes forced every 2 s, `independent_segments`) so segment cuts land on closed-GOP boundaries and timestamps stay continuous.
- Audio: mono, 48 kHz AAC 96 kbit/s (Kokoro outputs 24 kHz mono).

## Reality log

Measured on Actions run 42187611180 (`workflow_dispatch`, branch `cloud/ai247-day0`, ubuntu-24.04, public repo). Values below are measured unless marked *from memory*.

## Open-source survey (Day 0 search, what was used and why)

| Piece | Decision | Why |
|---|---|---|
| feedparser 6 | used | Maintained, handles RSS/Atom quirks; GitHub releases use the REST API (JSON) instead. |
| skia-python | used | Installs from a wheel (v144.1); needs `libegl1 libgl1 libfontconfig1` on Ubuntu; ~59 fps draw+readback on 4 vCPU. Pillow not needed. |
| Kokoro-82M via kokoro-onnx | used | `kokoro-onnx` runs the int8 ONNX model on CPU. Model files come from the kokoro-onnx GitHub release (huggingface.co is blocked from the cloud-session network, GitHub releases are not). The reference `kokoro`+`misaki` package pulls PyTorch and the weights from Hugging Face, so it was not used. |
| espeak-ng | fallback TTS | apt package, robotic but dependable. Piper was not needed. |
| ffmpeg HLS muxer | used | `-f hls` with forced 2 s keyframes and `independent_segments` cuts the single encode on closed-GOP boundaries. No other muxer library required. |
| hls.js | later (Day 3) | Standard player; not needed until the Pages site. |
| m3u8 (PyPI) | not used | Apple `mediastreamvalidator` is unavailable; a ~60-line checker in `newsbot/playlist.py` covers target duration, media sequence, discontinuity tags and cross-fetch continuity, and is tested. ffprobe validates the media itself. |

## Notes on Day 0 choices

- Segment duration is defined as the video-stream duration (equals EXTINF, 6.000 s). The audio stream inside a single `.ts` and the container span differ by a few AAC frames because the HLS muxer interleaves audio across the cut; concatenated, video is 60.000 s and audio is ~59.9 s. Tests allow container span +/-0.10 s, audio +/-0.5 s per segment (first segment measured 5.63 s on the runner), and 60 s +/-0.3 s overall.
- Sandbox network note: from the cloud session only PyPI, anthropic.com and GitHub release downloads were reachable, so feeds could not be verified there. Feed robots.txt/availability is therefore checked at run time on the Actions runner and reported per feed (see the job summary).

### Day 0 run results (measured)

- Runner: 4 vCPU (AMD EPYC 9V74), 15,983 MB RAM, Linux azure kernel, Python 3.12.16, ffmpeg 6.1.1 installed by apt (it was not preinstalled in a usable form; ~36 s install stage including libs and pip).
- Wall-clock: job 115 s end to end. Pipeline stages: fetch feeds 4.6 s, script 0.0 s, TTS 26.9 s (includes a one-off 120 MB Kokoro model download from GitHub; the workflow now caches `models/`), render+encode 28.7 s, manifest 0.5 s, total pipeline 60.6 s. One 60 s bulletin therefore renders in about 1x real time, well inside any hourly budget.
- skia-python: 71.1 fps draw + readback at 720p on the runner; the whole render+x264 pipeline ran at 62.8 fps (2.1x real time).
- Feeds (9 candidates tried, first 8 working used, all robots.txt "allowed"): OpenAI, Google AI, Hugging Face, NVIDIA Developer, Microsoft Research, arXiv cs.AI, Claude Code releases (GitHub API), Anthropic Python SDK (GitHub API). Google DeepMind's feed parsed but returned no items. Anthropic has no official news RSS. 105 items fetched.
- TTS: Kokoro (int8 ONNX via kokoro-onnx) worked on the runner. No fallback needed there. From the cloud sandbox huggingface.co and docs.github.com were blocked, so docs could not be read from there.
- All 25 acceptance tests passed on the runner, including (a)-(e). (f) is this section.
- Artifact: `bulletin-day0` on the run page (14-day retention): ten `seg_NNN.ts`, `manifest.json`, `index.m3u8`, `script.json`, `plan.json`, `report.json`.

### Where reality differs from the brief or needs checking

- A workflow must exist on the default branch before it can be dispatched via the API (404 otherwise), so Day 0 needed one merge to `main` before the first run.
- GitHub docs were not reachable from the cloud session, so these are *from memory, verify on docs.github.com*: scheduled workflows run at most every 5 minutes and can be delayed or dropped under load, so "hourly" cron is fine but not exact; scheduled workflows in public repos are disabled after 60 days without repo activity; GitHub-hosted jobs have a 6-hour limit (set `timeout-minutes` lower, currently 20); standard runners in public repos are 4 vCPU / 16 GB (matches observed).
- Anthropic per-run cap uses assumed prices (`NEWSBOT_PRICE_IN/OUT` default 1/5 USD per million tokens); verify real Haiku 5.5 prices before Day 1.
- GitHub Actions marks Node 20 actions deprecated (warning only); bump action versions on Day 1.
