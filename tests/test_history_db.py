"""D1 history client against a fake Cloudflare API (no network): schema, lookup/create by name, upsert, load, auth."""
import io
import json
import urllib.error
from pathlib import Path

import pytest

from newsbot import history_db


class FakeCF:
    """Minimal D1 REST fake: records every request, serves list/create/query. `auth` False -> 403 code 10000."""
    def __init__(self, auth=True, exists=True):
        self.auth, self.exists, self.reqs, self.rows = auth, exists, [], {"episodes": {}, "stories": {}, "claims": {}}
        self.sql = []

    def __call__(self, req, timeout=0):
        body = json.loads(req.data) if req.data else None
        self.reqs.append((req.get_method(), req.full_url, body))
        assert req.get_header("Authorization") == "Bearer s3cr3t-value"
        if not self.auth:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(json.dumps(
                {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}).encode()))
        path = req.full_url.split("/accounts/acct")[1]
        if path.startswith("/d1/database?name="):
            res = [{"uuid": "db-1", "name": "ai247-history"}] if self.exists else []
        elif path == "/d1/database" and req.get_method() == "POST":
            self.exists, res = True, {"uuid": "db-new", "name": body["name"]}
        elif path.endswith("/query"):
            res = [{"results": self.run(body["sql"], body.get("params") or []), "success": True}]
        else:
            raise AssertionError(path)
        return io.BytesIO(json.dumps({"success": True, "errors": [], "result": res}).encode())

    def run(self, sql, params):
        self.sql.append(sql)
        s = sql.strip().upper()
        if s.startswith("CREATE"):
            return []
        if s.startswith("INSERT OR REPLACE INTO EPISODES"):
            self.rows["episodes"][params[0]] = {"run_id": params[0], "ts": params[1], "entry": params[8]}
        elif s.startswith("INSERT OR REPLACE INTO STORIES"):
            self.rows["stories"][(params[0], params[1])] = params
        elif s.startswith("INSERT OR IGNORE INTO CLAIMS"):
            self.rows["claims"][(params[0], params[1])] = params
        elif s.startswith("DELETE FROM STORIES"):
            self.rows["stories"] = {k: v for k, v in self.rows["stories"].items() if k[0] != params[0]}
        elif s.startswith("DELETE FROM CLAIMS"):
            self.rows["claims"] = {k: v for k, v in self.rows["claims"].items() if k[0] != params[0]}
        elif s.startswith("SELECT ENTRY FROM EPISODES"):
            return [{"entry": r["entry"]} for r in sorted(self.rows["episodes"].values(), key=lambda r: r["ts"], reverse=True)][: params[0]]
        elif s.startswith("SELECT RUN_ID"):
            return [{"run_id": k} for k in self.rows["episodes"]]
        elif s.startswith("SELECT URL"):
            return [{"url": k[1]} for k in self.rows["stories"]]
        return []


ENTRY = {"run_id": "4242", "ts": "2026-11-06T14:00:00Z", "topic": "agent-harnesses", "mode": "topic", "published": True,
         "stories": [{"source": "OpenAI", "url": "https://openai.com/a", "headline": "A"}, {"source": "X", "url": "https://x/b", "headline": "B"}],
         "sentence_sha256": ["aaaa", "bbbb", "cccc"], "cost_usd": 0.0123, "model": "claude-haiku-5-5", "r2_prefix": "bulletins/x"}


def test_schema_is_idempotent_statements_from_the_worker_migration():
    stmts = history_db._split_sql(Path("worker/migrations/0001_history.sql").read_text())
    assert len(stmts) == 6 and all("IF NOT EXISTS" in s for s in stmts) and stmts[0].startswith("CREATE TABLE IF NOT EXISTS episodes")


def test_round_trip_create_schema_upsert_load_without_network(monkeypatch):
    monkeypatch.delenv("D1_DATABASE_ID", raising=False)
    fake = FakeCF(exists=False)
    db = history_db.D1(token="s3cr3t-value", account="acct", opener=fake)
    history_db._SCHEMA_DONE.clear()
    assert db.database_id() == "db-new"                       # created by name, once
    assert db.ensure_schema() == 6 and db.ensure_schema() == 0  # second call is a no-op in-process
    db.upsert(ENTRY)
    h = db.load()
    assert h["backend"] == "d1" and h["episodes"] == [ENTRY]
    assert db.covered_urls() == {"https://openai.com/a", "https://x/b"} and db.run_ids() == {"4242"}
    assert len(fake.rows["claims"]) == 3
    # params are bound, never interpolated into SQL
    assert all("openai.com" not in sql for sql in fake.sql)
    # no secret or account id is ever in a log line: the only place they appear is the request itself
    assert "s3cr3t" not in json.dumps(h)


def test_auth_error_names_the_missing_permission(monkeypatch):
    monkeypatch.delenv("D1_DATABASE_ID", raising=False)
    db = history_db.D1(token="s3cr3t-value", account="acct", opener=FakeCF(auth=False))
    with pytest.raises(history_db.D1Unavailable) as ei:
        db.database_id()
    assert ei.value.needs_you and "D1 -> Edit" in ei.value.needs_you and "s3cr3t" not in str(ei.value) and "acct" not in str(ei.value)


def test_unconfigured_raises_cleanly(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    assert not history_db.configured()
    with pytest.raises(history_db.D1Unavailable):
        history_db.D1()
