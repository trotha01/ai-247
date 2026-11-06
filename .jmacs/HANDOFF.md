## Objective
AI-247 manifest-swap continuity: Worker handles epoch/cycle_start_k so hourly manifest swaps take effect at loop boundaries; monotonic media/discontinuity sequence; spec for Day 1 uploader. Only worker/ and docs/ edited.

## Done
- worker/src/playlist.js: eras (cycle_start_k, cycle_start_dseq, prev), nextSwapStart, swapDseq.
- worker/test/unit/swap.test.js: hourly-swap simulation with hls-parser (monotonic seq, stable URIs, discontinuities, boundary).
- docs/MANIFEST-SWAP.md spec; DAY2.md pointer.

## Pending
- PR merge to main (see status.json).

## Next step
Day 1 uploader implements docs/MANIFEST-SWAP.md (not edited by me).
