# Topic research stage (design, approved by Trevor 2026-11-06 with four changes)

Goal: each episode is Claude researching one topic in depth, not a digest of whatever the 8 feeds had. The
stage sits in front of the existing writer: fetch feeds -> **pick a topic -> gather and read primary sources ->**
Haiku writer + fact check (unchanged) -> episode -> R2 -> **record in D1 -> discovery (web search)**.

Trevor's changes to the first draft: (1) the discovery call searches the web, not just feed titles; (2) no cap on new
topics per day; (3) history lives in Cloudflare D1, never in the repo; (4) plan and discovery run on Claude Fable 5.1
at low effort, writer and checker stay on Claude Haiku 5.5.

## Files Trevor can edit

- `topics/topics.json`: the topic list. Each topic has `id`, `name`, `lane` (`seed` or `discovered`), `keywords`
  (matched against feed item title+summary, lower-cased tokens, any keyword phrase hit counts), `queries` (web
  lookups for arXiv / GitHub / Hacker News), optional topic-specific `sources` (extra feeds or GitHub release repos),
  `seed_urls` (primary links a discovery call found; read and cited like any source), `enabled`, `added` (date),
  `reason` (one line). Seed lanes: `agent-harnesses` (AI agent harnesses and coding agents) and `ai-vfx` (AI for VFX
  and film/video production). Settings at the top: `repeat_after_episodes` (N), `min_new_items_to_repeat`,
  `min_items`, `discovery_enabled`, `lane_weights`. Discovered topics are appended by the workflow (the only thing it
  commits); delete or set `enabled: false` to drop one.
- The episode history is **not** a repo file any more. It is the D1 database `ai247-history` (see "Persistence");
  the Worker serves a read-only view at `/history.json?limit=50`, and every run's artifact carries a snapshot
  (`out1/history.json`).

## Per episode (`newsbot/topics.py`, stages `topic_research` and `discovery` in `newsbot/day1.py`)

1. **Candidates**: for every enabled topic, the feed items whose title+summary match its keywords, plus items from
   its own sources. Items already covered (URL in the history) are dropped.
2. **Score** = freshness x novelty x lane weight, deterministic, no LLM, written to `episode/topic_pick.json`:
   - freshness: sum over the topic's uncovered items of `0.5^(age_h/48)` (same decay as `rank.py`), capped at 8;
   - novelty: 1.0 if the topic has never aired or last aired N or more episodes ago; otherwise
     `(episodes since it aired + 1) / (N + 1)`, and a topic that aired within the last N episodes is **blocked**
     unless at least `min_new_items_to_repeat` uncovered items are newer than that episode ("genuinely new news");
   - lane weight: seed 1.0, discovered 0.9.
   A topic with fewer than `min_items` (5) uncovered items is not pickable (the workflow input `topic` forces one
   anyway). If nothing is pickable the run falls back to today's general rundown minus covered URLs
   (`topic: null`, reported as `feeds` mode), so the channel never goes dark.
3. **Research** (`newsbot/research.py`): the picked topic is deepened with keyless web lookups using its
   `queries` (arXiv API abstracts, GitHub repository search for recently pushed repos, Hacker News stories with
   >= 20 points used only as leads to their primary URL) and its `seed_urls`; leads without text are read first
   (3 pages max). The pool is ranked with `rank.py` (per-source cap 4, lifted when the topic lives on one or two
   sources), then the top stories' primary pages (article, arXiv abstract, release page) are fetched politely
   (robots.txt, the newsbot UA, 20 s timeout, 1 MB cap, 8 fetches per run in total), reduced to their main text, and
   used instead of the short feed summary when they add at least 400 characters: up to 6,000 characters reach the
   writer and checker (3,500 in feeds mode). Every sentence is still written from that one source and fact-checked
   against it; nothing changes in the gate.
4. **Plan call** (one call, **Claude Fable 5.1, `output_config.effort = low`**, no `thinking` parameter since Fable
   always thinks; `NEWSBOT_PLAN_MODEL` / workflow input `plan_model` switch it): given the topic and the candidate
   titles, return the story order and a two-sentence spoken framing intro that must contain no number or named
   entity not present in the sources (deterministic check; on failure the fixed intro is used). It never writes
   claims. `max_tokens` 3000 because Fable's thinking tokens count as output.
