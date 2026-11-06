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
| m3u8 (PyPI) | Day 1: test-only | Parser, not a validator. Day 0 did not use it; Day 1 uses it in `tests/test_seam.py` as an independent parser that must agree with our own on media sequence, discontinuity sequence, URIs and tags. Apple `mediastreamvalidator` is unavailable (macOS-only); Apple `mediastreamvalidator` is unavailable; a small checker in `newsbot/playlist.py` (`check_media_playlist`, `check_continuity` and friends, about 45 lines of the 165-line file before Day 1) covers target duration, media sequence, discontinuity tags and cross-fetch continuity, and is tested. ffprobe validates the media itself. |

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

## Day 2 status

Worker implemented in `worker/` (not deployed). See `docs/DAY2.md` for behaviour, tests, limitations and the deploy checklist.


## Day 1 run results (measured)

Runs on `main` (ubuntu-24.04, public repo, `workflow_dispatch`). Haiku episode: run 42203098918 (`gh run download 42203098918 -R trotha01/ai-247`). Extractive episode: green run 42208582626 (`gh run download 42208582626 -R trotha01/ai-247`; 28 sentences, 19.5 s pad, pipeline 563 s). Its first attempt, run 42203110356, failed only my sentence-count sanity floor. Artifact name `episode-day1`: `episode/` (100 `seg_NNN.ts`, `index.m3u8`, `manifest.json`, `script.json`, `plan.json`, `rank.json`, `report.json`), `slate/` (5 `slate_NNN.ts` + manifest), `episode.mp4` (stream copy for easy playback), `pool.json`, `channel_example.m3u8`.

| Measure | Claude Haiku 5.5 run | Extractive run (no LLM) |
|---|---|---|
| Episode length | 600.0 s, 100 segments (target 600 +/- 15) | 600.0 s, 100 segments |
| Rundown | 11 stories from 7 sources (12 ranked, 1 did not fit the time budget) | 12 stories from 7 sources |
| Aired sentences | 40, **40 supported (100%)**, 40 grounded (100%) | 28, 28 supported (verbatim), 100% grounded |
| Unsourced items aired | **0** | **0** |
| Standby pad at the end | 12 s | 19.5 s |
| Claude cost (estimated from `usage`) | **0.00484 USD** (26 calls, 15,974 in / 6,493 out tokens; cap 0.05; prices 0.10 / 0.50 USD per MTok) | 0 |
| Writer + checker first pass | 49 of 57 drafted lines (headlines included) supported = 86%; 1 rewrite, supported; rejected headlines fall back to the feed title | n/a |
| Pipeline wall-clock | 583 s (fetch 6 s, script 41 s, TTS+plan 194 s, render+encode 322 s, slate 15 s); job about 11 min | 563 s on run 42208582626 (TTS+plan 211 s); 348 s on the earlier run |
| Render under 25 min | yes (hard step timeout 25 min) | yes |
| A/V drift over the 600 s concat | 21 ms (audio starts 21 ms before video, 0 ms offset at the end) | same code path |
| Tests on the runner | 58 passed, 1 skipped | green on run 42208582626 (first attempt failed only my floor of 30 aired sentences, lowered to 20) |

Runner CPU differed between runs (Intel Xeon Platinum 8573C at 65 fps skia draw / 57 fps incl. encode; another run had 105 / 86 fps), so wall-clock varies about 1.7x. Both are far inside the 25 minute limit. Day 0 workflow rerun on Node 24 action majors: run 42197942314 green.

### What the Day 1 build does

