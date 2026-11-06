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
   - novelty: 1.0 if the topic has never aired; otherwise `0.5^(episodes since it last aired / N)` and, if it
     aired within the last N episodes, it is **blocked** unless at least `min_new_items_to_repeat` uncovered items
     are newer than that episode (that is "genuinely new news");
   - lane weight: seed 1.0, discovered 0.9.
   A topic with fewer than `min_items` (5) uncovered items is not pickable. If nothing is pickable the run
   falls back to today's general rundown (`topic: null`, reported as `feeds` mode), so the channel never goes dark.
3. **Research**: for the picked topic's top items (rank order), fetch the primary source (article page, arXiv
   abstract, GitHub release body) politely (robots.txt, UA, 20 s timeout, 1 MB cap, 8 fetches max), extract text,
   and replace the short feed summary with up to 6,000 characters of it. Every sentence is still written from
   that one source and fact-checked against it; nothing changes in the gate.
4. **Plan call** (one call, default Claude Haiku 5.5; `NEWSBOT_PLAN_MODEL=claude-sonnet-5-5` switches it): given
   the topic and the candidate titles, return the story order and a two-sentence spoken framing intro that must
   contain no number or named entity not present in the sources (deterministic check; on failure the fixed
   intro is used). It never writes claims.
5. **Discovery lane** (one Haiku call per run): given all feed titles of the run and the current topic names,
   propose at most one new, novel or newly popular area of AI with keywords and a one-line reason, or null. It is
   added to `topics.json` (lane `discovered`) only if its keywords match >= 2 of the run's items, no existing topic
   has a similar name/keywords, and no discovered topic was added today (`max_new_topics_per_day`, default 1).
6. **Dedupe**: covered URLs are excluded at step 1; the history entry is appended after the episode is published.

## Cost and models

Writer, checker and repair stay on Claude Haiku 5.5 under the existing `Meter` and `NEWSBOT_MAX_RUN_USD` = 0.05
per run. The plan and discovery calls use the same meter. Longer source text (6,000 vs 3,500 chars) raises the
writer+checker input: estimate 0.010-0.020 USD per episode on Haiku (today 0.005); Sonnet for the plan call adds
about 0.01. With the 3-hourly cron (8 runs/day): about 0.10-0.20 USD/day, 3-6 USD/month, under the 10 USD cap.
Measured cost per episode is in `report.json` (`llm.cost_usd_estimate`, split by call kind) and the job summary.

## Persistence

The workflow commits `episodes/history.json` and `topics/topics.json` back to the branch it ran on (`contents:
write`, `git pull --rebase` first, bot commit, never force). A push by `GITHUB_TOKEN` triggers no other workflow.
As a fallback the same history is uploaded to R2 as `episodes/history.json` with the episode and read back at the
next run, so dedupe survives a failed push. `mode=feeds` (workflow input) or repo variable `DAY1_TOPIC_MODE=off`
restores the old digest behaviour without a commit.

## Not in scope

Web search APIs (none without a key); the discovery call sees only what the feeds carried this run. Article
fetching respects robots.txt and fetches at most 8 pages per run.
