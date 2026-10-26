import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY, session_hash TEXT NOT NULL,
                    challenge_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    answer TEXT NOT NULL, feedback TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS attempts_lookup
                ON attempts(session_hash, challenge_id, id);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def new_session(self):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?)', (self.key(token),))
        return token

    def exists(self, token):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM sessions WHERE token_hash=?', (self.key(token),)).fetchone() is not None

    def history(self, token, cid, limit=20):
        with self.connect() as db:
            rows = db.execute('''SELECT * FROM attempts WHERE session_hash=? AND challenge_id=?
                                 ORDER BY id DESC LIMIT ?''', (self.key(token), cid, limit)).fetchall()
        return [{'id': r['id'], 'created_at': r['created_at'],
                 'answer': json.loads(r['answer']), 'feedback': json.loads(r['feedback'])}
                for r in reversed(rows)]

    def save(self, token, cid, answer, feedback):
        with self.connect() as db:
            row = db.execute('''INSERT INTO attempts(session_hash,challenge_id,created_at,answer,feedback)
                                VALUES (?,?,?,?,?)''',
                             (self.key(token), cid, datetime.now(timezone.utc).isoformat(),
                              json.dumps(answer, ensure_ascii=False), json.dumps(feedback, ensure_ascii=False)))
            return row.lastrowid
