# ai-247

A code-made, 24/7 AI news channel. Bulletins and graphics are rendered by code from primary-source feeds. No generated video is needed.

**Status: planning. The proof of concept has not started.**

## Architecture

1. GitHub Actions renders an hourly news bulletin (script, voice, code-drawn graphics).
2. Rendered segments are uploaded to Cloudflare R2.
3. A Cloudflare Worker serves a rolling HLS playlist built from those segments.
4. A Cloudflare Pages page plays the stream with hls.js.
5. Replays and a pre-rendered bootstrap pool keep the channel from going dark.
6. Every segment is labelled as AI-generated, and every claim cites its source.
7. Each episode researches one topic (`topics/topics.json`, editable; `docs/TOPICS.md`) from primary sources and
   never repeats a topic or story covered in `episodes/history.json` unless there is new news.

## Plan

Full plan: https://github.com/trotha01/knowledge-base-lab/blob/main/docs/ai-news-channel-plan.org

## Security

This repo is public. Never commit keys, stream keys or tokens. Secrets live only in GitHub Actions secrets, set by the repo owner.