- **Ranker** (`newsbot/rank.py`): score = source weight x 0.5^(age/48 h) x small richness bonus, near-duplicate titles removed (token Jaccard >= 0.6 or same URL), at most 2 per source, items with under 60 characters of summary skipped. Pure function, no LLM.
- **Writer** (`newsbot/llm.py`): per story, Haiku writes a headline and 3-5 sentences from that story's source text only. A **separate fresh-context call** (system prompt plus SOURCE and numbered SENTENCES only) gives a supported/unsupported verdict per sentence. Unsupported sentences get one repair round and a full re-check, otherwise they are dropped. A deterministic number/name grounding gate runs on every sentence too, so a lenient LLM verdict cannot air an ungrounded number (unit-tested with a deliberately sloppy checker). A rejected headline falls back to the feed title; a story that ends with under 2 supported sentences, or any API error, falls back to verbatim extractive sentences. Nothing airs without a source card.
- **Cost cap**: before every call the worst case (`max_tokens` all used) is added to spend so far; a call that could cross 0.05 USD is not made, the remaining stories go extractive and `budget_abort` is recorded. No key, or `NEWSBOT_NO_LLM`, or workflow input `llm=off`: extractive path. The key is only exposed to the render step as an env var and is never printed; the job runs only in `trotha01/ai-247` and not from forks (there is no `pull_request` trigger in the episode workflow).
- **Episode** (`newsbot/episode.py`): intro rundown, sources chart, per story headline + one scene per sentence (citation always on screen) + source card, recap, outro, silent standby pad to exactly 600.0 s. Scenes are whole multiples of 0.5 s so frames and audio samples are exact. One H.264/AAC encode split into 6 s HLS segments (closed 2 s GOP, forced keyframes).
- **Slate and pool** (`newsbot/slate.py`, `newsbot/pool.py`): five 6 s slate segments with the same encode settings; the pool keeps the newest episodes (sha256-verified, corrupt ones skipped) and `channel_blocks` always returns at least the slate, so the loop cannot be empty. The workflow downloads up to 3 earlier `episode-day1` artifacts as replays (best effort).
- **Seam tests** (`tests/test_seam.py`): on small real blocks (bulletin, slate, replay) and on the real episode: identical codec/audio parameters; 180 frames and keyframes at 0/2/4 s with a keyframe first; no leading pictures after a keyframe (closed GOP, decode-order check) and the x264 `open_gop=0` SEI in the first segment of each block; strictly increasing DTS and PTS >= DTS per stream; segments inside a block join continuously (video within 2 ms, audio within 30 ms) and block joins, including the loop wrap, do not, so they must carry `EXT-X-DISCONTINUITY`; the playlist generator is checked against the media for three full loops; MEDIA-SEQUENCE never decreases and same sequence number keeps the same URI across the loop; DISCONTINUITY-SEQUENCE counts departed tags (checked against brute force); an independent parser (`m3u8`) agrees; a missing tag is caught.

### Open-source survey (Day 1)

| Piece | Decision | Why |
|---|---|---|
| pysbd | used | Maintained rule-based sentence segmenter (handles "Dr.", "Inc."); regex fallback if missing. |
| feedparser | used (Day 0) | Unchanged. |
| m3u8 (PyPI) | tests only | Parser, validates nothing. Used as an independent parser for the cross-check. |
| Apple mediastreamvalidator / other HLS validators | not used | Apple's tool is macOS-only. I did not find or test a Linux HLS validator, so validity rests on ffprobe facts plus our own checks. This is a gap: the playlists have not been played by hls.js or Safari (Day 3). |
| Entailment models (HHEM, MiniCheck, DeBERTa NLI) | not used | Need PyTorch plus weights from Hugging Face (blocked from the cloud session, so not tried) and add GB-scale install time on a 4 vCPU runner. A fresh-context Haiku check plus deterministic number/name grounding is cheap (0.005 USD per episode). Not benchmarked against those models. |

### Verified facts (what I could and could not read)

