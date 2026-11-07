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

## R2 upload verified (2026-11-06)

Day 1 had no R2 upload until PR #18 (`newsbot/publish.py`, step "Publish to R2" in `day1.yml`, run after the render's tests, skipped with one log line when the `R2_*` secrets are absent). Layout: `docs/R2_LAYOUT.md` (B) with the continuity fields of `docs/MANIFEST-SWAP.md`. The Day 0 path (`newsbot/r2.py: upload`) also ran once with the real secrets: run 42211796435 (day0-bulletin on main), `r2_upload` stage 18.4 s, 53 tests passed, Day 0 layout `bulletins/<ts>/` with `manifest.json` before the segments (unchanged, not used by the Worker).

| Run (day1-episode on main) | Keys written, in order | Objects / bytes | Publish time |
|---|---|---|---|
| 42212912268, `llm=off` (extractive, 28 sentences, 100% grounded, 75 tests passed) | `bulletins/20261106T115430Z/seg_000.ts` .. `seg_099.ts` (`video/mp2t`), `bulletins/20261106T115430Z/manifest.json`, `bulletins/20261106T115430Z/slate/slate_000.ts` .. `slate_004.ts`, `.../slate/manifest.json`, then root `manifest.json` (`application/json`, one PutObject, last) | 108 / 34,139,323 | 116 s (render pipeline 326 s, install 31 s) |
| 42214045472, `llm=on` (Claude Haiku 5.5 + fact check: 60 drafted, 48 supported first pass, 3 rewritten, 41 aired, 100% supported; cost 0.00495 USD, 30 calls; 75 tests passed) | same shape under `bulletins/20261106T120928Z/` (100 `seg_NNN.ts`, block `manifest.json`, 5 slate segments + `manifest.json`), then root `manifest.json` last | 108 / 33,533,180 | 91 s (render pipeline 583 s, install 87 s) |

