"""Channel runner: runs one channel YAML (channels/<name>.yaml) as an always-on producer + worker loop.

    python -m spine run lang --root /srv/channels/lang/spine            # forever (what channel@lang.service runs)
    python -m spine run channels/lang.yaml --root /tmp/l --max-blocks 2 --dry-run   # bounded test, no upload

The pattern is the studio/lang loop pair (Mychal's), with every step a node (spine/contract.py):

  producer thread   keeps `cadence.queue_ahead` items ready in ROOT/inbox/. One item = the `producer` stage run in
                    ROOT/producing/<id>/<NN-node>/ job folders; the finished item folder is renamed into inbox/
                    (so the worker never sees half an item). At most one item per `cadence.produce_every` seconds.
  worker (main)     takes `cadence.block_items` items (or fewer once the oldest waited `cadence.max_wait` s: partial
                    flush), runs the `item` stage on each (an item that fails or skips goes to ROOT/failed/ and is
                    left out of the block), then the `block` stage once in ROOT/work/<ts>/ (inputs are lists, one
                    path per item). The last block node is `publish` (newsbot.publish: segments first, manifest last).

Durability: a step whose job folder already holds an ok result.json is not run again, and items that were being
worked on when the process stopped go back to the inbox, so a restart carries on where it stopped. Retries: each
node may set `retries` (default 0) with backoff; `timeout` (s) is enforced by the runner. Logs: one line per step on
stdout (journald), the node's own output in its JOB/log.txt, events in ROOT/events.jsonl, ROOT/status.json.
The YAML is read once at start: edit it and restart the service to swap a node. touch ROOT/STOP to stop.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

from .contract import read_result, write_node_yaml

REPO = Path(__file__).resolve().parents[1]
CHANNELS = REPO / "channels"
STAGES = ("producer", "item", "block")
CADENCE = {"queue_ahead": 3, "block_items": 1, "max_wait": 180, "produce_every": 0, "poll": 3}
EVENTS_CAP = 5_000_000


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ channel YAML --------------------------------
def channel_path(ref: str) -> Path:
    p = Path(ref)
    if p.suffix in (".yaml", ".yml") or p.exists():
        return p
    if not ref.replace("-", "").replace("_", "").isalnum():
        raise SystemExit(f"channel name must be letters/digits, not {ref!r}")
    return CHANNELS / f"{ref}.yaml"


def load_channel(ref: str) -> dict:
    """Read and check a channel YAML; returns it with defaults filled in."""
    path = channel_path(ref)
    ch = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for k in ("channel", "prefix"):
        if k not in ch:
            raise ValueError(f"{path}: missing {k!r}")
    ch["cadence"] = {**CADENCE, **(ch.get("cadence") or {})}
    ch["storage"] = {"local_cap_gb": 3.0, **(ch.get("storage") or {})}
    names: set[str] = set()
    for st in STAGES:
        ch[st] = ch.get(st) or []
        for n in ch[st]:
            if not n.get("node") or not (n.get("run") or n.get("cmd")):
                raise ValueError(f"{path}: every {st} node needs `node` and `run` (MODULE:FUNC) or `cmd`")
            for i in n.get("in", []):
                if i not in names:
                    raise ValueError(f"{path}: {st} node {n['node']} reads {i!r}, which no earlier node writes")
            names |= set(n.get("out", []))
    if not ch["block"] or ch["block"][-1]["node"] != "publish":
        raise ValueError(f"{path}: the last block node must be `publish`")
    ch["_path"] = str(path)
    return ch


# ------------------------------------------------------------------ one step ------------------------------------
class Runner:
    def __init__(self, ch: dict, root: Path, dry_run: bool = False, max_blocks: int = 0):
        self.ch, self.root, self.dry_run, self.max_blocks = ch, root, dry_run, max_blocks
        self.cad = ch["cadence"]
        self.stop_ev = threading.Event()
        self.lock = threading.Lock()
        self.status = {"channel": ch["channel"], "yaml": ch["_path"], "started": time.time(), "blocks": 0,
                       "items": 0, "failed_items": 0, "last_publish": None, "last_error": None,
                       "nodes": {st: [n["node"] for n in ch[st]] for st in STAGES}}
        for d in ("inbox", "producing", "working", "work", "failed", "done", "state"):
            (root / d).mkdir(parents=True, exist_ok=True)

    # events + status
    def event(self, **e):
        e["t"] = round(time.time(), 3)
        p = self.root / "events.jsonl"
        with self.lock:
            if p.exists() and p.stat().st_size > EVENTS_CAP:
                os.replace(p, p.with_suffix(".jsonl.1"))
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def save_status(self, **kw):
        with self.lock:
            self.status.update(kw)
            tmp = self.root / ".status.json.tmp"
            tmp.write_text(json.dumps(self.status, indent=1))
            os.replace(tmp, self.root / "status.json")

    def stopping(self) -> bool:
        return self.stop_ev.is_set() or (self.root / "STOP").exists()

    def command(self, node: dict, job: Path) -> list[str]:
        if node.get("run"):
            return [sys.executable, "-m", "spine.node", node["run"], str(job)]
        cmd = node["cmd"]
        return (cmd.split() if isinstance(cmd, str) else list(cmd)) + [str(job)]

    def run_step(self, node: dict, job: Path, inputs: dict) -> dict:
        """Run one node on one job folder (with retries); returns its result dict."""
        prev = read_result(job)
        if prev and prev["status"] == "ok":
            return prev  # durable: done before a restart
        spec = {"name": node["node"], "inputs": {k: ([str(x) for x in v] if isinstance(v, list) else str(v))
                                                 for k, v in inputs.items()},
                "outputs": node.get("out", []), "params": node.get("params") or {},
                "channel": {"name": self.ch["channel"], "prefix": self.ch["prefix"], "host": self.ch.get("host"),
                            "dry_run": self.dry_run},
                "state": str(self.root / "state" / node["node"]),
                "timeout": node.get("timeout", 900), "gpu": bool(node.get("gpu", False))}
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(REPO), os.environ.get("PYTHONPATH")])))
        if self.dry_run:
            env["SPINE_DRY_RUN"] = "1"
        tries = int(node.get("retries", 0)) + 1
        res = None
        for attempt in range(tries):
            if job.exists() and attempt:
                (job / "result.json").unlink(missing_ok=True)
            write_node_yaml(job, spec)
            t0 = time.time()
            try:
                with open(job / "log.txt", "a", encoding="utf-8") as lf:
                    lf.write(f"--- {time.strftime('%Y-%m-%dT%H:%M:%S')} attempt {attempt + 1}/{tries}\n")
                    lf.flush()
                    subprocess.run(self.command(node, job), cwd=REPO, env=env, stdout=lf, stderr=subprocess.STDOUT,
                                   timeout=spec["timeout"], start_new_session=False)
                res = read_result(job) or {"status": "fail", "outputs": {}, "log": "exited without result.json"}
            except subprocess.TimeoutExpired:
                res = {"status": "fail", "outputs": {}, "log": f"timeout after {spec['timeout']} s"}
            secs = time.time() - t0
            self.event(ev="step", node=node["node"], job=str(job.relative_to(self.root)), attempt=attempt + 1,
                       status=res["status"], seconds=round(secs, 1), cost_usd=res.get("cost_usd", 0), log=res.get("log", "")[:300])
            log(f"  {node['node']:<16} {res['status']:<4} {secs:6.1f}s  {res.get('log', '')[:140]}")
            if res["status"] != "fail" or attempt + 1 == tries or self.stopping():
                break
            time.sleep(min(60, 5 * 2 ** attempt))
        return res

    def run_stage(self, stage: str, base: Path, env: dict) -> tuple[str, dict]:
        """Run every node of a per-item stage in base/<NN-node>/. env: output name -> path relative to base (updated)."""
        for i, node in enumerate(self.ch[stage]):
            job = base / f"{stage[0]}{i:02d}-{node['node']}"
            ins = {k: base / env[k] for k in node.get("in", [])}
            res = self.run_step(node, job, ins)
            if res["status"] != "ok":
                return res["status"], env
            for k in node.get("out", []):
                if k not in res["outputs"]:
                    log(f"  {node['node']}: declared output {k!r} missing from result.json")
                    return "fail", env
                env[k] = os.path.relpath(job / res["outputs"][k], base)
            (base / "item.json").write_text(json.dumps({**self.item_meta(base), "outputs": env}))
        return "ok", env

    @staticmethod
    def item_meta(base: Path) -> dict:
        p = base / "item.json"
        return json.loads(p.read_text()) if p.exists() else {}

    # ------------------------------------------------------------------ producer --------------------------------
    def next_id(self) -> str:
        p = self.root / "state" / "seq"
        n = int(p.read_text() or 0) + 1 if p.exists() else 1
        p.write_text(str(n))
        return f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{n:05d}"

    def queued(self) -> int:
        return sum(1 for p in (self.root / "inbox").iterdir() if p.is_dir())

    def produce_one(self) -> bool:
        # resume a half-made item from before a restart, else start a new one
        old = sorted(p for p in (self.root / "producing").iterdir() if p.is_dir())
        base = old[0] if old else self.root / "producing" / self.next_id()
        if not old:
            base.mkdir(parents=True)
            (base / "item.json").write_text(json.dumps({"id": base.name, "made": time.time(), "outputs": {}}))
        env = self.item_meta(base).get("outputs", {})
        st, env = self.run_stage("producer", base, env)
        if st == "ok":
            meta = self.item_meta(base)
            meta["queued"] = time.time()
            (base / "item.json").write_text(json.dumps(meta))
            os.replace(base, self.root / "inbox" / base.name)
            log(f"queued item {base.name} ({self.queued()} waiting)")
            return True
        os.replace(base, self.root / "failed" / base.name)
        self.event(ev="item_failed", stage="producer", item=base.name, status=st)
        return False

    def producer_loop(self):
        last, fails = 0.0, 0
        while not self.stopping():
            try:
                if self.queued() < self.cad["queue_ahead"] and time.time() - last >= self.cad["produce_every"]:
                    last = time.time()
                    if self.produce_one():
                        fails = 0
                        continue
                    fails += 1
                    self.stop_ev.wait(min(300, 10 * 2 ** min(fails, 5)))  # back off on repeated failure
                    continue
            except Exception as e:  # never die: log, wait, retry
                log(f"producer error: {e!r}")
                self.save_status(last_error=f"producer: {e!r}"[:300])
                self.stop_ev.wait(30)
            self.stop_ev.wait(self.cad["poll"])

    # ------------------------------------------------------------------ worker ----------------------------------
    def take_batch(self, now: float | None = None) -> list[Path]:
        now = time.time() if now is None else now
        items = sorted((p for p in (self.root / "inbox").iterdir() if p.is_dir()), key=lambda p: p.name)
        if not items:
            return []
        n = self.cad["block_items"]
        oldest = self.item_meta(items[0]).get("queued", items[0].stat().st_mtime)
        if len(items) >= n or now - oldest > self.cad["max_wait"]:
            return items[:n]
        return []

    def work_block(self, batch: list[Path]) -> bool:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        moved = []
        for p in batch:
            dst = self.root / "working" / p.name
            os.replace(p, dst)
            moved.append(dst)
        ok_items = []
        for base in moved:
            st, env = self.run_stage("item", base, self.item_meta(base).get("outputs", {}))
            if st == "ok":
                ok_items.append((base, env))
            else:
                os.replace(base, self.root / "failed" / base.name)
                self.event(ev="item_failed", stage="item", item=base.name, status=st)
                self.save_status(failed_items=self.status["failed_items"] + 1)
        if not ok_items:
            return False
        bdir = self.root / "work" / ts
        lists = {}
        for base, env in ok_items:
            for k, v in env.items():
                lists.setdefault(k, []).append(base / v)
        single: dict[str, Path] = {}
        res = {"status": "fail"}
        for i, node in enumerate(self.ch["block"]):
            job = bdir / f"b{i:02d}-{node['node']}"
            ins = {k: (single[k] if k in single else lists[k]) for k in node.get("in", [])}
            res = self.run_step(node, job, ins)
            if res["status"] != "ok":
                break
            for k in node.get("out", []):
                single[k] = job / res["outputs"].get(k, k)
        if res["status"] != "ok":
            log(f"BLOCK FAILED {ts}: work kept in {bdir}; items moved to failed/")
            for base, _ in ok_items:
                os.replace(base, self.root / "failed" / base.name)
            self.event(ev="block_failed", block=ts, items=[b.name for b, _ in ok_items])
            self.save_status(last_error=f"block {ts}: {res.get('log', '')}"[:300])
            return False
        for base, _ in ok_items:
            (self.root / "done" / f"{base.name}.json").write_text(json.dumps(self.item_meta(base)))
            shutil.rmtree(base, ignore_errors=True)
        pub = read_result(bdir / f"b{len(self.ch['block']) - 1:02d}-publish") or {}
        self.event(ev="published", block=ts, items=len(ok_items), log=pub.get("log", "")[:300])
        log(f"ON AIR block {ts}: {len(ok_items)} item(s) | {pub.get('log', '')[:160]}")
        self.save_status(blocks=self.status["blocks"] + 1, items=self.status["items"] + len(ok_items),
                         last_publish=time.time(), last_publish_log=pub.get("log", "")[:300])
        shutil.rmtree(bdir, ignore_errors=True)
        return True

    def prune_local(self) -> int:
        cap = int(float(self.ch["storage"]["local_cap_gb"]) * 1e9)

        def size(p: Path) -> int:
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
        items = [p for d in ("work", "failed", "done") for p in (self.root / d).iterdir()]
        total = sum(size(p) for p in items)
        removed = 0
        for p in sorted(items, key=lambda p: p.stat().st_mtime):
            if total <= cap:
                break
            total -= size(p)
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            removed += 1
        return removed

    def recover(self):
        """Items that were being worked on when the process stopped go back to the inbox (their ok steps are kept)."""
        for p in (self.root / "working").iterdir():
            if p.is_dir():
                os.replace(p, self.root / "inbox" / p.name)
                log(f"recovered item {p.name} into the inbox")

    def run(self, producer: bool = True, worker: bool = True) -> int:
        self.recover()
        self.save_status()
        c = self.cad
        log(f"channel {self.ch['channel']} from {self.ch['_path']}: prefix {self.ch['prefix']!r}, root {self.root}, "
            f"queue_ahead {c['queue_ahead']}, block_items {c['block_items']}, max_wait {c['max_wait']}s"
            f"{', DRY RUN' if self.dry_run else ''}")
        for st in STAGES:
            log(f"  {st}: " + " -> ".join(f"{n['node']}({n.get('run') or n.get('cmd')})" for n in self.ch[st]))
        t = None
        if producer:
            t = threading.Thread(target=self.producer_loop, name="producer", daemon=True)
            t.start()
        published = 0
        try:
            while worker and not self.stopping():
                try:
                    batch = self.take_batch()
                    if not batch:
                        self.stop_ev.wait(c["poll"])
                        continue
                    if self.work_block(batch):
                        published += 1
                    else:
                        self.stop_ev.wait(10)
                    if self.prune_local():
                        log(f"local cache over {self.ch['storage']['local_cap_gb']} GB: pruned oldest work/failed/done")
                    if self.max_blocks and published >= self.max_blocks:
                        break
                except Exception as e:
                    log(f"worker error: {e!r}")
                    self.save_status(last_error=f"worker: {e!r}"[:300])
                    self.stop_ev.wait(30)
            if not worker and t:
                while not self.stopping():
                    self.stop_ev.wait(1)
        finally:
            self.stop_ev.set()
            if t:
                t.join(timeout=5)
        log("stopped")
        return 0


def install_signals(r: Runner):
    def h(signum, _frame):
        log(f"signal {signum}: stopping after the current step")
        r.stop_ev.set()
    signal.signal(signal.SIGTERM, h)
    signal.signal(signal.SIGINT, h)
