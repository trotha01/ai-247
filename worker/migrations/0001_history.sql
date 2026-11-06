-- Episode history for topic and story dedupe (docs/TOPICS.md). Applied by `wrangler d1 migrations apply` in
-- deploy.yml and, idempotently, by newsbot/history_db.py before the day1 job reads it (every statement is
-- CREATE ... IF NOT EXISTS, so running it twice is harmless).
CREATE TABLE IF NOT EXISTS episodes (
  run_id    TEXT PRIMARY KEY,
  ts        TEXT NOT NULL,
  topic     TEXT,
  mode      TEXT,
  published INTEGER NOT NULL DEFAULT 0,
  r2_prefix TEXT,
  cost_usd  REAL,
  model     TEXT,
  entry     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS episodes_ts ON episodes(ts);
CREATE INDEX IF NOT EXISTS episodes_topic ON episodes(topic, ts);
CREATE TABLE IF NOT EXISTS stories (
  run_id   TEXT NOT NULL,
  url      TEXT NOT NULL,
  source   TEXT,
  headline TEXT,
  PRIMARY KEY (run_id, url)
);
CREATE INDEX IF NOT EXISTS stories_url ON stories(url);
CREATE TABLE IF NOT EXISTS claims (
  run_id TEXT NOT NULL,
  sha16  TEXT NOT NULL,
  PRIMARY KEY (run_id, sha16)
);
