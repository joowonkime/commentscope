"""Durable product state, separate from the shared inference money ledger."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def decode(row):
    return json.loads(row['data'])


class Store:
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            statements = [
                'CREATE TABLE IF NOT EXISTS version (id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER)',
                'CREATE TABLE IF NOT EXISTS app_sessions (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, data TEXT NOT NULL)',
                '''CREATE TABLE IF NOT EXISTS opinions (session_id TEXT REFERENCES app_sessions(id), kind TEXT,
                   revision INTEGER, data TEXT NOT NULL, PRIMARY KEY(session_id,kind,revision))''',
                'CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, session_id TEXT REFERENCES app_sessions(id), data TEXT NOT NULL)',
                '''CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, room_id TEXT REFERENCES rooms(id),
                   seq INTEGER NOT NULL, data TEXT NOT NULL, UNIQUE(room_id,seq))''',
                '''CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, session_id TEXT REFERENCES app_sessions(id),
                   operation TEXT, state TEXT, data TEXT NOT NULL)''',
                '''CREATE TABLE IF NOT EXISTS requests (session_id TEXT REFERENCES app_sessions(id), operation TEXT,
                   request_id TEXT, body_sha TEXT NOT NULL, status INTEGER, data TEXT NOT NULL,
                   PRIMARY KEY(session_id,operation,request_id))''',
                '''CREATE TABLE IF NOT EXISTS reflections (id TEXT, session_id TEXT REFERENCES app_sessions(id),
                   revision INTEGER, data TEXT NOT NULL, PRIMARY KEY(id,revision))''']
            for statement in statements: db.execute(statement)
            db.execute('INSERT OR IGNORE INTO version VALUES(1,1)')
            if db.execute('SELECT schema_version FROM version WHERE id=1').fetchone()[0] != 1:
                raise ValueError('Unsupported product database version')
            for row in db.execute("SELECT * FROM jobs WHERE state IN ('queued','running')").fetchall():
                value = decode(row)
                value['state'] = 'needs_reconciliation' if row['state']=='running' else 'cancelled'
                value['error'] = {'code': 'process_restarted', 'retryable': False}
                db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', (value['state'],encode(value),row['id']))
                rid = value.get('room_id')
                if rid:
                    room = db.execute('SELECT data FROM rooms WHERE id=?',(rid,)).fetchone()
                    if room:
                        item = decode(room); item['state'] = value['state']; item['revision'] += 1
                        db.execute('UPDATE rooms SET data=? WHERE id=?',(encode(item),rid))

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction: db.execute('ROLLBACK')
            raise
        finally: db.close()
