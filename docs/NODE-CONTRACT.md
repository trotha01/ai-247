# Node contract and channel YAML (Phase 1 spine)

Code: `spine/` (contract, runner), `spine/nodes/` (wrappers around existing code), `channels/<name>.yaml`.
Plan: `docs/PIPELINE-PLAN.md` Phase 1.

## A node

A node is **a command run on one job folder** `JOB`.

1. The runner writes `JOB/node.yaml`:
   ```yaml
   name: render_lesson
   inputs: {script.json: /abs/path/script.json}     # block nodes get a list of paths, one per item
   outputs: [clip.mp4]                              # names the node must report
   params: {voices: {en: en_US-ljspeech-medium}}    # from the channel YAML, nothing else
   channel: {name: lang, prefix: lang/, host: griffith, dry_run: false}
   state: /srv/channels/lang/spine/state/render_lesson   # kept between jobs (e.g. a counter)
   timeout: 600
   gpu: false
   ```
2. The runner runs the command with `JOB` as its last argument (Python nodes: `python -m spine.node MODULE:FUNC JOB`).
3. The node writes its outputs inside `JOB`, then **`JOB/result.json` last, atomically** (temp file + rename):
   ```json
   {"status": "ok|skip|fail", "outputs": {"clip.mp4": "render/clip.mp4"}, "seconds": 41.2, "cost_usd": 0.0, "log": "one line"}
   ```
   Output paths are relative to `JOB`. No `result.json` (crash, kill, timeout) = `fail`. A declared output missing from
   `outputs` = `fail`. `skip` = nothing to do (the item is dropped, not retried).
4. Everything the node prints goes to `JOB/log.txt`. Secrets come from the environment only and are never written.

A Python node is a function `f(job: spine.contract.Job)` returning `{name: path}` (optionally `(outputs, log_line)`);
raise `spine.contract.Skip` to skip. `spine.contract.call` writes `result.json`.

## A channel YAML

```yaml
channel: lang                 # name; the service is channel@lang
host: griffith                # informational only: no host paths anywhere, a channel moves by reinstalling
prefix: lang/                 # R2 prefix in ai247-media ("" = root, AI-247)
worker: lang-live             # Cloudflare Worker that plays it
healthz: https://lang-live.trotha01.workers.dev/healthz
cadence: {queue_ahead: 12, block_items: 1, max_wait: 120, produce_every: 0}
storage: {local_cap_gb: 3}
producer: [nodes run per item, ahead of time, into ROOT/inbox/]
item:     [nodes run per item by the worker]
block:    [nodes run once per block over all items; the last one is `publish`]
```

Each node entry: `{node, run: MODULE:FUNC | cmd: [...], in: [...], out: [...], params: {...}, timeout: s, retries: n, gpu: bool}`.
`in` names must be written by an earlier node (checked at load: `python -m spine check`). The plan's flat `graph:` maps
onto these three stages: the stage says *when* a node runs (ahead / per item / per block), which is the loop pattern
the channels already use.

## The runner (`python -m spine run NAME --root DIR`)

Plain Python, one process per channel (systemd user unit `deploy/box/channel@.service`):
- **producer thread** keeps `queue_ahead` items in `ROOT/inbox/` (item folders appear by rename, never half-written);
- **worker** takes `block_items` items, or fewer once the oldest waited `max_wait` s (**partial flush**); an item whose
  node fails or skips goes to `ROOT/failed/` and the block goes on without it (**skip failures**); the block stage ends
  in `publish` (`newsbot.publish.publish_many`: **segments first, manifest last**), under the channel prefix only;
- **retries** per node with backoff, **timeouts** enforced by the runner;
- **durable on disk**: a step whose job folder holds an ok `result.json` is never re-run; items in flight return to the
  inbox on restart; producer state (e.g. next lesson number) lives in `ROOT/state/<node>/`;
- **logs**: one line per step to stdout (journald), `JOB/log.txt`, `ROOT/events.jsonl` (rotated at 5 MB),
  `ROOT/status.json` (blocks, last publish, last error);
- the YAML is read at start: **swap a node by editing the YAML and restarting the unit**.

### Why not DBOS (yet)

The plan picked DBOS. For v1 the runner is a plain loop with the same contract because the durable state DBOS would add
is already on disk (job folders + `result.json` checkpoints, rename-based queues), griffith runs NixOS with Python 3.14
where every extra wheel (DBOS pulls SQLAlchemy/psycopg/OpenTelemetry) has to be checked against nix-ld, and each host
runs only one or two channels, so there is no cross-channel queue to coordinate. The `gpu: true` flag is in the contract;
when Puddle needs a shared GPU queue across channels on HyperAI, DBOS (or Huey) can drive the same nodes unchanged.