- **Verified on platform.claude.com/docs/en/about-claude/pricing (fetched 2026-11-06):** Haiku 5.5 0.10 input / 0.50 output USD per MTok for prompts up to 100k tokens (0.50 / 2.50 above that); Sonnet 5.5 2 / 10. The old Day 0 default of 1 / 5 was Haiku 4.5's price and is gone.
- **Not reachable from the cloud session** (host does not resolve): docs.github.com, www.rfc-editor.org, datatracker.ietf.org, github.blog. Search-engine snippets of docs.github.com are the only evidence for the GitHub items below, so treat them as secondhand, not as a read of the page:
  - 6 hour job limit and 35 day workflow run limit (snippet of the limits page); `timeout-minutes` is 35 for the job and 25 for the render step.
  - Scheduled workflows in public repos are disabled after 60 days without repository activity; forks have them disabled by default (snippet).
  - Shortest cron interval 5 minutes; scheduled runs can be delayed under load and the start of the hour is the busiest, so the test cron uses minute 23 (secondhand: community posts quoting the docs). Observed delay not measured yet, since the cron has not fired on main.
  - Standard Linux runner for public repos: 4 CPU, 16 GB RAM, 14 GB SSD (snippet of the runner reference); observed 4 vCPU / 15,982 MB.
  - Artifact retention default 90 days, 1-90 days for public repos (snippet); we set 14.
  - Terms: the archived 2021 text lists cryptomining and "disproportionate burden" uses such as CDN or serverless apps as misuse; a GitHub staff reply on the community forum said not to use Actions for serverless computing. I found no GitHub text about video rendering. **Public-repo policy for automated media rendering is therefore unverified.** The episode job is a batch render once per trigger, not a delivery service, but a 3-hourly cron that renders 10 minutes of video should be reviewed against the current terms before it runs unattended. The cron can be stopped with the repo variable `DAY1_CRON_ENABLED=false` or `gh workflow disable day1-episode`.
- **RFC 8216:** not reachable. The invariants implemented and tested (discontinuity at each timestamp-sequence/parameter change, MEDIA-SEQUENCE and DISCONTINUITY-SEQUENCE never decrease, DISCONTINUITY-SEQUENCE incremented as tagged segments leave the playlist, TARGETDURATION >= every rounded EXTINF) are from my knowledge of sections 4.3.2.3, 4.3.3.1-4.3.3.3, 6.2.1 and 6.2.2; a search snippet confirmed the two DISCONTINUITY-SEQUENCE rules. The section text itself was not read.
- **Node 24 action majors** read from the actions' public release pages and `action.yml` on 2026-11-06: checkout v7, setup-python v7, cache v6, upload-artifact v7 (all `node24`); they ran green here. The github.blog changelog with the deprecation dates was not reachable.

### Where reality differs (Day 1)

- Real feed summaries are short: 28 verbatim sentences across 12 stories and about 3-4 supported Haiku sentences per story, because the writer may only use the feed text. A full 10 minutes therefore needs a sources chart, recap, source cards and a slightly slower voice (speed 0.92), and still ends with 12-19 s of silent standby. More text per story (article bodies, with robots/terms checks) is the real fix.
- Haiku's first-pass support rate was 86%: the fact check mattered, and the deterministic gate and rewrite round cleaned the rest. The aired 100% is by construction (only supported lines air), so the 95% acceptance number is really measuring the gate; the independent measure is the 86% first-pass rate and the grounding re-check.
- An undrained ffmpeg stderr pipe deadlocked the first local 10-minute render (fine at 60 s in Day 0). Fixed by logging to a file.
- The apt/pip install step hung three times (runs 42197984840, 42205482723, CI 42208590694: 10-27 min with no output after apt finished, i.e. inside `pip install -q`; the job-level 35 min limit was the only bound). Fixed in #12: step `timeout-minutes: 8`, apt `Acquire::Retries=3`/`http::Timeout=30`, `pip --timeout 60 --retries 3` under a 5-minute `timeout`, up to 3 attempts, in day0/day1/ci. Install took 34-38 s on every run since.
- **Post-fix Haiku run 42210163643 (main, defaults: tts kokoro, llm on, 2026-11-06 11:25Z): success.** Install 38 s; episode 600.0 s / 100 segments (target 600 +/- 15); 10 stories aired (12 ranked), 27.5 s pad; 38 aired sentences, 38 supported (100%); fact check 58 drafted, 49 supported first pass (84%), 1 rewritten (supported), 0 dropped, 0 fallback stories; cost 0.00457 USD; pipeline 530 s (script 36 s, TTS+plan 192 s, render+encode 279 s), render step 8 min 50 s of the 25 min limit; tests 58 passed, 1 skipped; artifact `episode-day1` uploaded. R2 upload and `manifest.json` to R2: **no**, day1.yml passes no R2 secrets and `newsbot/day1.py` does not call `newsbot/r2.py` (only the Day 0 bulletin path does); still open.
- HLS segments are separately encoded files, so each block join needs `EXT-X-DISCONTINUITY`; true continuity across files would need timestamp rewriting (not done).
- No R2 upload was exercised (no R2 secrets). Replays come from earlier workflow artifacts.
