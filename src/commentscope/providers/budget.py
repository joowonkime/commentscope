"""Persistent local-call budget. Unfinished calls retain their full reservation.

SQLite transactions protect the shared cycle allowance across processes. Each
model request runs in a disposable process with a wall-clock deadline. This is
call elapsed time, not a GPU utilization meter or an authenticity certificate.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import multiprocessing
from pathlib import Path
import sqlite3
import time

from commentscope.factory.automatic_contract import digest
from commentscope.providers.local_llama import generate

VERSION = 'local-inference-budget-0.1'
MAX_RESPONSE_BYTES = 2_000_000
SHUTDOWN_RESERVATION_SECONDS = 3


class BudgetExhausted(RuntimeError):
    pass


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def worker(pipe, provider, request):
    try:
        result = provider(request['system'], request['data'], request['schema'],
                          max_tokens=request['max_tokens'])
        if not isinstance(result, dict):
            raise ValueError('Expected response object')
        raw = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(raw.encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ValueError('Response size limit')
        pipe.send(('ok', raw))
    except BaseException as exc:
        # Exception messages may contain user data or credentials.
        pipe.send(('error', type(exc).__name__))
    finally:
        pipe.close()


class InferenceBudget:
    def __init__(self, path, cycle_id, *, limit_seconds=8*60*60):
        if not isinstance(cycle_id, str) or not cycle_id.strip() or not positive(limit_seconds):
            raise ValueError('Explicit cycle ID and positive finite budget required')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cycle_id, self.limit = cycle_id, float(limit_seconds)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), version TEXT, cycle TEXT, limit_seconds REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, plan_sha TEXT, request_sha TEXT, request_json TEXT, started_at TEXT, reserved REAL, charged REAL, elapsed REAL, state TEXT, response_json TEXT, error TEXT)')
            db.execute('INSERT OR IGNORE INTO policy VALUES (1,?,?,?)', (VERSION, cycle_id, self.limit))
            if db.execute('SELECT version,cycle,limit_seconds FROM policy WHERE id=1').fetchone() != (VERSION, cycle_id, self.limit):
                raise ValueError('Existing cycle policy cannot be replaced')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        finally:
            db.close()

    def reserve(self, request, plan_sha, timeout_seconds):
        if not positive(timeout_seconds) or not isinstance(plan_sha, str) or len(plan_sha) != 64 or any(c not in '0123456789abcdef' for c in plan_sha):
            raise ValueError('Invalid request deadline or plan identity')
        if set(request) != {'system','data','schema','max_tokens'}:
            raise ValueError('Unexpected request fields')
        encoded = json.dumps(request, ensure_ascii=False, allow_nan=False)
        reserve = timeout_seconds + SHUTDOWN_RESERVATION_SECONDS
        with self.transaction() as db:
            charged = db.execute('SELECT COALESCE(SUM(charged),0) FROM calls').fetchone()[0]
            if charged + reserve > self.limit:
                raise BudgetExhausted('Cycle inference budget cannot cover another bounded call')
            cursor = db.execute('INSERT INTO calls(plan_sha,request_sha,request_json,started_at,reserved,charged,state) VALUES (?,?,?,?,?,?,?)',
                (plan_sha, digest(request), encoded, datetime.now(timezone.utc).isoformat(), reserve, reserve, 'reserved'))
            return cursor.lastrowid

    def finish(self, call_id, elapsed, state, response=None, error=None):
        if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed < 0 or state not in {'ok','error','timeout','interrupted'}:
            raise ValueError('Invalid terminal call record')
        if (state == 'ok') != (response is not None) or (state != 'ok') != (error is not None):
            raise ValueError('Result state mismatch')
        encoded = None if response is None else json.dumps(response, ensure_ascii=False, allow_nan=False)
        with self.transaction() as db:
            row = db.execute('SELECT state,reserved FROM calls WHERE id=?', (call_id,)).fetchone()
            if row is None or row[0] != 'reserved':
                raise ValueError('Missing or already finished call')
            # Timeout/interruption charges remain conservative, including cleanup.
            charged = max(elapsed, row[1]) if state in {'timeout','interrupted'} else elapsed
            db.execute('UPDATE calls SET elapsed=?,charged=?,state=?,response_json=?,error=? WHERE id=?',
                       (elapsed, charged, state, encoded, error, call_id))

    def summary(self):
        with self.transaction() as db:
            rows = db.execute('SELECT id,plan_sha,request_sha,reserved,charged,elapsed,state,error FROM calls ORDER BY id').fetchall()
        calls = [dict(zip(['id','plan_sha256','request_sha256','reserved_seconds','charged_seconds','elapsed_seconds','state','error'], row)) for row in rows]
        charged = sum(c['charged_seconds'] for c in calls)
        return {'artifact_kind':VERSION,'cycle_id':self.cycle_id,'limit_seconds':self.limit,
                'charged_seconds':charged,'remaining_seconds':max(0,self.limit-charged),
                'unfinished_reservations':sum(c['state']=='reserved' for c in calls),'calls':calls}

    def call(self, request, plan_sha, *, timeout_seconds=180, provider=generate):
        call_id = self.reserve(request, plan_sha, timeout_seconds)
        started = time.monotonic()
        context = multiprocessing.get_context('spawn')
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=worker, args=(sender,provider,request), daemon=True)
        state, response, error = 'error', None, 'worker_start_failed'
        caught = None
        try:
            process.start()
            sender.close()
            remaining = max(0, timeout_seconds-(time.monotonic()-started))
            if not receiver.poll(remaining):
                state, error = 'timeout', 'wall_clock_deadline'
            else:
                state, value = receiver.recv()
                if state == 'ok':
                    response, error = json.loads(value), None
                else:
                    error = value
        except BaseException as exc:
            state = 'interrupted' if isinstance(exc, (KeyboardInterrupt,SystemExit)) else 'error'
            error, response, caught = type(exc).__name__, None, exc
        finally:
            sender.close(); receiver.close()
            if process.pid is not None:
                process.join(.1)
                if process.is_alive():
                    process.terminate(); process.join(1)
                if process.is_alive():
                    process.kill(); process.join(1)
                if process.is_alive():
                    state, response, error = 'interrupted', None, 'worker_did_not_exit'
            self.finish(call_id, time.monotonic()-started, state, response, error)
        if caught is not None:
            raise caught
        if state != 'ok':
            raise RuntimeError('Bounded local inference failed: '+str(error))
        return response

    def provider(self, plan_sha, *, timeout_seconds=180, implementation=generate):
        def bounded(system, data, schema, max_tokens=500):
            return self.call({'system':system,'data':data,'schema':schema,'max_tokens':max_tokens},
                             plan_sha, timeout_seconds=timeout_seconds, provider=implementation)
        return bounded
