# Pipeline plan: three channels on air, then one shared spine

Date: 2026-11-07. Inputs: `reports/channel-pipeline-survey.org`, `studio/` (Mychal's `producer_loop.py` + `channel_worker.py`),
`lang/` + `deploy/box/` (#59, #60), `docs/PLAN.md`, issue #50, `worker/src`.

## * Verdict

Fastest path first: **copy the loop pair that already works** (Mychal's always-on producer + worker: queue ahead, small
blocks, publish through `newsbot.publish`, flush partial blocks, skip on failure; the Worker fails over on a stale
manifest to the replay pool). Run each channel's pair as systemd services: AI-247 and Lingua on griffith
(`/srv/channels`, `deploy/box/install.sh`), Puddle Park on Mychal's HyperAI GPU box. GitHub cron per channel stays on as
the backstop until that channel's loop has been fresh for 24 h, then it is turned off.
Only after all three are on air do we move them onto one **job-folder node contract** (`node.yaml` + `result.json`,
channel = YAML graph) with **one DBOS runner per host** (survey verdict; Huey as fallback). Port AI-247 first (simplest),
then Lingua, then Puddle Park. Install stays portable so channels can move from griffith to HyperAI later.
Issue #50 fixes and better nodes come last, in Phase 2.

Acceptance test used everywhere: **`/healthz` fresh < 1 h, checked every 10 min for 24 h** (no gaps).

## Current state (2026-11-07)

| Channel | Producer today | Playout | Status |
|---|---|---|---|
| AI-247 (news) | GitHub Actions `hourly.yml`, one bulletin per hour | Worker `worker/src` on R2 `ai247-media`, replay pool `replay-pool.yml` | On air |
| Puddle Park (preschool) | `studio/pipeline` loops on Mychal's HyperAI GPU box | Worker `puddle-live` (prefix `puddle/`), player `puddle-park-tv.pages.dev` | Loops stopped: need Mychal's restart against bucket `ai247-media` (#56) with Trevor-scoped R2 keys |
| Lingua (Latin/Greek/Hebrew) | GitHub Actions `lang-channel.yml`, every 4 h | Worker `lang-live`, page `ai-247.pages.dev/lang` | On air (v0); griffith `/srv/channels` install from #60 waits for R2 keys |

## Phase 0: all three on air (target: this week)

Owner: Trevor (keys, griffith), Mychal (HyperAI), Claude sessions (code, checks).

- [ ] Trevor: put R2 keys (scoped to `ai247-media`) in `/srv/channels/lang/r2.env` on griffith; run `install.sh lang`.
- [ ] Add an `ai247` target to `deploy/box/install.sh`: `ai247-producer` + `ai247-worker` user units, same shape as Lingua
      (producer fetches feeds and writes scripts ahead into `inbox/`, worker renders 60 s blocks and publishes).
- [ ] Trevor: `install.sh ai247` on griffith; Anthropic key in `/srv/channels/ai247/env` (mode 600).
- [ ] Mychal: restart `producer_loop.py` + `channel_worker.py` on HyperAI with bucket `ai247-media`, prefix `puddle/`
      (Trevor sends an R2 token scoped to the bucket).
- [ ] Replay pools for all three prefixes (`replay-pool.yml`: root, `puddle/`, `lang/`); confirm each Worker fails over to it.
- [ ] Per channel, after 24 h fresh: turn off its cron (`hourly.yml`, `lang-channel.yml`; keep `workflow_dispatch`).

Acceptance: each of `/healthz` on the AI-247 Worker, `puddle-live`, `lang-live` fresh < 1 h for 24 h; a forced stop of
one worker shows the replay pool on air within one manifest TTL.
Risks: R2 keys late (blocks griffith + Puddle); griffith reboot without lingering (check `loginctl show-user`); Mychal's
availability; Puddle box shares GPU with other work. Mitigation: Actions cron stays on until the 24 h test passes.
Cost/day: Haiku for AI-247 ~0.3 USD (24 bulletins); Lingua 0 (no LLM); Puddle local LLM on HyperAI (box cost, Mychal's);
R2/Workers within free tier. **~0.3 USD/day.**

## Phase 1: shared spine (next 2-3 weeks)

Owner: Claude sessions (code), Trevor (review/merge), Mychal (HyperAI install + Blender node).

- [ ] Write `docs/NODE-CONTRACT.md`: a node is a command run in a job folder; reads `node.yaml` (name, inputs, params,
      host, timeout, gpu: bool), writes outputs and `result.json` (`status: ok|skip|fail`, outputs, seconds, cost_usd, log).
- [ ] `pipeline/run.py`: one DBOS runner per host; reads a channel YAML, runs nodes as durable steps, `gpu` queue with
      concurrency 1, failure = skip block (same rule as today), publish node always last.
- [ ] Port AI-247 nodes; run beside the old loop on a test prefix for 24 h; then swap.
- [ ] Port Lingua; same 24 h shadow then swap.
- [ ] Port Puddle Park on HyperAI; same shadow then swap.
- [ ] `install.sh` takes `--host`; no host paths in code or YAML, so a channel moves griffith -> HyperAI by reinstalling.
- [ ] Blender node on the GPU box (visuals for Puddle, later backdrops for the others), 600 s timeout in the node, not the loop.

Acceptance: each channel's 24 h `/healthz` test passes on the runner; one node swapped (e.g. TTS) by editing only YAML.
Risks: DBOS SQLite on a busy box; contract churn while porting (freeze it after AI-247); Puddle port touches the
security model in `studio/README.md` (root reads only through `read_eng_file`). Cost/day: unchanged, ~0.3 USD.

## Phase 2: swap and improve (after Phase 1)

Owner: Claude sessions + Mychal for box items.

- [ ] Issue #50 blocking item first: `engineer_loop.py` reads `review.md` through `O_NOFOLLOW` (`read_eng_file`).
- [ ] Rest of #50: R2 keys only in the boto3 client, content filter on `channel direct`/`order`, scoped `check_imports`,
      safe temp dirs, pinned dsh/Node, exact `pkill`, stream URLs to config, Puddle Worker built from its own source.
- [ ] Better nodes: ComfyUI `image` node, Piper phoneme voices for Lingua, card templates.
- [ ] Per-channel health alert: cron check of each `/healthz`; stale > 30 min posts to Trevor (email/push).

Acceptance: #50 closed; alerts fire in a forced-stale test; 24 h `/healthz` test still green on all three.
Risks: security fixes break the Puddle agents; alert noise. Cost/day: ~0.3-0.5 USD plus any GPU box time.

## Channel YAMLs (Phase 1 target)

```yaml
# channels/ai247.yaml
channel: ai247
host: griffith
prefix: ""
block_seconds: 60
queue_ahead: 3
graph:
  - {node: fetch_feeds,  out: [items.json]}
  - {node: write_script, in: [items.json], out: [script.json], params: {model: claude-haiku-5-5, max_usd: 0.05}}
  - {node: fact_check,   in: [script.json, items.json], out: [script.json]}
  - {node: tts_kokoro,   in: [script.json], out: [voice.wav]}
  - {node: render_cards, in: [script.json, voice.wav], out: [segments/]}
  - {node: publish,      in: [segments/], params: {bucket: ai247-media}}
```

```yaml
# channels/lang.yaml
channel: lang
host: griffith
prefix: lang/
block_seconds: 120
queue_ahead: 4
graph:
  - {node: pick_lesson,  out: [lesson.json]}          # MACULA / OSHB / Vulgate + Whitaker's Words
  - {node: translit_ipa, in: [lesson.json], out: [ipa.json]}
  - {node: tts_piper,    in: [ipa.json], out: [voice.wav]}
  - {node: render_html,  in: [lesson.json, voice.wav], out: [segments/]}   # Chromium + Noto Serif Hebrew
  - {node: publish,      in: [segments/], params: {bucket: ai247-media}}
```

```yaml
# channels/puddle.yaml
channel: puddle
host: hyperai
prefix: puddle/
block_seconds: 60
queue_ahead: 3
graph:
  - {node: showrunner,   out: [episode.json], params: {llm: llama-server/qwen}}
  - {node: content_gate, in: [episode.json], out: [episode.json]}        # #50 filter
  - {node: tts_local,    in: [episode.json], out: [voice.wav]}
  - {node: blender,      in: [episode.json, voice.wav], out: [frames/], gpu: true, timeout: 600}
  - {node: encode_hls,   in: [frames/, voice.wav], out: [segments/]}
  - {node: publish,      in: [segments/], params: {bucket: ai247-media}}
```

## Node table

| Node | Inputs | Outputs | Host |
|---|---|---|---|
| fetch_feeds | feed list | items.json | griffith (any CPU) |
| write_script | items.json | script.json | griffith (Anthropic API) |
| fact_check | script.json, items.json | script.json (or skip) | griffith |
| tts_kokoro | script.json | voice.wav | griffith CPU |
| render_cards | script.json, voice.wav | 6 s HLS segments | griffith CPU (skia + ffmpeg) |
| pick_lesson | corpus files | lesson.json | griffith |
| translit_ipa | lesson.json | ipa.json | griffith |
| tts_piper | ipa.json | voice.wav | griffith CPU |
| render_html | lesson.json, voice.wav | segments | griffith (Chromium + ffmpeg) |
| showrunner | directions, history | episode.json | HyperAI (llama-server) |
| content_gate | episode.json | episode.json (or skip) | HyperAI CPU |
| tts_local | episode.json | voice.wav | HyperAI |
| blender | episode.json, voice.wav | frames/ | HyperAI GPU (queue `gpu`, 1) |
| image (ComfyUI, Phase 2) | prompt | png | HyperAI GPU |
| encode_hls | frames/, voice.wav | segments | HyperAI CPU |
| publish | segments | R2 objects + manifest.json | any (`newsbot.publish`) |
