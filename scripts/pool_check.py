#!/usr/bin/env python3
"""Check the replay pool after a refresh (docs/FAILOVER.md): `pool/manifest.json` is in R2, verifies complete, equals
the manifest the refresh wrote/kept, and the live Worker's `/healthz` reports the pool as usable.

    python scripts/pool_check.py --manifest pool-manifest.json --url https://ai247-live.<acct>.workers.dev [--wait 120]

R2 is checked only when the R2_* secrets are in the environment (never printed). The Worker is checked only when a
URL is given (or site/config.json has a streamUrl). The pool cache in the Worker is 60 s (POOL_TTL_MS), so /healthz
is polled for up to --wait seconds until `pool.built_at` equals the local manifest's; a usable pool with another
built_at (other isolate / cache) is a warning, an unusable pool is a failure. Exit 0 ok, 1 failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from newsbot import r2, replay_pool  # noqa: E402


def healthz_verdict(h: dict, want_built_at: str | None) -> str:
    """"match" (usable pool with the expected built_at), "usable" (usable pool, other built_at) or "bad"."""
    p = h.get("pool") or {}
    if not (p.get("ok") and (p.get("segments") or 0) > 0):
        return "bad"
    return "match" if not want_built_at or p.get("built_at") == want_built_at else "usable"


def describe(h: dict) -> str:
    m, p = h.get("manifest") or {}, h.get("pool") or {}
    return (f"/healthz: ok={h.get('ok')} source={h.get('source')} reason={h.get('reason')} "
            f"manifest.age_s={m.get('age_s')} max_age_s={m.get('max_age_s')} manifest.problem={m.get('problem')} "
            f"pool.ok={p.get('ok')} pool.problem={p.get('problem')} pool.segments={p.get('segments')} pool.built_at={p.get('built_at')}")


def worker_url_from_site() -> str:
    try:
        u = json.loads(Path("site/config.json").read_text()).get("streamUrl") or ""
    except Exception:
        return ""
    return u.rsplit("/", 1)[0] if "/" in u else ""


def check_r2(local: dict, pool_key: str, key_prefix: str = "") -> bool:
    s3, b = replay_pool.channel_client(replay_pool.check_key_prefix(key_prefix)), r2.bucket()
    h = s3.head_object(Bucket=b, Key=pool_key)
    print(f"R2 {pool_key}: {h['ContentLength']} bytes, last modified {h['LastModified']:%Y-%m-%dT%H:%M:%SZ}")
    m = replay_pool.existing_pool(s3, b, pool_key) or {}
    problem = replay_pool.verify_pool(s3, b, m)
    print(f"R2 pool: ok={problem is None} problem={problem} segments={len(replay_pool.segment_keys(m))} built_at={m.get('built_at')} "
          f"blocks={[x.get('id') for x in m.get('blocks', [])]}")
    if problem:
        print(f"FAIL: {pool_key} in R2 is not usable")
        return False
    if replay_pool.segment_keys(m) != replay_pool.segment_keys(local):
        print(f"FAIL: {pool_key} in R2 differs from the manifest this run wrote/kept")
        return False
    return True


def check_worker(url: str, want_built_at: str | None, wait_s: int, out: Path | None) -> bool:
    url = url.rstrip("/")
    print(f"checking {url}/healthz (up to {wait_s} s; the Worker's pool cache is 60 s)")
    deadline, last, verdict = time.monotonic() + wait_s, None, "none"
    while True:
        try:
            req = urllib.request.Request(f"{url}/healthz?rp={int(time.time())}", headers={"User-Agent": "ai247-pool-check/1", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                last = json.loads(r.read())
            if out:
                out.write_text(json.dumps(last, indent=1))
            print(describe(last))
            verdict = healthz_verdict(last, want_built_at)
            if verdict == "match":
                break
        except Exception as e:
            print(f"/healthz: {type(e).__name__}: {e}")
        if time.monotonic() >= deadline:
            break
        time.sleep(5)
    if verdict == "match":
        print("verified: the Worker reports the replay pool as usable (built_at matches)")
        return True
    if verdict == "usable":
        print("::warning::/healthz reports a usable pool but not this run's built_at (another isolate or cache); not failing")
        return True
    print(f"::error::{url}/healthz does not report a usable replay pool")
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest", default="pool-manifest.json", help="the pool manifest the refresh wrote/kept")
    ap.add_argument("--url", default=os.environ.get("WORKER_URL") or "", help="Worker base URL (default: $WORKER_URL, else site/config.json)")
    ap.add_argument("--pool-key", default=replay_pool.POOL_KEY)
    ap.add_argument("--key-prefix", default="", help="channel folder in the bucket, e.g. puddle/ (keys are under it)")
    ap.add_argument("--wait", type=int, default=120, help="seconds to poll /healthz")
    ap.add_argument("--healthz-out", default="healthz.json", help="write the last /healthz body here ('' = no)")
    ap.add_argument("--no-r2", action="store_true", help="skip the R2 check even if secrets are set")
    a = ap.parse_args(argv)
    local = json.loads(Path(a.manifest).read_text())
    ok = True
    if a.no_r2:
        print("R2 check skipped (--no-r2)")
    elif r2.r2_configured():
        ok = check_r2(local, a.pool_key, a.key_prefix) and ok
    else:
        print("R2 secrets not set: R2 check skipped")
    url = a.url or worker_url_from_site()
    if not url:
        print("::warning::no Worker URL (WORKER_URL unset, site/config.json streamUrl empty): /healthz not checked")
    else:
        ok = check_worker(url, local.get("built_at"), a.wait, Path(a.healthz_out) if a.healthz_out else None) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
