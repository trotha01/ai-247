"""Hourly run planner and reporter for the `hourly-bulletins` workflow (docs/PLAN.md "Hourly cadence").

Trevor's rule: if the cron runs once an hour, each run must produce at least an hour of new footage. One run = one
feed fetch, dealt into N slices of stories; every slice renders a 10-minute bulletin in parallel (`python -m
newsbot.day1 --items-json plan/slice_<i>.json`), and the stitch job publishes them in slice order as the fresh blocks
of one root manifest (`newsbot.publish --run-ts`).

    python -m newsbot.hourly plan --out plan --slices 6 [--items-json fixture.json]
    python -m newsbot.hourly summary plan bulletins/*          # Markdown for $GITHUB_STEP_SUMMARY

Planning rules (pure functions, tested in tests/test_hourly.py):
  - candidates = items with enough summary text, de-duplicated across the whole run (same URL or near-identical title);
  - stories that already aired come last: `aired_urls` reads the `sources` of the newest per-bulletin manifests in
    R2 (bulletins/<id>/manifest.json), so never-aired stories go first, then the ones aired longest ago. The feeds do
    not supply 60 minutes of never-aired text per hour (about 110 items from 8 feeds, refreshing slowly), so repeats
    are spread as thinly as possible rather than avoided; the plan report counts them (`never_aired` per slice);
  - dealing: in that order, each story goes to the emptiest slice that still has room for its source (at most
    `--max-per-source` per slice, `--per-slice` stories per slice), so every bulletin mixes sources and the fresh
    stories are spread over the hour. A slice must have at least `--min-slice-items` stories or it is not rendered;
    the number of slices shrinks (never below 1) when the supply is short, and the plan says so.
No secrets are printed; R2 credentials come from the environment (boto3) and the aired-URL lookup is best effort.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import feeds as feedmod
from . import r2, rank, replay_pool

SLICES = 6
PER_SLICE = 14           # rank picks the 12 best inside the slice; 2 spare for stories the gate drops
MAX_PER_SOURCE = 4       # per slice (NEWSBOT_PER_SOURCE_CAP in the render job must be >= this)
MIN_SLICE_ITEMS = 8
AIRED_MANIFESTS = 150    # newest per-bulletin manifests read for the aired-URL memory (~25 hours at 6 per hour)


# ---------------------------------------------------------------- aired memory ---------------------------------
def bulletin_manifest_keys(s3, bucket: str, prefix: str = replay_pool.BULLETIN_PREFIX) -> list[str]:
    """`bulletins/<id>/manifest.json` keys, newest first, from a delimiter listing of the `bulletins/<id>/` prefixes
    only (one page per 1000 bulletins), not of every segment object ever published."""
    ids, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix, "Delimiter": "/"}
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        ids += [c["Prefix"] for c in r.get("CommonPrefixes", [])]
        if not r.get("IsTruncated"):
            break
        token = r.get("NextContinuationToken")
    return [f"{p}manifest.json" for p in sorted(ids, reverse=True)]


def aired_urls(s3, bucket: str, max_manifests: int = AIRED_MANIFESTS, threads: int = 8) -> tuple[dict[str, str], dict]:
    """url -> id of the newest bulletin that aired it, from `sources` of the newest bulletins/<id>/manifest.json in R2.
    Returns ({}, report) with the error named when R2 cannot be read; nothing here fails a run."""
    report = {"ok": False, "manifests_read": 0, "urls": 0, "error": None}
    try:
        keys = bulletin_manifest_keys(s3, bucket)[:max_manifests]
    except Exception as e:
        report["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return {}, report

    def read(key):
        try:
            return key, replay_pool._get_json(s3, bucket, key)
        except Exception:
            return key, None

    out: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, threads)) as ex:
        results = list(ex.map(read, keys))
    for key, m in results:  # newest first: the first id seen for a url is the newest airing
        if not m:
            continue
        report["manifests_read"] += 1
        bid = key.rsplit("/", 2)[-2]
        for s in m.get("sources", []) or []:
            url = s.get("url")
            if url and url not in out:
                out[url] = bid
    report.update(ok=True, urls=len(out))
    return out, report


# ---------------------------------------------------------------- planning -------------------------------------
def candidates(items, now: float, aired: dict[str, str]) -> list:
    """De-duplicated, narratable items: never-aired first (best score first), then aired ones, oldest airing first."""
    pool = [i for i in items if len((i.summary or "").strip()) >= rank.MIN_SUMMARY_CHARS]
    scored = sorted(pool, key=lambda i: (-rank.score(i, now), i.url))
    deduped = []
    for it in scored:
        if not any(rank.is_duplicate(it, c) for c in deduped):
            deduped.append(it)
    return sorted(deduped, key=lambda i: (1 if i.url in aired else 0, aired.get(i.url, ""), -rank.score(i, now), i.url))


def deal(cands: list, slices: int, per_slice: int = PER_SLICE, max_per_source: int = MAX_PER_SOURCE) -> list[list]:
    """Deal ordered candidates into `slices` lists: each goes to the emptiest slice with room for its source."""
    out = [[] for _ in range(slices)]
    per = [defaultdict(int) for _ in range(slices)]
    for it in cands:
        best = None
        for j in range(slices):
            if len(out[j]) >= per_slice or per[j][it.source] >= max_per_source:
                continue
            if best is None or len(out[j]) < len(out[best]):
                best = j
        if best is None:
            continue
        out[best].append(it)
        per[best][it.source] += 1
    return out


def plan(items, reports, now: float, aired: dict[str, str], slices: int = SLICES, per_slice: int = PER_SLICE,
         max_per_source: int = MAX_PER_SOURCE, min_slice_items: int = MIN_SLICE_ITEMS) -> dict:
    """The run plan: slices of items (fixture shape for newsbot.day1 --items-json) plus a report."""
    cands = candidates(items, now, aired)
    n = max(1, min(slices, len(cands) // max(1, min_slice_items)))
    dealt = deal(cands, n, per_slice, max_per_source)
    dealt = [s for s in dealt if len(s) >= min_slice_items] or dealt[:1]
    never = [i for i in cands if i.url not in aired]
    return {
        "run_ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now)),
        "slices_wanted": slices, "slices": len(dealt), "items_total": len(items), "candidates": len(cands),
        "never_aired": len(never), "aired_known": sum(1 for i in cands if i.url in aired),
        "shortfall": None if len(dealt) == slices else f"only {len(cands)} candidate stories for {slices} slices of >= {min_slice_items}",
        "slice_items": [[i.__dict__ for i in s] for s in dealt],
        "slice_report": [{"slice": j, "items": len(s), "never_aired": sum(1 for i in s if i.url not in aired),
                          "sources": dict(Counter(i.source for i in s))} for j, s in enumerate(dealt)],
        "feeds": reports,
    }


def write_plan(p: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for j, items in enumerate(p["slice_items"]):
        (out / f"slice_{j}.json").write_text(json.dumps({"items": items, "reports": p["feeds"], "slice": j, "run_ts": p["run_ts"]}, indent=1))
    (out / "slices.json").write_text(json.dumps(list(range(p["slices"]))))
    (out / "plan.json").write_text(json.dumps({k: v for k, v in p.items() if k != "slice_items"}, indent=1))


# ---------------------------------------------------------------- summary --------------------------------------
def summary_markdown(plan_dir: Path, bulletin_dirs: list[Path]) -> str:
    """Job summary for the stitch job: footage, per-slice facts, cost, novelty."""
    p = json.loads((plan_dir / "plan.json").read_text())
    rows, cost, sentences, footage = [], 0.0, 0, 0.0
    pub = None
    for d in bulletin_dirs:
        rp = d / "report.json"
        if not rp.exists():
            rows.append(f"| `{d.name}` | missing report.json (render failed?) | | | | | |")
            continue
        r = json.loads(rp.read_text())
        ll, au = r.get("llm", {}), r.get("audit", {})
        c = float(ll.get("cost_usd_estimate", 0) or 0) if ll.get("used") else 0.0
        cost += c
        sentences += int(au.get("aired_sentences", 0))
        footage += float(r.get("episode_seconds", 0))
        rows.append(f"| `{d.name}` | {r.get('episode_seconds')} s / {r.get('segments')} seg | {r.get('rundown_stories')} from {len(r.get('rundown_sources', []))} sources | "
                    f"{au.get('aired_sentences')} ({au.get('supported_pct')}% supported) | `{r.get('script_by')}` | {c:.4f} | {r.get('total_seconds')} s |")
        if pub is None and (d / "publish.json").exists():
            pub = json.loads((d / "publish.json").read_text())
    out = ["## Hourly bulletins run", "",
           f"- Run `{p['run_ts']}`: **{footage / 60:.1f} min of new footage** from {len(bulletin_dirs)} bulletin(s) "
           f"({p['slices']} of {p['slices_wanted']} slices planned{'; ' + p['shortfall'] if p.get('shortfall') else ''}); "
           f"{'**below the 60-minute hourly target**' if footage < 3600 else 'meets the 60-minute hourly target'}",
           f"- Stories: {p['candidates']} candidates from {p['items_total']} items ({len([f for f in p['feeds'] if f.get('ok')])} feeds); "
           f"{p['never_aired']} never aired before, {p['aired_known']} aired earlier (aired memory: {p.get('aired_store', {})})",
           f"- Aired sentences: {sentences}; Claude cost this run: **{cost:.4f} USD** (per-slice cap 0.05 USD; LLM slices per run set by HOURLY_LLM_SLICES)"]
    if pub:
        out.append(f"- Published: {pub['fresh_blocks']} fresh block(s) starting at `{pub['prefix']}`, {pub['objects']} objects / {pub['bytes']} bytes, "
                   f"root manifest `cycle_start_k` {pub['cycle_start_k']}, `loop_from` {pub['loop_from']}, fresh {pub['fresh_minutes']} min, "
                   f"blocks {[(k, n) for k, _, n in pub['blocks']]}, inherited pending blocks {pub['inherited_blocks']}")
    else:
        out.append("- Published: nothing (no publish.json; R2 secrets missing or the publish step failed)")
    out += ["", "| bulletin | length | rundown | aired sentences | script | Claude USD | pipeline |", "|---|---|---|---|---|---|---|", *rows, "",
            "| slice | items dealt | never aired | sources |", "|---|---|---|---|"]
    for s in p["slice_report"]:
        out.append(f"| {s['slice']} | {s['items']} | {s['never_aired']} | {', '.join(f'{k} {v}' for k, v in sorted(s['sources'].items()))} |")
    out += ["", "| feed | ok | robots | items | note |", "|---|---|---|---|---|"]
    for f in p["feeds"]:
        out.append(f"| {f.get('name')} | {f.get('ok')} | {f.get('robots')} | {f.get('items')} | {f.get('note', '')} |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- CLI ------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="fetch feeds once and deal them into slices")
    pl.add_argument("--out", default="plan")
    pl.add_argument("--slices", type=int, default=SLICES)
    pl.add_argument("--per-slice", type=int, default=PER_SLICE)
    pl.add_argument("--max-per-source", type=int, default=MAX_PER_SOURCE)
    pl.add_argument("--min-slice-items", type=int, default=MIN_SLICE_ITEMS)
    pl.add_argument("--items-json", help="offline: use saved items instead of fetching")
    pl.add_argument("--no-aired", action="store_true", help="skip the R2 aired-URL lookup")
    sm = sub.add_parser("summary", help="Markdown job summary: plan dir then bulletin output dirs")
    sm.add_argument("plan_dir")
    sm.add_argument("bulletins", nargs="*")
    a = ap.parse_args(argv)

    if a.cmd == "summary":
        print(summary_markdown(Path(a.plan_dir), [Path(b) for b in a.bulletins]))
        return 0

    now = time.time()
    t0 = time.time()
    if a.items_json:
        data = json.loads(Path(a.items_json).read_text())
        items, reports = [feedmod.Item(**d) for d in data["items"]], data.get("reports", [])
    else:
        items, reports = feedmod.fetch_all(max_feeds=len(feedmod.CANDIDATES))  # every working candidate: supply matters
        reports = feedmod.reports_json(reports)
    print(f"{len(items)} items from {sum(1 for r in reports if r.get('ok'))} working feeds in {time.time() - t0:.1f} s")

    aired, store = {}, {"ok": False, "error": "skipped"}
    if not a.no_aired and r2.r2_configured():
        t1 = time.time()
        aired, store = aired_urls(r2.client(), r2.bucket())
        store["seconds"] = round(time.time() - t1, 1)
    elif not a.no_aired:
        store["error"] = "R2 secrets not set"
    print("aired memory:", json.dumps(store))

    p = plan(items, reports, now, aired, a.slices, a.per_slice, a.max_per_source, a.min_slice_items)
    p["aired_store"] = store
    write_plan(p, Path(a.out))
    print("PLAN", json.dumps({k: v for k, v in p.items() if k not in ("slice_items", "feeds")}, indent=1))
    if p["slices"] < a.slices:
        print(f"::warning::{p['shortfall']}; rendering {p['slices']} bulletin(s) ({p['slices'] * 10} min) this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