Root manifest after run 1: `epoch` 1793000000 (= the Worker's `EPOCH` var), `cycle_start_k` 161021, `cycle_start_dseq` 0, blocks `[bulletin 20261106T115430Z (100), slate (5)]`, no `prev` (first publish). Run 2 read that manifest back from R2 (`current root manifest: cycle_start_k=161021 blocks=2`) and published `cycle_start_k` 161231 (= 161021 + 2 x 105, the next loop boundary of the old cycle with 10 segments of margin), `cycle_start_dseq` 4 (two loops x two block starts), blocks `[bulletin 20261106T120928Z (100), slate (5), replay 20261106T115430Z (100)]` and `prev` = the run 1 manifest, so the Worker can swap at the boundary without the media or discontinuity sequence going backwards. The replay's 100 segments were not re-uploaded. Nothing was deleted or overwritten. Both runs' logs list every key written, in order, with its content type and size.

Live endpoint: the Worker went live at `https://ai247-live.trotha01.workers.dev` during this work (PRs #19-#23, `deploy.yml`). That host and `ai-247.pages.dev` are blocked from the cloud session's network, so the read-only check comes from the deploy workflow's smoke test on the Actions runner (run 42215042026, 12:07Z, between the two publishes): `/healthz` ok (`source=live-manifest`), `/live.m3u8` starts with `#EXTM3U`, CORS `*`, media-sequence 161138 rising to 161139, and it fetched `seg/bulletins/20261106T115430Z/seg_012.ts` as `video/mp2t`, 295,536 bytes, exactly the key and size run 1's publish log recorded (161138 - 161021 = 117 = one loop of 105 plus 12, so the Worker was 12 segments into the second loop of run 1's cycle). Each run's `episode-day1` artifact includes `publish.json` with every key in order.

## Replay pool seeded and scheduled (2026-11-06)

Before this, `/healthz` on `ai247-live` reported `pool.problem: "missing: pool/manifest.json is not in the bucket"` (checked from the cloud session at 13:04Z: this host was reachable from the sandbox this time, so the checks below are direct reads of `/healthz`, not the deploy log). Run 42222599138 of `replay-pool` on main (`source=r2`, `max_blocks=2`, publish step 51 s) wrote `pool/manifest.json`: 2 blocks, 200 segments, built from `bulletins/20261106T120928Z/` and `bulletins/20261106T115430Z/` (the two Day 1 publishes above), epoch 1793000000 (`epoch_mismatch: null`). At 13:06Z `/healthz` showed `pool.ok: true` with `source` still `live-manifest`.

Kept running without a human (`docs/FAILOVER.md`, "Schedule and refresh guard"): `replay-pool` now also runs daily at 04:41 UTC and refreshes the pool from the two newest complete episodes; `newsbot/replay_pool.py` refuses to replace a good pool with an empty one, writes nothing when no complete episode exists, and skips the PutObject when the pool already lists the newest episodes. `worker/wrangler.toml` `MAX_MANIFEST_AGE_S` went from `0` to `14400`, so a live `manifest.json` older than 4 h (one missed 3-hourly `day1-episode` run plus slack) fails over to the pool and returns when a fresh manifest lands.

## Topic research stage (2026-11-06)

Each episode now researches one topic instead of digesting the 8 feeds: `topics/topics.json` (editable lanes; a
web-searching discovery call on Claude Fable 5.1 may add topics, no daily cap), the episode history in Cloudflare D1
(`newsbot/history_db.py`, dedupe; nothing committed), `newsbot/topics.py`, `newsbot/research.py`, `newsbot/discovery.py`. Design, settings and the first measured
episode (run 42229528561: topic `agent-harnesses`, 8 stories from 5 sources, 0.00586 USD) are in `docs/TOPICS.md`.
Topic episodes run on `day1-episode` dispatches (`mode=feeds` or repo variable `DAY1_TOPIC_MODE=off` restores the
digest); the hourly cadence below renders its slices with topic mode off. Measured with Fable 5.1 plan + web-searching
discovery: 0.32 USD per topic episode (run 42238216216, `docs/TOPICS.md`).

## Hourly cadence: >= 60 min of new footage per run (2026-11-06)

Trevor's rule: if the cron dispatches once an hour, each hour must produce at least an hour of new footage (produced minutes >= cadence minutes), so the channel never repeats old footage because the new footage is too short. Branch `cloud/ai247-coverage`.

### Measured before the change (runs 42235237153, 42214045472, 42229528561 on `main`)

| Measure | Value |
|---|---|
| Footage per run | 600 s (one 10-minute episode, 100 x 6 s) every 3 h on the old cron = 10 min per 180 min of cadence |
| Render minutes per minute of footage | pipeline 376-594 s per 600 s of footage = **0.63-1.0 min per footage minute** (TTS+plan 107-211 s, render+encode 214-322 s at 57-86 fps incl. encode, script 35-41 s with Haiku, fetch 5-6 s, slate 10-15 s); 15-min bulletins would run 9-15 min, 20-min bulletins 13-20 min: fine on a fast runner, inside the 25-minute render limit only with margin on a slow one |
| Limits | render step `timeout-minutes` 25, job 35 (GitHub max 6 h per job; the cadence, not the limit, is the binding constraint); public-repo standard runners 4 vCPU / 16 GB, up to 20 concurrent jobs |
| R2 publish | 108 objects / 33 MB in 91-144 s **sequential** (about 1.3 s per PutObject) |
| Claude cost | 0.0046-0.0050 USD per 10-minute Haiku episode (26-30 calls); per-process cap 0.05 USD |
| Content supply | 110 items from 8 feeds (15 per feed, the parser's limit; Microsoft Research 10, Claude Code releases 10), 12 ranked, 10-11 aired per episode; feeds refresh slowly (a few new items per hour) |
| Schedule | 0 `schedule` runs ever for `day1-episode` (cron `23 */3`); manual runs work (cron worker, PRs #25 and #30) |

### Design chosen: six 10-minute bulletins per hour, rendered in parallel, aired fresh-first

Cheapest path that meets the rule with the tested 10-minute unit (test suite, 600 s target, 25-minute limit) and no new infrastructure:

- **`hourly-bulletins` workflow** (`.github/workflows/hourly.yml`, cron `23 * * * *`): job `plan` fetches every working candidate feed once (`newsbot/hourly.py`), pushes stories that already aired to the back (aired-URL memory = `sources` of the newest 150 `bulletins/<id>/manifest.json` in R2), de-duplicates, and deals 14 stories per slice (at most 4 per source) into up to 6 slices; job `render` is a matrix of one 10-minute bulletin per slice (`newsbot.day1 --items-json`, unchanged pipeline, 6 jobs in parallel, each 6-15 min); job `stitch` publishes all rendered bulletins in slice order as the fresh blocks of one root manifest (`newsbot.publish --run-ts`, uploads 12 in parallel) and writes the footage minutes, cost and novelty to the job summary. A failed slice does not stop the others (`fail-fast: false`, stitch runs `if: always()`); fewer than 60 minutes is a `::warning::`, not a red run. The `day1-episode` cron was removed (dispatch only): a second cron would only add spend.
- **Worker: fresh footage first** (`loop_from` in `manifest.json`, docs/MANIFEST-SWAP.md): the fresh blocks play exactly once from `cycle_start_k`, then slate + the previous hour's six bulletins loop until the next publish. The swap rule became block-granular: a new manifest starts at the end of the old fresh region if that is still ahead (nothing fresh is cut), otherwise at `k + margin` inside the replay loop (tagged, continuous); a pending manifest's fresh blocks are inherited instead of dropped. Legacy manifests keep the loop-boundary rule. Same math in `worker/src/playlist.js` and `newsbot/channel.py`, cross-checked on generated vectors (`worker/test/fixtures/swap-v3-golden.json`); hls-parser simulations in `worker/test/unit/swap.test.js` show every fresh segment of on-time runs airs once, in order, with monotonic sequences and stable URIs, and that a late run plays replays only for the gap.
- **Cost guard**: only the first `HOURLY_LLM_SLICES` bulletins per run (repo variable, default 1) use Claude Haiku; the others are extractive (0 USD). The 0.05 USD per-process cap is unchanged.

| Setting | Claude spend | GitHub |
|---|---|---|
| default, 1 Haiku slice of 6 | 24 x 0.005 = **0.12 USD/day, ~3.6 USD/month** (inside the 10 USD monthly limit) | 24 runs x (plan 2 min + 6 x ~12 min + stitch 5 min) = ~80 job-minutes/hour, free for a public repo; 6 concurrent jobs of the 20 allowed |
| 2 Haiku slices | 0.24 USD/day, ~7.2 USD/month | same |
| all 6 Haiku | 0.72 USD/day, ~22 USD/month: **needs Trevor to raise the cap** | same |
| PR #29 topic stage (Fable plan + web-search discovery) per slice | 0.15-0.30 USD per bulletin: not enabled on the hourly path (`NEWSBOT_TOPIC_MODE=off`); 1 topic slice per hour would be 3.6-7.2 USD/day | |

### Honest limit: new footage, not always new stories

The 8-14 feeds supply about 110-200 items (now up to 60 arXiv items per fetch) and refresh by a few items per hour, while 60 minutes of bulletins need about 60-70 stories (Haiku, 3-5 sentences each) or more (extractive). The planner therefore spends the never-aired stories first, spread over the hour's slices, and fills the rest with the stories aired longest ago, re-narrated and re-rendered; the job summary counts `never aired` per slice. Genuinely new content per hour needs more source text (PR #29's research stage reads primary pages; more feeds), which is outside this item.

### Verification runs

**Run 1: 42252356577** (`workflow_dispatch` on `main` 9d5ec65, 16:26:13Z, defaults: 6 slices, `HOURLY_LLM_SLICES` 1). Whole run 14 min (16:26:13 to 16:40:11Z).

| Stage | Measured |
|---|---|
| plan | 17 s job: install 3 s, fetch 200 items from 12 working feeds in 6.8 s (Google DeepMind and llama.cpp returned no items), aired memory 6 manifests / 20 URLs in 1.4 s, 142 candidates, **128 never aired**, 6 slices x 14 stories (6-7 sources each, <= 4 per source), run_ts `20261106T162623Z` |
| render x 6 (parallel) | install 31-75 s; render step 8 min 12 s to 11 min 49 s (pipeline 492 s on slice 1: TTS+plan 207 s, render+encode 268 s at 68 fps incl. encode; 52-65 fps on the slower runners, six encodes ran at once); tests 11-15 s; artifact 31 MB per slice. Every rendered bulletin was 600.0 s / 100 segments with 100% supported and grounded sentences (slice 1: 11 stories, 30 sentences, 15.5 s pad). |
| what went wrong | slices 0, 2, 3 failed only `test_rundown_10_to_12_stories` with **9 stories** (the Day 1 floor; the longer arXiv abstracts and release notes make a story about 70 s, so 9 fill 600 s), so three complete bulletins were not published; slice 5 hit the known install stall (step timeout after 8 min, before any render). |
| stitch | download 4 s; **publish 22.3 s for 209 objects / 67.6 MB** (12 parallel uploads; 108 objects took 91-144 s sequentially before); root manifest `cycle_start_k` 163981 (the loop boundary of the legacy manifest then live = 16:51:26Z), `cycle_start_dseq` 41, `loop_from` 2, blocks [bulletin x2, slate, replay x4 (150835Z, 144236Z, 140715Z, 120928Z)], `rendered_minutes` 20.0 -> `::warning::` (target 60); `/healthz` ok, `source=live-manifest`, `manifest.uploaded` 16:40:04Z, 605 segments / 7 blocks |
| coverage | **20 min of new footage: below the target**, because of the floor above, not the pipeline. Fix: `NEWSBOT_MIN_STORIES` (default 10 keeps day1-episode as it was; the hourly slices pass 6). |
| cost | slice 0 was the Haiku slice and was rejected by the floor; the published bulletins were extractive (0 USD). |
| cron | the file reached `main` at 15:47Z; the 16:23Z slot produced no run (the Day 1 cron also missed its first slot). Watch 17:23Z. |

**Run 2: 42255030016** (`workflow_dispatch` from `cloud/ai247-coverage` a8f24ef with the floor fix, 16:43:31Z to 16:56:40Z, 13 min).

| Stage | Measured |
|---|---|
| plan | 20 s job; the aired memory now knew run 1's stories (it read 8 manifests), 6 slices again |
| render x 6 | slices 0, 3, 5: install 31-40 s, render 6 min 10 s to 10 min 44 s, **all tests passed with the floor of 6** (slice 3 had passed the old floor too); slices 1, 2, 4: **install stall** again. In slice 2's log apt took 3 min 13 s (16:44:05 to 16:47:18) and `pip install` then printed nothing for 5 min until the 8-minute step timeout, so no second attempt ever ran. |
| stitch | 3 bulletins, **310 objects / 96.8 MB in 40.0 s**; root manifest `cycle_start_k` **164181 = run 1's fresh end (163981 + 200)**, i.e. the swap rule let run 1's two bulletins finish before run 2's three start; `cycle_start_dseq` 43, `loop_from` 3, 10 blocks (3 fresh, slate, 6 replays incl. run 1's two bulletins), `rendered_minutes` 30.0 -> `::warning::`; `/healthz` 905 segments / 10 blocks, uploaded 16:56:37Z |
| coverage | **30 min**: the floor fix worked, the install stall took the other three slices. Fix: install step 20 min with every stage bounded (apt 120 s each, pip 200 s with a 20 s socket timeout and 2 retries) so a second and third attempt always fit; render job 50 min; the same guard in `ci.yml`'s two install steps, which stalled three times today as well. |
| on air | run 1's swap verified from this session at 16:51:33Z: media sequence 163978 continuous, `EXT-X-DISCONTINUITY-SEQUENCE` 41 = the published anchor, the last three replay segments then `20261106T162623Z-00/seg_000.ts`; headless Chromium on https://ai-247.pages.dev played through it (state `live`, 12.0 s of video in 12 s, segments from both prefixes fetched with 200, 0 errors). |

**Run 3: 42256733605** (`workflow_dispatch` from `cloud/ai247-coverage` fd38108 with the install fix; queued 16:54:40Z behind run 2 in the shared concurrency group, started 16:56:44Z, done 17:11:38Z: **15 min**).

| Stage | Measured |
|---|---|
| plan | 20 s; 6 slices |
| render x 6 | **all six succeeded**: install 35-46 s on every job (no stall this time; the fix only mattered for the budget), render step 9 min 41 s to 11 min 41 s, tests 15-17 s. Slice 0 (the Haiku slice): 12 stories written, 8 aired (long sources), 36 sentences, 100% supported and grounded, 26 calls, **0.00583 USD** (write 0.0022, check 0.0036, repair 0.0001), pipeline 700 s (script 41 s, TTS+plan 282 s, render+encode 353 s at 51.7 fps incl. encode on an AMD EPYC 9V74 runner). Slices 1-5 extractive, 0 USD. |
| stitch | download 10 s; **6 bulletins, 613 objects / 195 MB published in 80.3 s**; the manifest in R2 (run 2's) had not started yet (its start 164181 = 17:11:26Z, publish at 17:10:13Z), so its 3 fresh blocks were **inherited** in front of ours: `cycle_start_k` 164181, `cycle_start_dseq` 43, `loop_from` 9, 16 blocks (9 fresh = 90 min, slate, 6 replays), `rendered_minutes` **60.0** -> coverage check passed, no warning; `/healthz` 1505 segments / 16 blocks, uploaded 17:11:31Z |
| on air | at 17:12:38Z the playlist was at media sequence 164189, `EXT-X-DISCONTINUITY-SEQUENCE` 44, playing `20261106T164342Z-00/seg_008..012` (run 2's first bulletin, started on schedule at 164181 under the new manifest); headless Chromium on pages.dev: state `live`, 12.0 s of video in 12 s, 5 segments of that prefix fetched with 200, 0 errors |
| cost | 0.00583 USD for the run (one Haiku slice): **0.14 USD/day, 4.2 USD/month at 24 runs**, inside the 10 USD monthly limit |

### Result

Trevor's rule holds on the run with the fixes: **60 min of new footage per hourly run** in 15 min of wall-clock (plan 20 s, six 10-minute renders in parallel 10-12 min each, stitch 1.5 min), published in one root manifest that the Worker plays fresh-first; two earlier runs showed the two failure modes (the Day 1 story floor and the install stall) and both are fixed in PR #34. The feed supply still does not give 60 min of never-aired stories per hour (see "Honest limit"): run 1 had 128 never-aired candidates right after the switch, later hours will mostly re-narrate the stories aired longest ago until more source text is added.

Cron: the `hourly-bulletins` file reached `main` at 15:47Z; the 16:23Z slot produced no run. The first `schedule` run was 42298386727 at 21:38Z (see "Schedule trigger" below); the stale-manifest failover (4 h) and the replay loop inside each manifest cover a missed hour without going dark.

## Schedule trigger: proven on the first scheduled run (2026-11-06, run 42298386727)

**First `schedule` event for this repository: `hourly-bulletins` run 42298386727, created 21:38:28Z for the 21:23Z slot (15 min late), on `main` 70b4c1b.** Its Trigger step logged `event=schedule ref=main` and `HOURLY_CRON_ENABLED=<unset>`, so the job-level gate passed. Unattended, the run planned 6 slices (200 feed items, 142 candidates, 45 never aired), rendered 3 of them and the `stitch` job published them: `bulletins/20261106T213836Z-00..02/`, 310 objects / 98.4 MB, root `manifest.json` last at 21:53:28Z (`cycle_start_k` 167006, `cycle_start_dseq` 76, `loop_from` 3, 3 fresh blocks). `/healthz` at 00:59Z next day: `source=live-manifest`, `manifest.uploaded` 2026-11-06T21:53:28.887Z, 905 segments / 10 blocks, pool ok. So the cron fires for this repository and a cron run publishes a new manifest to R2 that the Worker serves.

**The run's conclusion is `failure`**, because 3 of the 6 render slices failed (the stitch publishes whatever rendered, by design):
- slices 0 and 2: `test_rundown_story_count_within_floor_and_12_from_multiple_sources`, `assert 3 >= 4` on distinct sources. Each slice was dealt 14 items from 6-7 sources, rank kept 12 from 5, and the 600 s time budget kept 9 stories, cutting the single-item sources first; both bulletins were full length and 100% grounded. Fixed by making the floor an env var (`NEWSBOT_MIN_SOURCES`, default 4 unchanged for `day1-episode`) and setting it to 3 for the hourly slices, whose planner already mixes sources (the whole run covered 11).
- slice 5: the apt install stall (three bounded attempts of 120-144 s each, no output), the same runner-side symptom seen on `ci` and `day1-episode` all day; the coverage worker's bounded-retry install already handles it when the mirror recovers within the step budget.

**Caveat: the scheduler is still unreliable for this repository.** 0 events for the 12:23Z-18:23Z slots (five slots, `main` pushed seven times meanwhile), then one event for 21:23Z (2 h 38 min after the last push to `main`), then none for 22:23Z, 23:23Z and 00:23Z. Checks that rule out the repo side, from the API and git: every workflow `active`; the gate variable unset (printed by the run itself); every PR merged by `trotha01` and every push run on `main` has `actor` `trotha01`; not a fork, not archived, public, owner type User; concurrency queues rather than cancels. Community reports (#203473, #185355) describe the same silence on brand-new repositories and a GitHub-side regression; the external-cron workaround those posters used is a Cloudflare Cron Trigger (free) on a Worker that POSTs `/repos/trotha01/ai-247/actions/workflows/hourly.yml/dispatches` with a fine-grained PAT (Actions: read and write, this repository) kept as a Worker secret. That needs Trevor's token and decision. Until then the channel gets new footage on whatever slots GitHub honours plus manual dispatches; the 4-hour stale-manifest failover and the replay loop keep it on air.
