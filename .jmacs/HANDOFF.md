# Handoff

## Objective
Research report reports/channel-pipeline-survey.org: shared swappable-node architecture for AI-247, Puddle Park and a new Latin/Koine Greek/Biblical Hebrew channel; survey open-source orchestration, playout, real-time agent frameworks, agent harnesses and open Bible-language datasets. Branch cloud/channel-survey; PR to main, merge when checks pass.

## Done
- Read docs/PLAN.md, docs/TOPICS.md, docs/R2_LAYOUT.md, site/puddle-architecture.html, studio/ on studio-puddle-park.
- Surveyed (A)-(E) from GitHub/PyPI/npm primary sources (2026-11-07); unreachable hosts and 2nd-hand facts flagged in the report.
- Wrote reports/channel-pipeline-survey.org: Verdict, comparison tables, node contract sketch (job folder, node.yaml, result.json, channel.yaml), AI-247/Puddle Park/language-channel mapping, migration order, Experts and sources.
- Verdict: own file contract + DBOS Transact (Huey fallback) on the GPU box, Actions for cloud steps, ComfyUI as an image node, keep R2+Worker playout, dsh pinned (opencode fallback), Claude Agent SDK for Claude-only nodes; language data MACULA/SBLGNT, OSHB/MACULA Hebrew, Clementine Vulgate + Whitaker's; Piper phoneme voices via own IPA rules; Hebrew cards in headless Chromium.

- PR #53 squash-merged to main as 568b0dc (tests, worker-site-e2e, claude-review green on e2eb135). Review notes handled: dsh session-log upload off in the migration step; Chatterbox only as a flagged text-only fallback; licence rules marked as to confirm with counsel; second-hand Vulgate/he-voice licences flagged in the verdict.

## Pending
- jmacs todo-status done: jmacs is not installed in the cloud session; orchestrator to mark the todo done with path reports/channel-pipeline-survey.org.

## Next step
None. Optional spikes named in the report: pronunciation rules + Piper phoneme input, Hebrew cards in Chromium.
