# Topic research stage (design)

Goal: each episode is Claude researching one topic in depth, not a digest of whatever the 8 feeds had. The
stage sits in front of the existing writer: fetch feeds -> **pick a topic -> gather and read primary sources ->**
Haiku writer + fact check (unchanged) -> episode -> R2.

## Files Trevor can edit

- `topics/topics.json`: the topic list. Each topic has `id`, `name`, `lane` (`seed` or `discovered`), `keywords`
  (matched against feed item title+summary, lower-cased tokens, any keyword phrase hit counts), optional
  topic-specific `sources` (extra feeds or GitHub release repos, fetched only when that topic is a candidate),
  `enabled`, `added` (date), `reason` (one line). Seed lanes: `agent-harnesses` (AI agent harnesses and coding
  agents) and `ai-vfx` (AI for VFX and film/video production). Settings at the top: `repeat_after_episodes` (N),
  `min_new_items_to_repeat`, `max_new_topics_per_day`.
- `episodes/history.json`: one entry per published episode: run id, time, topic id, story URLs, headlines, and
  the sha256 of every aired sentence. Written by the workflow (see "Persistence"); hand edits are fine.

## Per episode (`newsbot/topics.py`, stage `topic_research` in `newsbot/day1.py`)

1. **Candidates**: for every enabled topic, the feed items whose title+summary match its keywords, plus items from
   its own sources. Items already covered (URL in history) are dropped.
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
   >= 20 points used only as leads to their primary URL); leads without text are read first (3 pages max). The
   pool is ranked with `rank.py` (per-source cap 4, lifted when the topic lives on one or two sources), then the
   top stories' primary pages (article, arXiv abstract, release page) are fetched politely (robots.txt, the newsbot
   UA, 20 s timeout, 1 MB cap, 8 fetches per run in total), reduced to their main text, and used instead of the
   short feed summary when they add at least 400 characters: up to 6,000 characters reach the writer and checker
   (3,500 in feeds mode). Every sentence is still written from that one source and fact-checked against it;
   nothing changes in the gate.
4. **Plan call** (one call, default Claude Haiku 5.5; `NEWSBOT_PLAN_MODEL=claude-sonnet-5-5` switches it): given
   the topic and the candidate titles, return the story order and a two-sentence spoken framing intro that must
   contain no number or named entity not present in the sources (deterministic check; on failure the fixed
   intro is used). It never writes claims.
5. **Discovery lane** (`newsbot/discovery.py`, one Haiku call per run, skipped once the day's cap is reached):
   given the run's item titles and the current topics, propose at most one new, novel or newly popular area of AI
   (id, name, description, keywords, queries, one-line reason) or null. It enters `topics.json` (lane `discovered`)
   only if its keywords match >= 2 of the run's items, no existing topic is similar (name/keyword token overlap),
   the reply validates field by field, and no discovered topic was added today (`settings.max_new_topics_per_day`,
   default 1; `settings.discovery_enabled` turns the lane off).
6. **Dedupe**: covered URLs are excluded at step 1; the history entry is appended after the episode is published.

## Cost and models

Writer, checker and repair stay on Claude Haiku 5.5 under the existing `Meter` and `NEWSBOT_MAX_RUN_USD` = 0.05
per run. The plan and discovery calls use the same meter. Longer source text (6,000 vs 3,500 chars) raises the
writer+checker input: estimate 0.010-0.020 USD per episode on Haiku (today 0.005); Sonnet for the plan call adds
about 0.01. With the 3-hourly cron (8 runs/day): about 0.10-0.20 USD/day, 3-6 USD/month, under the 10 USD cap.
Measured cost per episode is in `report.json` (`llm.cost_usd_estimate`, split by call kind) and the job summary.

## Outputs

`episode/topic_pick.json` (scores of every topic, the pick, fetch reports, the plan and discovery results),
`script.json` gains `topic`, `rundown_title` and the planned `intro`; `report.json` gains `topic` and
`llm.cost_by_kind` (write / check / repair / plan / discover). The job summary shows the topic, sources read,
plan model, discovery outcome and the cost split. Workflow inputs: `mode` (topic | feeds), `topic` (force an id),
`plan_model`. Fixture runs (`--items-json`) fetch nothing. After a publish the workflow runs
`site/test/e2e-live.js` (Playwright) against https://ai-247.pages.dev: playlist 200, media sequence rising, page in
state live, video time advancing, segments as video/mp2t, and whether the new bulletin is already in the playlist
(it airs at the next cycle boundary).

## Persistence

The workflow commits `episodes/history.json` and `topics/topics.json` back to the branch it ran on (`contents:
write`, `git pull --rebase` first, bot commit, never force). A push by `GITHUB_TOKEN` triggers no other workflow.
As a fallback the same history is uploaded to R2 as `episodes/history.json` with the episode and read back at the
next run, so dedupe survives a failed push. `mode=feeds` (workflow input) or repo variable `DAY1_TOPIC_MODE=off`
restores the old digest behaviour without a commit.

## Not in scope

Keyed web search APIs; the discovery call sees only the titles the feeds and topic sources carried this run.
Page fetching respects robots.txt and reads at most 8 pages per run.

## Measured (first topic episode, run 42229528561, 2026-11-06, `workflow_dispatch` on the branch)

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
| History | `episodes/history.json` entry committed back by the run (`dfe523e`) and mirrored to R2 |
| Live check (runner) | playlist 200, media sequence rising, segments 200 video/mp2t, label visible; `state live` not reached within 60 s on the runner (state `connecting`, segments were being fetched); the same check from the cloud session passed with video time advancing |
| Published | `bulletins/20261106T140715Z/` (105 segments, 32.5 MB); the Worker swaps it in at the next cycle boundary |

Per-day estimate at the 3-hourly cron: 8 x 0.006 = about 0.05 USD/day on Haiku (the longer primary texts cost less
than estimated because openai.com pages are not fetchable and the fetch budget is 8 pages).