5. **Writer + checker** (`newsbot/llm.py`): unchanged, Claude Haiku 5.5, fresh-context fact check, deterministic
   number/name grounding, one repair round, extractive fallback. Nothing airs without a source card.
6. **Discovery lane** (`newsbot/discovery.py`, after the writer so a budget stop never costs an aired sentence):
   one **Claude Fable 5.1 call at low effort with the server-side web search tool** (`web_search_20260209`,
   `max_uses` 3; falls back to `web_search_20250305` on a 400). It sees the run's item titles and the current topics,
   searches the web for a new, novel or newly popular area of AI, and proposes `{id, name, description, keywords,
   queries, links, reason}` or null. Gates, all deterministic:
   - `links` must be http(s), not on an aggregator/social host (HN, Reddit, X, YouTube, Medium, news sites, ...), and
     must have appeared in the search results the tool returned or among this run's items: the model cannot invent a
     URL. Surviving links become the topic's `seed_urls`, so the first episode on it cites those primary pages.
   - at least 2 "items" match its keywords, counting the run's feed items and the surviving primary links;
   - no existing topic is similar (overlap coefficient of name+keyword tokens >= 0.5, plural-insensitive);
   - fields validate (kebab id, 3-15 keywords, ...); a `refusal` stop or non-JSON reply adds nothing.
   **There is no per-day cap** (`max_new_topics_per_day` was removed). `settings.discovery_enabled: false` turns the
   lane off; `NEWSBOT_DISCOVERY_SEARCHES` sets the search budget per call.
7. **Dedupe**: covered URLs are excluded at step 1; the episode (topic, story URLs, sentence hashes) is written to D1
   after the publish step, and the discovered topic (if any) is committed to `topics.json`.

## Persistence (Cloudflare D1)

- Database `ai247-history` (D1), schema in `worker/migrations/0001_history.sql`: `episodes` (one row per run, the
  full history entry as JSON plus topic/ts/mode/published/r2_prefix/cost/model columns), `stories` (run_id, url,
  source, headline), `claims` (run_id, sha256-16 of every aired sentence). All statements are `IF NOT EXISTS`.
