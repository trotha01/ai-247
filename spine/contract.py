"""The node contract (docs/NODE-CONTRACT.md): a node is a command run on one job folder.

The runner writes JOB/node.yaml (name, inputs, params, channel, state, timeout, gpu) and runs the node's command with
JOB as its last argument (and as the working directory). The node writes its outputs into JOB and then JOB/result.json
LAST, atomically (temp file + rename):

    {"status": "ok" | "skip" | "fail", "outputs": {name: path relative to JOB}, "seconds": float,
     "cost_usd": float, "log": "short human line"}

A command that exits without result.json counts as "fail". Python nodes use `python -m spine.node MODULE:FUNC JOB`
(see `call`), so a node function only reads `Job.inputs/params` and returns its outputs.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATUSES = ("ok", "skip", "fail")
RESULT = "result.json"
NODE_YAML = "node.yaml"


class Skip(Exception):
    """Raise from a node to say 'nothing to do for this job' (status skip, the runner drops the item)."""


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_node_yaml(job: Path, spec: dict) -> Path:
    job.mkdir(parents=True, exist_ok=True)
    p = job / NODE_YAML
    write_atomic(p, yaml.safe_dump(spec, sort_keys=False, allow_unicode=True))
    return p


def write_result(job: Path, status: str, outputs: dict | None = None, seconds: float = 0.0, cost_usd: float = 0.0,
                 log: str = "") -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, not {status!r}")
    r = {"status": status, "outputs": outputs or {}, "seconds": round(seconds, 3), "cost_usd": round(cost_usd, 6),
         "log": log[-2000:]}
    write_atomic(job / RESULT, json.dumps(r, ensure_ascii=False, indent=1))
    return r


def read_result(job: Path) -> dict | None:
    p = job / RESULT
    if not p.exists():
        return None
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "fail", "outputs": {}, "log": f"unreadable result.json: {e!r}"}
    if r.get("status") not in STATUSES:
        return {"status": "fail", "outputs": {}, "log": f"bad status {r.get('status')!r}"}
    return r


@dataclass
class Job:
    """What a Python node function sees: its folder and the parsed node.yaml."""
    dir: Path
    spec: dict = field(default_factory=dict)
    cost_usd: float = 0.0

    @property
    def name(self) -> str:
        return self.spec.get("name", "")

    @property
    def params(self) -> dict:
        return self.spec.get("params") or {}

    @property
    def channel(self) -> dict:
        return self.spec.get("channel") or {}

    @property
    def inputs(self) -> dict:
        """name -> Path, or list of Paths for block nodes (one per item)."""
        out = {}
        for k, v in (self.spec.get("inputs") or {}).items():
            out[k] = [Path(x) for x in v] if isinstance(v, list) else Path(v)
        return out

    @property
    def state(self) -> Path:
        """A folder this node keeps between jobs (e.g. the next lesson number); survives restarts."""
        p = Path(self.spec.get("state") or self.dir / "state")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def out(self, name: str) -> Path:
        return self.dir / name

    @classmethod
    def load(cls, job: Path) -> "Job":
        return cls(job, yaml.safe_load((job / NODE_YAML).read_text(encoding="utf-8")) or {})


def call(func, job_dir: Path) -> dict:
    """Run a Python node function on JOB and write result.json. func(job) returns {output name: path} (absolute or
    relative to JOB) and may return (outputs, log_line). Raise Skip to skip; any other exception is a fail."""
    t0 = time.time()
    job = Job.load(job_dir)
    try:
        ret = func(job)
        outs, line = (ret if isinstance(ret, tuple) else (ret, ""))
        rel = {k: os.path.relpath(Path(v) if Path(v).is_absolute() else job_dir / v, job_dir) for k, v in (outs or {}).items()}
        for k, v in rel.items():
            if not (job_dir / v).exists():
                raise FileNotFoundError(f"node said it wrote {k} = {v}, but it is not there")
        return write_result(job_dir, "ok", rel, time.time() - t0, job.cost_usd, line)
    except Skip as e:
        return write_result(job_dir, "skip", {}, time.time() - t0, job.cost_usd, str(e))
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, flush=True)
        return write_result(job_dir, "fail", {}, time.time() - t0, job.cost_usd, f"{type(e).__name__}: {e}")
