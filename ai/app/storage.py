"""작성: rootkit · 2026-10-23. SQLite snapshots and atomic activation/idempotency."""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Storage:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or os.environ.get("AI_DB_PATH", "data/rootkit.sqlite3"))
        if self.path == ":memory:":
            raise ValueError("Use a temporary SQLite file; service connections require durable storage")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT NOT NULL, version INTEGER NOT NULL,
                    documents TEXT NOT NULL, knowledge TEXT NOT NULL DEFAULT '{}',
                    term_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(dataset_id, version)
                );
                CREATE TABLE IF NOT EXISTS catalogs (
                    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL,
                    status TEXT NOT NULL, snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    FOREIGN KEY(dataset_id,dataset_version) REFERENCES datasets(dataset_id,version)
                );
                CREATE TABLE IF NOT EXISTS active_catalog (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), catalog_id TEXT NOT NULL REFERENCES catalogs(id)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS attempts_owner ON attempts(user_id, created_at);
                CREATE TABLE IF NOT EXISTS submissions (
                    attempt_id TEXT NOT NULL REFERENCES attempts(id), request_id TEXT NOT NULL,
                    answer TEXT NOT NULL, result TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(attempt_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS evaluation_requests (
                    attempt_id TEXT NOT NULL REFERENCES attempts(id), request_id TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(attempt_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT NOT NULL,
                    target TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
            """)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=240, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=240000")
        return conn

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def event(self, operation: str, target: str, status: str, detail):
        with self.transaction() as conn:
            conn.execute("INSERT INTO events(operation,target,status,detail) VALUES(?,?,?,?)",
                         (operation, target, status, dump(detail)))
