# R2 key layout: contract between the uploader and the Worker

Verified end to end by `worker/test/e2e/layout.test.js` (real `newsbot.r2.upload` with a fake S3 client -> local R2 -> `wrangler dev --local`) and `site/test/e2e-worker.js` (browser, cross-origin, `?src=`).

## What was wrong (found by that test)

`newsbot/pipeline.py` calls `r2.upload(out, "bulletins/<UTC timestamp>")`, and `newsbot/r2.py` writes every `.ts/.json/.m3u8` to `{prefix}/{filename}`, so one bulletin lands at

```
bulletins/20261106T120000Z/manifest.json
bulletins/20261106T120000Z/seg_000.ts ... seg_009.ts
bulletins/20261106T120000Z/index.m3u8   (+ other *.json)
```

The Worker read `manifest.json` at the bucket root (`PREFIX=""`) and answered 503. Also, the uploader uploads in sorted order, so `manifest.json` is written **before** the segments.

## Contract (Worker side, implemented)

Two config values in `worker/wrangler.toml` `[vars]` (override at deploy: `wrangler deploy --var PREFIX:...`):

| Key read | Meaning |
|---|---|
| `{PREFIX}manifest.json` | the manifest |
| `{PREFIX}{uri}` | each segment; `uri` is the manifest's `uri` field (pool/channel manifest) else its `file` field (Day 0 manifest). The playlist lists it as `seg/{uri}`; `/seg/<path>.ts` reads `{PREFIX}<path>.ts` |

`PREFIX` is normalised (`""`, `a/b`, `/a/b/` all work; stored as `a/b/`). The Worker answers `.ts` with `Content-Type: video/mp2t` whatever R2 stored, with CORS `*` (preflight allows `Range`). Only `[A-Za-z0-9_./-]+.ts` without `..` is served, and only below `PREFIX`.

### Layout A, works today with the unmodified uploader

`PREFIX = "bulletins/<ts>/"` (one bulletin per deploy/var). Day 0 manifest, `file` = `seg_000.ts`. Static, so it plays one bulletin until someone changes the var.

### Layout B, recommended for the hourly channel (what the uploader must follow)

`PREFIX = ""`. Per bulletin (already what `r2.upload(out, "bulletins/<ts>")` does):

```
bulletins/<ts>/seg_NNN.ts            Content-Type: video/mp2t
bulletins/<ts>/manifest.json         the per-bulletin Day 0 manifest (kept for provenance)
```

and a **channel manifest at the bucket root** that references those keys by full key:

```
manifest.json   {"version":2,"segment_seconds":6,"epoch":<unix>,
                 "blocks":[{"id":"<ts>","segments":[{"uri":"bulletins/<ts>/seg_000.ts","duration":6.0}, ...]}, ...]}
```

(the shape `newsbot.pool.channel_blocks` produces: `uri = "{prefix}/{file}"`). Rules for the uploader:

1. Upload **all** segments first, `manifest.json` last. A manifest that names missing keys makes the live playlist point at 404s. (Currently violated by `r2.py`'s sorted loop; that file belongs to the Day 1 branch.)
2. Write the root `manifest.json` in one PutObject (R2 PUTs are atomic per object), with `Content-Type: application/json`.
3. Keep `epoch` stable across uploads, and never delete a block's segments while any manifest (or a cached playlist, ~1 minute) still names them.
4. Keys are plain `[A-Za-z0-9_./-]`, segment names end in `.ts`.
5. Content types: `.ts` `video/mp2t`, `.json` `application/json` (already what `r2.py` sets; the Worker does not depend on it for `.ts`).

Known limitation unchanged from `docs/DAY2.md`: swapping the manifest mid-stream changes what `k % N` maps to.

## Day 1 uploader (implemented: `newsbot/publish.py`, step "Publish to R2" in `day1.yml`)

Runs only after the render passed its tests, and only when the four `R2_*` secrets exist (otherwise one log line,
exit 0). Per run, with `<ts>` the publish time (`%Y%m%dT%H%M%SZ`), in this order:

```
bulletins/<ts>/seg_000.ts .. seg_099.ts        video/mp2t
bulletins/<ts>/manifest.json                   application/json   (per-bulletin, after its segments)
bulletins/<ts>/slate/slate_000.ts .. _004.ts   video/mp2t
bulletins/<ts>/slate/manifest.json             application/json
manifest.json                                  application/json   (root channel manifest, ONE PutObject, LAST)
```

The root manifest's cycle is `[bulletin <ts>, slate <ts>/slate, up to 3 replays]`, where the replays are the
bulletin/replay blocks of the manifest that was live (already in R2, so nothing is re-uploaded; `uri` is the full
key). Continuity fields `epoch` (taken from the live manifest, else `newsbot.channel.EPOCH` = the Worker's
`EPOCH` var), `cycle_start_k`, `cycle_start_dseq` and `prev` follow `docs/MANIFEST-SWAP.md`; the Python port in
`newsbot/channel.py` is tested against vectors from `worker/src/playlist.js` (`tests/test_publish.py`). Nothing is
ever deleted or overwritten (fresh prefix per run). `out1/publish.json` lists every key written, in order.
