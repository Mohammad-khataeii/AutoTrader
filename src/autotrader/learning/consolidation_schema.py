"""Additive migration for the research SQLite store, never financial databases."""

VERSION = 1
DDL = """
CREATE TABLE IF NOT EXISTS consolidation_versions (
  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS research_content (
  hash TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_sources (
  source TEXT PRIMARY KEY, role TEXT NOT NULL, identity TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_refs (
  source TEXT NOT NULL, kind TEXT NOT NULL, record_id TEXT NOT NULL,
  content_hash TEXT NOT NULL REFERENCES research_content(hash),
  known_at TEXT, observed_at TEXT NOT NULL, symbol TEXT, timeframe TEXT,
  position_id TEXT, order_id TEXT, decision_id TEXT,
  PRIMARY KEY(source,kind,record_id));
CREATE INDEX IF NOT EXISTS research_ref_market ON research_refs(kind,symbol,timeframe,observed_at);
CREATE INDEX IF NOT EXISTS research_ref_known ON research_refs(kind,known_at);
CREATE INDEX IF NOT EXISTS research_ref_position ON research_refs(source,kind,position_id);
CREATE INDEX IF NOT EXISTS research_ref_order ON research_refs(source,kind,order_id);
CREATE INDEX IF NOT EXISTS research_ref_decision ON research_refs(source,kind,decision_id);
CREATE TABLE IF NOT EXISTS research_versions (
  source TEXT NOT NULL, kind TEXT NOT NULL, record_id TEXT NOT NULL,
  content_hash TEXT NOT NULL REFERENCES research_content(hash),
  collected_at TEXT NOT NULL, known_at TEXT, PRIMARY KEY(source,kind,record_id,content_hash));
CREATE TABLE IF NOT EXISTS research_links (
  source TEXT NOT NULL, signal_id TEXT NOT NULL, decision_id TEXT NOT NULL,
  PRIMARY KEY(source,signal_id,decision_id));
CREATE TABLE IF NOT EXISTS research_cursors (
  source TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY(source,kind));
CREATE TABLE IF NOT EXISTS research_errors (
  source TEXT NOT NULL, kind TEXT NOT NULL, record_id TEXT NOT NULL,
  content_hash TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(source,kind,record_id,content_hash));
CREATE TABLE IF NOT EXISTS research_tasks (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL, record_id TEXT NOT NULL,
  content_hash TEXT NOT NULL, symbol TEXT NOT NULL, observed_at TEXT NOT NULL,
  due_at TEXT NOT NULL, horizon INTEGER NOT NULL, next_attempt_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING');
CREATE INDEX IF NOT EXISTS research_tasks_due ON research_tasks(status,next_attempt_at,due_at);
CREATE INDEX IF NOT EXISTS research_tasks_input ON research_tasks(source,kind,record_id);
CREATE TABLE IF NOT EXISTS research_postmortems (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, evaluated_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS research_postmortem_task ON research_postmortems(task_id,evaluated_at);
CREATE TABLE IF NOT EXISTS research_holdouts (
  evaluation_start TEXT NOT NULL, evaluation_end TEXT NOT NULL, protocol TEXT NOT NULL,
  PRIMARY KEY(evaluation_start,evaluation_end));
CREATE TABLE IF NOT EXISTS research_forecasts (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, model_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_forecast_reviews (
  id TEXT PRIMARY KEY, forecast_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS research_forecast_review_id ON research_forecast_reviews(forecast_id);
"""


def migrate(store):
    store.db.execute("PRAGMA foreign_keys=ON")
    table = store.db.execute("SELECT 1 FROM sqlite_master WHERE name='consolidation_versions'").fetchone()
    if table and (store.db.execute("SELECT max(version) FROM consolidation_versions").fetchone()[0] or 0) > VERSION:
        raise ValueError("research_store_schema_newer_than_code")
    store.db.executescript("BEGIN IMMEDIATE;\n" + DDL + f"\nINSERT OR IGNORE INTO consolidation_versions(version) VALUES ({VERSION});\nCOMMIT;")
