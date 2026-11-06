# Handoff

## Objective
Build Day 0 of the ai-247 news-channel PoC (see docs/PLAN.md): a workflow_dispatch Actions run that renders one 60 s bulletin as ten 6 s HLS segments + manifest, works without Anthropic/R2 secrets.

## Done
- docs/PLAN.md written (copy of brief).
- Sandbox findings: skia-python, feedparser, kokoro-onnx install via pip; Kokoro model files download from GitHub releases (huggingface.co, docs.github.com and most feed hosts are blocked from the cloud sandbox).

## Pending
- newsbot package, tests, workflow, run, merge.

## Next step
Write the code under newsbot/, tests under tests/, workflow .github/workflows/day0.yml.
