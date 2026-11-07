# studio: Puddle Park, a puppet channel that writes and animates itself

**Watch: [puddle-park.pages.dev](https://puddle-park.pages.dev)** (labelled AI-generated).

Puddle Park is a 24/7 felt-puppet channel. A local LLM writes every 15-second scene as it airs, Blender animates it from
code, Kokoro voices it, MOSS-Image paints backdrops and title cards, and the result streams through this repository's
Worker. Nobody pre-writes episodes: the owners steer the producer with short directions, and an AI showrunner and an
AI engineer handle the rest. It is the first channel of a planned "make your own channel" platform; the preschool
theme is just the simplest test of the animation pipeline.

It reuses ai-247's streaming half unchanged: `newsbot/publish.py` + `newsbot/channel.py` (uploader and manifest swap)
and `worker/src` (the HLS Worker), with every R2 key under the prefix `puddle/`.

## How it fits together

```
 owners ─ tools/direct.sh, tools/approve.sh ─┐                    guests (password) ─ studio page ─┐
                                              v                                                     v
 ┌──────────────────────────── GPU box (HyperAI, 1x RTX 3090, Hong Kong) ─────────────────────────────────────┐
 │  Qwen 3.8 27B (llama.cpp, :8080) ◄── producer, showrunner, engineer all share this one model               │
 │                                                                                                            │
 │  producer_loop ──scene JSON──► inbox/ ──► channel_worker: voice.py ─► Blender puddle.py ─► ffmpeg ─► HLS ──┼──► R2 puddle/
 │      ▲ brief.md + standing directions        │  (renders as user "render"; MOSS windows between blocks)    │       │
 │      │                                       └─ backdrops.py: MOSS image library (backdrops, title cards)  │       ▼
 │  showrunner (dsh web, user "show") ── channel (root service, per-user permissions) ── proposals/          │   Worker aitv-live
 │  engineer (dsh headless, user "eng"): builder + reviewer ── eng-test ── submit ──► owner approves ──► actions/live/  │   (worker/src)
 └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘       ▼
   gate.js (password, user "gate") ◄── Cloudflare quick tunnel ◄── showrunner-link Worker (fixed link)         puddle-park.pages.dev
```

| Part | Folder | Runs | What it does |
|---|---|---|---|
| Engine | `engine/` | box | `puddle.py` builds the felt set and four puppets (each its own silhouette) in Blender and animates a scene script; `voice.py` voices it with Kokoro and drives lip sync; plug-in actions extend it |
| Producer | `pipeline/producer_loop.py` | box | Qwen writes the next scenes (JSON schema), repaired so the engine can play them; keeps 8 queued; reads `brief.md`, standing directions, the image library and approved plug-in actions every round |
| Render worker | `pipeline/channel_worker.py` | box | 4 scenes at a time → 1-minute block → 6 s HLS segments → R2 via `newsbot.publish`; title cards; keeps the bucket under 8 GB; opens MOSS windows between blocks |
| Image library | `pipeline/backdrops.py` | box | MOSS-Image Turbo in ComfyUI makes ordered backdrops (1792x512 panoramas) and title cards, text encoder on CPU, then stops ComfyUI to give the GPU back |
| Showrunner | `showrunner/` | box | A dsh (DeepSeek harness) web agent people chat with; watches what is on air and steers the producer only through the `channel` command |
| Studio page | `showrunner/gate.js` | box | Password page; one screen with the live channel, the standing directions, the latest scenes, new-action requests and the chat |
| Engineer | `engineer/` | box | Builds requested actions as plug-ins: a builder writes and test-renders (`eng-test`), a fresh reviewer looks at the frames and submits or sends it back |
| Stream + page | `cloudflare/` | Cloudflare | `aitv-live` deploys this repo's `worker/src` with `PREFIX=puddle/`; `puddle-site` is the player page; `showrunner-link` redirects a fixed URL to the current tunnel |

## Day-to-day (owners)

One-time: copy `.env.box.example` to `.env.box` (git-ignored) and put in how you SSH to the box.

```bash
studio/tools/direct.sh "Leave at most one second of silence between lines"   # steer the producer
studio/tools/direct.sh                                                          # directions, recent scenes, health
studio/tools/approve.sh                                                         # new-action requests and their status
studio/tools/approve.sh 20261107-013244-wren_can_spin                           # approve one (look at its preview first)
studio/tools/deploy.sh --restart                                                # put this checkout's code on the box
```

Everything the showrunner can do is the `channel` command (`showrunner/channel`, run `channel` for the list).

## Where things live on the box

`deploy.sh` copies the repo to these paths (historic names; the `kids-test` folder predates this repo):

| Repo | Box |
|---|---|
| `engine/*`, `pipeline/*` | `/hyperai/home/kids-test/blender/` |
| `showrunner/channel`, `engineer/eng-test` | `/hyperai/home/bin/` |
| `showrunner/*` | `/hyperai/home/showrunner/` (dsh state of the agent: `/hyperai/home/show`) |
| `engineer/*` | `/hyperai/home/engineer/` (agent's own folder: `/output/eng`) |
| `box/*.sh` | `/hyperai/home/loop/` (and `bl.sh`, `install_dsh.sh` in `/hyperai/home/`) |
| channel data (not in git) | `/hyperai/home/loop/puddle/`: `inbox/ done/ failed/ library/ proposals/ actions/live/ producer/{brief.md,notes.md,history.jsonl}` and the logs |

Only `/hyperai/home` survives a container restart (it is a link to `/output`; dsh keys workspaces by the real path).
After a restart nothing starts by itself yet: `run_llama.sh`, `run_channel_service.sh`, `run_producer.sh`,
`run_worker.sh --block 4 --renders 4`, the engineer loop and `showrunner/start_showrunner.sh` (one boot script is a TODO).

## Security model

The showrunner page is public behind one password, and the agents can run shell commands, so:
- Each agent runs as its own unprivileged Linux user (`show`, `eng`), the password page as `gate`, Blender renders as
  `render`. None can read the R2 keys (`/hyperai/home/.r2.env`, root only) or change the channel's code.
- They act only through the root-side `channel` service, which checks the caller's Linux user on every request
  (`ALLOWED` in `showrunner/channel`): the showrunner can direct and file requests, the engineer can submit, the page
  can read. Approving a new action needs root, which in practice means an owner's SSH key (`tools/approve.sh`).
- Plug-in actions are AI-written code. They are parsed (never imported) by the producer and the service, and only run
  inside Blender as `render`, with a time limit; an error skips that one action, not the scene.
- Puddle Park's agents are told to keep it suitable for ages 2-5 whoever asks (`showrunner/agents/AGENTS.md`).
- Secrets (R2 keys, the showrunner password, tokens) live only on the box and are never committed.

## Numbers (one RTX 3090, $0.10/h)

About real time: a 1-minute block takes 50-65 s with 4 renders while Qwen shares the card. MOSS images take ~40 s each.
Details in `docs/BENCHMARK.md`. Everything at once (Qwen, Blender, MOSS, agents) fills the card; the next step is a
second 3090 (Qwen and agents on one, Blender and MOSS on the other).

## Known limits / next steps

- One card: agents and MOSS windows slow rendering; viewers then see replays (the manifest's replay blocks).
- The showrunner rides a Cloudflare quick tunnel (no uptime guarantee, new address on restart; the fixed link follows it).
  A named tunnel needs a domain.
- No boot script yet; paths still say `kids-test`.
- Qwen's thinking cannot yet be switched off from dsh's config for the engineer (the `chat_template_kwargs` setting is
  not reaching llama-server); the builder/reviewer split keeps each conversation short instead.
- Platform: accounts and per-user channels ("bring your own AI" for the writing side) come after the pipeline settles.
