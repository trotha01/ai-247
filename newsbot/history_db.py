"""Episode history in Cloudflare D1 (docs/TOPICS.md, "Persistence"), reached through the Cloudflare REST API.

    db = history_db.D1()                 # needs CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID (never printed)
    db.ensure_schema()                   # creates the database (by name) and runs worker/migrations/*.sql, idempotent
    h = db.load()                        # {"version": 1, "episodes": [...]} newest last, like the old history.json
    db.upsert(entry)                     # one episode: episodes row + stories rows + claims rows

Why REST and not `wrangler d1 execute`: the Actions job then needs no Node install, and the query endpoint takes
bound parameters, so no SQL string building. The Worker reads the same database through its D1 binding
(`/history.json`). Auth/permission failures raise D1Unavailable with the exact permission Trevor must add
(Account -> D1 -> Edit on CLOUDFLARE_API_TOKEN); callers fall back to the R2 mirror and report `needs_you`.
Secrets are read from the environment and never logged; URLs that contain the account id are never printed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"
DB_NAME = os.environ.get("D1_DATABASE_NAME", "ai247-history")
MIGRATIONS = Path(__file__).resolve().parent.parent / "worker" / "migrations"
PERMISSION = "Cloudflare API token permission Account -> D1 -> Edit (the token currently has Workers Scripts: Edit and Pages: Edit)"
MAX_EPISODES = 500
_SCHEMA_DONE: set[str] = set()


class D1Unavailable(RuntimeError):
    """D1 cannot be used in this run. `needs_you` is set when only Trevor can fix it (permissions)."""
    def __init__(self, msg: str, needs_you: str | None = None):
        super().__init__(msg)
        self.needs_you = needs_you


def configured() -> bool:
    return bool(os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID"))


def _split_sql(text: str) -> list[str]:
    body = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


class D1:
    def __init__(self, token: str | None = None, account: str | None = None, name: str = DB_NAME, opener=None, timeout: float = 30.0):
        self.token = token or os.environ.get("CLOUDFLARE_API_TOKEN", "")
        self.account = account or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        self.name, self.timeout = name, timeout
        self._open = opener or urllib.request.urlopen
        self._id: str | None = os.environ.get("D1_DATABASE_ID") or None
        if not (self.token and self.account):
            raise D1Unavailable("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID not set")

    # ------------------------------------------------------------------ HTTP
    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{API}/accounts/{self.account}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self._open(req, timeout=self.timeout) as r:
                payload = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                payload = {"success": False, "errors": [{"code": e.code, "message": f"HTTP {e.code}"}]}
            payload.setdefault("_http", e.code)
        except Exception as e:  # DNS, timeout, TLS: no secrets in the message
            raise D1Unavailable(f"D1 API unreachable: {type(e).__name__}")
        if not payload.get("success", False):
            errs = payload.get("errors") or []
            codes = {int(x.get("code", 0)) for x in errs if isinstance(x, dict)}
            msgs = "; ".join(str(x.get("message", ""))[:120] for x in errs if isinstance(x, dict)) or "unknown error"
            http = payload.get("_http")
            if http in (401, 403) or codes & {9109, 10000, 10001, 7000, 7003}:
                raise D1Unavailable(f"D1 API refused the token ({msgs})", needs_you=f"Add {PERMISSION}")
            raise D1Unavailable(f"D1 API error: {msgs}")
        return payload

    # ------------------------------------------------------------------ database
    def database_id(self, create: bool = True) -> str:
        if self._id:
            return self._id
        res = self._req("GET", f"/d1/database?name={self.name}")
        for d in res.get("result") or []:
            if d.get("name") == self.name:
                self._id = d["uuid"]
                return self._id
        if not create:
            raise D1Unavailable(f"D1 database {self.name!r} does not exist")
        res = self._req("POST", "/d1/database", {"name": self.name})
        self._id = (res.get("result") or {})["uuid"]
        return self._id

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        res = self._req("POST", f"/d1/database/{self.database_id()}/query", {"sql": sql, "params": params or []})
        out = []
        for part in res.get("result") or []:
            out += part.get("results") or []
        return out

    def ensure_schema(self, migrations: Path = MIGRATIONS) -> int:
        """Run every statement of worker/migrations/*.sql (all IF NOT EXISTS). Returns the statement count."""
        key = self.database_id()
        if key in _SCHEMA_DONE:
            return 0
        n = 0
        for f in sorted(Path(migrations).glob("*.sql")):
            for stmt in _split_sql(f.read_text()):
                self.query(stmt)
                n += 1
        _SCHEMA_DONE.add(key)
        return n

    # ------------------------------------------------------------------ history
    def load(self, limit: int = MAX_EPISODES) -> dict:
        rows = self.query("SELECT entry FROM episodes ORDER BY ts DESC LIMIT ?", [limit])
        eps = []
        for r in rows:
            try:
                eps.append(json.loads(r["entry"]))
            except Exception:
                continue
        eps.sort(key=lambda e: e.get("ts", ""))
        return {"version": 1, "episodes": eps, "backend": "d1"}

    def upsert(self, entry: dict) -> None:
        run_id = str(entry.get("run_id"))
        self.query("INSERT OR REPLACE INTO episodes (run_id, ts, topic, mode, published, r2_prefix, cost_usd, model, entry) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   [run_id, entry.get("ts", ""), entry.get("topic"), entry.get("mode"), 1 if entry.get("published") else 0,
                    entry.get("r2_prefix"), float(entry.get("cost_usd") or 0.0), entry.get("model"),
                    json.dumps(entry, separators=(",", ":"), ensure_ascii=False)])
        self.query("DELETE FROM stories WHERE run_id = ?", [run_id])
        self.query("DELETE FROM claims WHERE run_id = ?", [run_id])
        for s in entry.get("stories", []):
            if s.get("url"):
                self.query("INSERT OR REPLACE INTO stories (run_id, url, source, headline) VALUES (?, ?, ?, ?)",
                           [run_id, s["url"], s.get("source"), (s.get("headline") or "")[:300]])
        for sha in entry.get("sentence_sha256", []):
            self.query("INSERT OR IGNORE INTO claims (run_id, sha16) VALUES (?, ?)", [run_id, str(sha)[:16]])

    # ------------------------------------------------------------------ discovered topics
    def load_topics(self) -> list[dict]:
        """Topics the discovery lane added, oldest first (the durable copy; topics.json may lag on main)."""
        out = []
        for r in self.query("SELECT entry FROM discovered_topics ORDER BY added, id"):
            try:
                out.append(json.loads(r["entry"]))
            except Exception:
                continue
        return out

    def upsert_topic(self, entry: dict) -> None:
        self.query("INSERT OR REPLACE INTO discovered_topics (id, added, entry) VALUES (?, ?, ?)",
                   [str(entry["id"]), str(entry.get("added", "")), json.dumps(entry, separators=(",", ":"), ensure_ascii=False)])

    def run_ids(self) -> set[str]:
        return {str(r["run_id"]) for r in self.query("SELECT run_id FROM episodes")}

    def covered_urls(self) -> set[str]:
        return {r["url"] for r in self.query("SELECT url FROM stories")}


def main(argv=None) -> int:
    """python -m newsbot.history_db [status|load]: a read-only check, prints no secrets."""
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if not configured():
        print("D1 not configured (CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID unset)")
        return 2
    try:
        db = D1()
        db.ensure_schema()
        h = db.load()
        print(f"D1 {db.name}: database_id={db.database_id()} episodes={len(h['episodes'])}")
        if argv[:1] == ["load"]:
            print(json.dumps(h, indent=1)[:4000])
        return 0
    except D1Unavailable as e:
        print(f"D1 unavailable: {e}" + (f"\nNEEDS_YOU: {e.needs_you}" if e.needs_you else ""))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