- **Secrets stay out of the render step**: the render job's step "Load episode history" (`python -m newsbot.topics load
  out1/history_in.json`) is the only step there with Cloudflare/R2 credentials; it writes a hand-off file (episodes,
  store status, D1 discovered topics) that the render step reads through `NEWSBOT_HISTORY_IN`. Writes happen in the
  separate `record` job, and only its final commit step sees the repository write token.
- **Write/read path from Actions**: `newsbot/history_db.py` calls the Cloudflare REST API
  (`/accounts/<id>/d1/database/<uuid>/query` with bound parameters) using `CLOUDFLARE_API_TOKEN` and
  `CLOUDFLARE_ACCOUNT_ID`, looks the database up by name and creates it if missing, runs the migration file
  idempotently, then `load()` / `upsert()`. No Node install in the day1 job; secrets and the account id are never
  printed. `python -m newsbot.history_db status` is a read-only check.
- **Worker**: `[[d1_databases]]` binding `DB` in `worker/wrangler.toml`; `deploy.yml` looks the database up by name
  (creating it if needed), writes its id into the toml, runs `wrangler d1 migrations apply --remote`, then deploys.
  `GET /history.json?limit=N` returns the newest entries (CORS, no-store).
- **Permission**: the token needs **Account -> D1 -> Edit**. Without it the day1 job reads/writes only the R2 mirror
  (`episodes/history.json` in the media bucket, kept as a read cache / fallback), prints a `::warning::` and the job
  summary says `History store: r2 ... NEEDS TREVOR: Add Cloudflare API token permission Account -> D1 -> Edit`;
  the deploy job removes the binding so the Worker still deploys. On the first run with D1 working, entries found in
  the R2 mirror are imported, so nothing is lost across the switch.
- Nothing about history is committed to the repo (`episodes/` is git-ignored). A topic added by discovery is written
  to the D1 table `discovered_topics` (the durable copy, merged into the topic list at run time; an entry with the same
  id in `topics.json` wins, so Trevor can edit or disable it there) and appended to `topics/topics.json`, which the
  run commits back when the branch allows it. On `main` the ruleset (pull requests required) refuses that push, so
  the step only warns; the topic is still in D1 and in the run artifact (`topic_pick.json`).

## Cost and models

| Call | Model | Effort | Per episode (estimate) |
|---|---|---|---|
| writer + checker + repair (about 30 calls) | Claude Haiku 5.5 (0.10 / 0.50 USD per MTok) | low / medium | **0.0054 USD** measured (run 42238216216; 0.00586 on run 42229528561) |
| plan (1 call) | Claude Fable 5.1 (10 / 50 USD per MTok) | low | **0.0238 USD** measured |
| discovery (1 call + up to 3 web searches at 0.01 USD each) | Claude Fable 5.1 | low | **0.2929 USD** measured (3 searches; search results are input tokens) |

Measured **0.322 USD per episode** (run 42238216216, details below); the per-run guard `NEWSBOT_MAX_RUN_USD` is **0.75**
(pre-flight worst case before every call, web searches included; the writer runs before discovery, so a stop only
drops discovery). Topic episodes run only when `day1-episode` is dispatched (PR #33 moved the unattended schedule to
`hourly.yml`, whose six slices per hour run with `NEWSBOT_TOPIC_MODE=off`), so unattended spend from this stage is
currently 0; if topic mode were put on a cadence, 8 episodes/day would be about 2.6 USD/day (77 USD/month) against the
10 USD monthly limit, which remains the hard stop at the Anthropic console. Levers in order of effect:
`plan_model=claude-haiku-5-5` (workflow input / `NEWSBOT_PLAN_MODEL`, `NEWSBOT_DISCOVERY_MODEL`), a slower cron,
`NEWSBOT_DISCOVERY_SEARCHES`, `settings.discovery_enabled: false`. Measured cost by call kind is in `report.json`
(`llm.cost_by_kind`: write / check / repair / plan / discover, `llm.web_searches`) and in the job summary.

Worst case under the guard: 0.75 USD per dispatched episode.

## Measured run

### This build: run 42238216216 (2026-11-06, `workflow_dispatch` on the branch, mode=topic, Fable 5.1 plan + discovery)

| Measure | Value |
|---|---|
| Topic picked | `agent-harnesses` (77 uncovered items vs 61 for `ai-vfx`; both saturated the 12-item freshness window at 10.39, tie broken on id). The previous episode's topic was not known to this run: D1 refused the token and the render step of this commit had no R2 secrets yet (added in 1d03092), so dedupe did not apply here |
| Primary pages read | 5 swapped in: github.com 5,976 chars, momentic.ai 5,945, pipod.dev 2,084 (3 HN/GitHub leads), Microsoft Research 522 -> 5,922, arXiv cs.GR 1,169 -> 3,462 |
| Stories | 10 written from 5 sources, 9 aired (600.0 s, 100 segments, 44.5 s pad); 52 drafted lines, 37 supported first pass (71%), 6 rewritten (5 supported), 1 dropped, 0 extractive fallbacks; 36 aired sentences, **100% supported, 100% grounded, 0 unsourced** |
| Plan call | Claude Fable 5.1, effort low: **0.02379 USD** |
| Discovery call | Claude Fable 5.1, effort low, **3 web searches**: **0.29293 USD** (incl. 0.03 for the searches); accepted `verified-code-generation` ("Three feed items today (PDD Kit, LLM-to-Dafny, proof formalization) plus 5+ recent arXiv papers on verified code synthesis benchmarks", 12 matching items/links), committed to `topics/topics.json` by the run (5f23967) |
| Writer + checker + repair | Claude Haiku 5.5: write 0.001835 + check 0.002893 + repair 0.00068 = **0.0054 USD** |
| **Total** | **0.32213 USD per episode** (cap 0.75). At the 3-hourly cron: **about 2.6 USD/day, 77 USD/month**; 91% of it is the discovery call |
| Wall-clock | fetch 4.8 s, topic research 19.1 s, script 46.3 s, discovery 19.5 s, TTS 234 s, render 316 s; pipeline 662 s; publish 102 s; job 18 min |
| History | D1: `D1 API refused the token (Authentication error)` -> **needs Trevor: add Account -> D1 -> Edit to CLOUDFLARE_API_TOKEN**. Fallback worked: the record step read the R2 mirror (1 earlier entry) and wrote back 2 entries |
| Published | `bulletins/20261106T150835Z/` (105 segments + manifests, 32.0 MB), `cycle_start_k` 163171: the Worker swaps it in at that media sequence (about 20 min after publish) |
| **Plays on https://ai-247.pages.dev** | Verified from the cloud session with Google Chrome via `site/test/e2e-live.js` at 15:32Z, when the live playlist had reached `seg/bulletins/20261106T150835Z/seg_016.ts`: page state `live`, video time advancing (20.0 s), segments 200 `video/mp2t`, no console errors, AI-generated label visible. The same check 12 min earlier (bulletin not yet on air) also passed and reported the swap pending |
| Live check (runner) | playlist 200, media sequence rising 162971 -> 162972, 11 segments fetched as 200 video/mp2t, no console errors, label visible; the Playwright Chromium on the runner cannot decode H.264/AAC so the page ended in state offline there (the check now prefers the runner's Google Chrome and only asserts `state live` when the browser can decode) |

Cost lever actually worth pulling: the discovery call. `NEWSBOT_DISCOVERY_SEARCHES=1` roughly halves it; `plan_model=claude-haiku-5-5`
brings the whole episode back to ~0.01 USD; `settings.discovery_enabled: false` removes it.

### Baseline: first topic episode of the Haiku-only build (run 42229528561, 2026-11-06, before Trevor's four changes)

| Measure | Value |
|---|---|
| Topic picked | `agent-harnesses` (both seed lanes had 60-70 uncovered items; the freshness sum saturated at the old cap of 8, so the tie broke on id; freshness now counts the 12 freshest items) |
| Inputs | 8 general feeds (105 items) + 10 topic feeds/repos (91 items); web: arXiv 21, GitHub search 24, HN leads 21 candidates |
| Primary pages read | 8 fetched (3 leads first), 5 with text swapped in (2,084-5,976 chars); 3 openai.com pages refused bots (HTTP 403); 7 stories kept their feed text (budget used) |
| Stories | 9 written from 5 sources, 8 aired (600.0 s, 100 segments, 31 s pad); 45 drafted lines, 33 supported first pass (73%), 4 rewritten (3 supported), 1 dropped, 0 extractive fallbacks |
| Aired sentences | 100% supported, 100% grounded, 0 unsourced |
| Cost (Claude Haiku 5.5) | **0.00586 USD** total: plan call 0.00039, writer + checker + repair the rest; cap 0.05 |
| Discovery call | failed (`ValueError`: no JSON in the reply, most likely truncated at 700 output tokens); raised to 1,200 |
| Wall-clock | topic research 15.7 s, script 35 s, TTS 198 s, render 300 s; pipeline 594 s; publish 128 s; job 15 min |
| History | entry was committed to `episodes/history.json` by that build (since removed from the repo; the R2 mirror still has it and seeds D1 on first use) |
| Live check (runner) | playlist 200, media sequence rising, segments 200 video/mp2t, label visible; `state live` not reached within 60 s on the runner (state `connecting`, segments were being fetched); the same check from the cloud session passed with video time advancing |
| Published | `bulletins/20261106T140715Z/` (105 segments, 32.5 MB); the Worker swaps it in at the next cycle boundary |

Per-day estimate at the 3-hourly cron: 8 x 0.006 = about 0.05 USD/day on Haiku (the longer primary texts cost less
than estimated because openai.com pages are not fetchable and the fetch budget is 8 pages).

## Outputs

`episode/topic_pick.json` (scores of every topic, the pick, fetch reports, the plan result, the history store status,
the discovery result with its cost and search count), `script.json` gains `topic`, `rundown_title` and the planned
`intro`; `report.json` gains `topic` (incl. `history`, `discovery_*`) and `llm.cost_by_kind`. The job summary shows
the topic, sources read, plan model, the discovery outcome and cost, the history store (and what Trevor must fix if
D1 is unavailable), and the cost split. Workflow inputs: `mode` (topic | feeds), `topic` (force an id), `plan_model`
(Fable 5.1 default, Sonnet 5.5, Haiku 5.5). Fixture runs (`--items-json`) fetch nothing. After a publish the workflow
runs `site/test/e2e-live.js` (Playwright) against https://ai-247.pages.dev: playlist 200, media sequence rising,
page in state live, video time advancing, segments as video/mp2t, and whether the new bulletin is already in the
playlist (it airs at the next cycle boundary).

## Not in scope

Page fetching respects robots.txt and reads at most 8 pages per run. Server-side refusal fallbacks are not enabled
on the Fable calls: a refusal simply means no plan intro / no new topic for that run (logged).
