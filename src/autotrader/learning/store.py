"""Incremental research-only state and content-addressed JSON models.

Nothing in this database is a financial posting or primary execution authority.
SQLite transactions and a process lock support restart and duplicate invocation.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from autotrader.research.data import canonical, digest


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root/'research.sqlite', timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS observations (
          id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, payload TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'PENDING', result TEXT, prediction TEXT);
        CREATE INDEX IF NOT EXISTS pending ON observations(status,observed_at);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS realized (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(observations)')}
        if 'next_attempt_at' not in columns:
            self.db.execute('ALTER TABLE observations ADD COLUMN next_attempt_at TEXT')
        self.db.commit()

    def get(self, key: str, default: Any = None) -> Any:
        r = self.db.execute('SELECT payload FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, key: str, value: Any) -> None:
        self.db.execute('INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload', (key, canonical(value).decode()))

    def insert(self, event: dict[str, Any], prediction: dict[str, Any] | None = None) -> None:
        self.db.execute('INSERT OR IGNORE INTO observations(id,observed_at,payload,prediction) VALUES (?,?,?,?)',
            (event['id'], event['observed_at'], canonical(event).decode(), canonical(prediction).decode() if prediction else None))

    def finish(self, identity: str, status: str, result: dict[str, Any]) -> None:
        self.db.execute('UPDATE observations SET status=?,result=? WHERE id=? AND status=?',
                        (status, canonical(result).decode(), identity, 'PENDING'))

    def artifact(self, value: dict[str, Any]) -> str:
        identity = digest(canonical(value))
        path = self.root/'artifacts'/(identity+'.json');path.parent.mkdir(exist_ok=True)
        data = canonical(value)
        try:
            with path.open('xb') as f:
                f.write(data);f.flush()
                import os
                os.fsync(f.fileno())
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError('immutable_artifact_conflict')
        self.db.execute('INSERT OR IGNORE INTO runs VALUES (?,?)', (identity, data.decode()))
        return identity

    def read_artifact(self, identity: str) -> dict[str, Any]:
        import re
        if not re.fullmatch('[a-f0-9]{64}', identity):
            raise ValueError('invalid_model_identity')
        data = (self.root/'artifacts'/(identity+'.json')).read_bytes()
        if digest(data) != identity:
            raise ValueError('model_artifact_integrity_failed')
        result: dict[str, Any] = json.loads(data)
        return result

    def close(self) -> None:
        self.db.close()
