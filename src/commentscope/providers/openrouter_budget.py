"""Durable API money reservations, separate from the local time ledger.

Unknown charges retain their entire reservation and stop new paid requests.
Reopening/resuming cannot increase limits. An explicit audited credit revision
may raise the account ceiling without changing historical money or run caps.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from commentscope.providers.budget import BudgetExhausted
from commentscope.providers.openrouter import validate, billing_prices
from commentscope.factory.automatic_contract import digest

VERSION = 'openrouter-spend-ledger-0.1'
SCALE = Decimal(10)**12
MAX_UNITS = 2**63-1


def units(value, *, rounding=ROUND_CEILING):
    if type(value) not in (int, float, str, Decimal):
        raise ValueError('Finite nonnegative USD amount required')
    try: amount = Decimal(str(value))
    except InvalidOperation: raise ValueError('Invalid USD amount') from None
    if not amount.is_finite() or amount < 0 or amount > Decimal(MAX_UNITS)/SCALE:
        raise ValueError('Finite nonnegative USD amount required')
    return int((amount*SCALE).to_integral_value(rounding=rounding))


def dollars(value):
    text = format(Decimal(value)/SCALE, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def identity(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('SHA256 request and plan identities required')


class SpendLedger:
    def __init__(self, path, account_id, *, maximum_usd, opening_charge_usd=0):
        maximum, opening = units(maximum_usd, rounding=ROUND_FLOOR), units(opening_charge_usd)
        if not isinstance(account_id, str) or not account_id.strip() or maximum <= 0 or opening > maximum:
            raise ValueError('Explicit account and valid finite opening balance required')
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.maximum, self.opening, self.account_id = maximum, opening, account_id
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), version TEXT, account TEXT, maximum INTEGER, opening INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS plans (sha TEXT PRIMARY KEY, maximum INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, plan_sha TEXT, request_sha TEXT, reserved INTEGER, charged INTEGER, state TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS resolutions (call_id INTEGER PRIMARY KEY, evidence_sha TEXT, reason TEXT, resolved_at TEXT)')
            expected = (VERSION, account_id, maximum, opening)
            row = db.execute('SELECT version,account,maximum,opening FROM policy WHERE id=1').fetchone()
            if row is None: db.execute('INSERT INTO policy VALUES (1,?,?,?,?)', expected)
            elif row != expected: raise ValueError('Existing API account policy cannot be replaced')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction: db.execute('ROLLBACK')
            raise
        finally: db.close()

    def check_policy(self,db):
        actual=db.execute('SELECT version,account,maximum,opening FROM policy WHERE id=1').fetchone()
        if actual!=(VERSION,self.account_id,self.maximum,self.opening):
            raise ValueError('Stale API account policy; reopen with current audited limit')

    def increase_limit(self,*,maximum_usd,observed_key_limit_usd,authorization_sha256,user_request):
        """Explicit control-plane revision; never a resume or a money refund."""
        identity(authorization_sha256)
        maximum=units(maximum_usd,rounding=ROUND_FLOOR);observed=units(observed_key_limit_usd,rounding=ROUND_FLOOR)
        if not isinstance(user_request,str) or not user_request.strip() or maximum>observed:
            raise ValueError('User instruction and sufficient observed team credit required')
        with self.transaction() as db:
            self.check_policy(db)
            db.execute('CREATE TABLE IF NOT EXISTS limit_revisions (authorization_sha TEXT PRIMARY KEY, record TEXT NOT NULL)')
            previous=db.execute('SELECT record FROM limit_revisions WHERE authorization_sha=?',(authorization_sha256,)).fetchone()
            if previous is not None:
                record=json.loads(previous[0])
                if (record['new_maximum_usd']!=dollars(maximum) or self.maximum!=maximum
                        or record['observed_key_limit_usd']!=dollars(observed) or record['user_request']!=user_request):
                    raise ValueError('Credit revision authorization changed')
                return record
            if maximum<=self.maximum:raise ValueError('Explicit credit increase required')
            if db.execute("SELECT 1 FROM calls WHERE state NOT IN ('complete','conservative') LIMIT 1").fetchone():
                raise BudgetExhausted('Active or uncertain money must settle before credit revision')
            history={name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall() for name in ('plans','calls','resolutions')}
            charged=self.opening+db.execute('SELECT COALESCE(SUM(charged),0) FROM calls').fetchone()[0]
            record=dict(version='openrouter-account-credit-revision-20261112-v1',account_id=self.account_id,
                authorization_sha256=authorization_sha256,user_request=user_request,
                old_maximum_usd=dollars(self.maximum),new_maximum_usd=dollars(maximum),
                observed_key_limit_usd=dollars(observed),opening_charge_usd=dollars(self.opening),
                charged_usd_at_change=dollars(charged),history_sha256=digest(history),
                changed_at=datetime.now(timezone.utc).isoformat())
            db.execute('UPDATE policy SET maximum=? WHERE id=1',(maximum,))
            db.execute('INSERT INTO limit_revisions VALUES (?,?)',(authorization_sha256,json.dumps(record,sort_keys=True)))
        self.maximum=maximum
        return record

    def reserve(self, plan_sha, request_sha, maximum_cost_usd, *, run_limit_usd, key_remaining_usd):
        identity(plan_sha); identity(request_sha)
        reserve = units(maximum_cost_usd)
        limit = units(run_limit_usd, rounding=ROUND_FLOOR)
        remaining = units(key_remaining_usd, rounding=ROUND_FLOOR)
        if limit <= 0: raise ValueError('Positive run spending limit required')
        with self.transaction() as db:
            self.check_policy(db)
            row = db.execute('SELECT maximum FROM plans WHERE sha=?', (plan_sha,)).fetchone()
            if row is not None and row[0] != limit: raise ValueError('Frozen run spending limit changed')
            if row is None: db.execute('INSERT INTO plans VALUES (?,?)', (plan_sha, limit))
            if db.execute("SELECT 1 FROM calls WHERE state NOT IN ('complete','conservative') LIMIT 1").fetchone():
                raise BudgetExhausted('Active or uncertain API charge requires reconciliation')
            charged = self.opening + db.execute('SELECT COALESCE(SUM(charged),0) FROM calls').fetchone()[0]
            run_charged = db.execute('SELECT COALESCE(SUM(charged),0) FROM calls WHERE plan_sha=?', (plan_sha,)).fetchone()[0]
            if charged+reserve > self.maximum or run_charged+reserve > limit or reserve > remaining:
                raise BudgetExhausted('API account, run or remote key cannot cover this reservation')
            return db.execute("INSERT INTO calls(plan_sha,request_sha,reserved,charged,state) VALUES (?,?,?,?,'reserved')",
                              (plan_sha, request_sha, reserve, reserve)).lastrowid

    def finish(self, call_id, actual_cost_usd):
        actual = None if actual_cost_usd is None else units(actual_cost_usd)
        exceeded = False
        with self.transaction() as db:
            self.check_policy(db)
            row = db.execute('SELECT reserved,state FROM calls WHERE id=?', (call_id,)).fetchone()
            if row is None or row[1] != 'reserved': raise ValueError('Missing or already settled API reservation')
            exceeded = actual is not None and actual > row[0]
            state = 'unknown' if actual is None else 'over_ceiling' if exceeded else 'complete'
            db.execute('UPDATE calls SET charged=?,state=? WHERE id=?',
                       (row[0] if actual is None else actual, state, call_id))
        if exceeded: raise BudgetExhausted('Actual API charge exceeded its ceiling; evidence retained')

    def resolve_conservatively(self, call_id, *, plan_sha256, request_sha256, evidence_sha256, reason):
        """Explicit audited release of a hold; never refund its reserved money."""
        for value in (plan_sha256, request_sha256, evidence_sha256): identity(value)
        if not isinstance(reason, str) or not reason.strip(): raise ValueError('Explained audit evidence required')
        with self.transaction() as db:
            self.check_policy(db)
            row = db.execute('SELECT plan_sha,request_sha,reserved,charged,state FROM calls WHERE id=?', (call_id,)).fetchone()
            if row is None or row[:2] != (plan_sha256, request_sha256) or row[4] != 'unknown':
                raise ValueError('Only the exact terminal unknown charge may be resolved')
            db.execute("UPDATE calls SET charged=?,state='conservative' WHERE id=?", (max(row[2], row[3]), call_id))
            db.execute('INSERT INTO resolutions VALUES (?,?,?,?)',
                       (call_id, evidence_sha256, reason, datetime.now(timezone.utc).isoformat()))

    def summary(self, *, plan_sha256=None):
        if plan_sha256 is not None: identity(plan_sha256)
        with self.transaction() as db:
            self.check_policy(db)
            clause, args = ('', ()) if plan_sha256 is None else (' WHERE plan_sha=?', (plan_sha256,))
            opening = self.opening if plan_sha256 is None else 0
            row = None if plan_sha256 is None else db.execute('SELECT maximum FROM plans WHERE sha=?', (plan_sha256,)).fetchone()
            maximum = self.maximum if plan_sha256 is None else row[0] if row else 0
            charged = opening + db.execute('SELECT COALESCE(SUM(charged),0) FROM calls'+clause, args).fetchone()[0]
            counts = dict(db.execute('SELECT state,count(*) FROM calls'+clause+' GROUP BY state', args).fetchall())
            suffix = '' if plan_sha256 is None else ' AND plan_sha=?'
            confirmed = opening + db.execute("SELECT COALESCE(SUM(charged),0) FROM calls WHERE state IN ('complete','over_ceiling')"+suffix, args).fetchone()[0]
            conservative = db.execute("SELECT COALESCE(SUM(charged),0) FROM calls WHERE state='conservative'"+suffix, args).fetchone()[0]
        return {'maximum_usd': dollars(maximum), 'charged_usd': dollars(charged),
                'confirmed_usd': dollars(confirmed), 'conservative_usd': dollars(conservative),
                'conservative_calls': counts.get('conservative', 0),
                'remaining_usd': dollars(max(0, maximum-charged)), 'calls': sum(counts.values()),
                'reserved_calls': counts.get('reserved', 0),
                'uncertain_calls': counts.get('unknown', 0)+counts.get('over_ceiling', 0)}


class PaidBudget:
    """Adapt InferenceBudget while keeping explicitly local calls separate."""
    def __init__(self, base, ledger, *, plan_sha256, deployment, maximum_run_usd,
                 paid_provider, key_metadata, local_providers=(), spend_scope_sha256=None):
        identity(plan_sha256)
        if spend_scope_sha256 is not None: identity(spend_scope_sha256)
        self.deployment = validate(deployment)
        self.prices = billing_prices(self.deployment)
        if not self.prices or not self.deployment['provider'].get('only') or units(maximum_run_usd) <= 0:
            raise ValueError('Frozen provider, price ceilings and positive run limit required')
        self.base, self.ledger = base, ledger
        self.plan_sha, self.run_limit = plan_sha256, maximum_run_usd
        # Several frozen execution plans can share one explicitly frozen money
        # owner. Request/time/checkpoint provenance still uses the actual plan.
        self.spend_scope = plan_sha256 if spend_scope_sha256 is None else spend_scope_sha256
        self.paid_provider, self.metadata = paid_provider, key_metadata
        self.local_providers = tuple(local_providers)

    def maximum_charge(self, request):
        p = {k: Decimal(str(v)) for k, v in self.prices.items()}
        return (self.deployment['context']*p['prompt'] + request['max_tokens']*p['completion'])/1_000_000 + p['request']

    def call(self, request, plan_sha, *, timeout_seconds, provider):
        if plan_sha != self.plan_sha: raise ValueError('API spending belongs to a different plan')
        if provider in self.local_providers:
            return self.base.call(request, plan_sha, timeout_seconds=timeout_seconds, provider=provider)
        if provider != self.paid_provider: raise ValueError('Unknown provider cannot bypass API accounting')
        if (set(request) != {'system', 'data', 'schema', 'max_tokens'}
                or type(request['max_tokens']) is not int
                or not 0 < request['max_tokens'] < self.deployment['context']):
            raise ValueError('Complete bounded API request required')
        json.dumps(request, allow_nan=False)
        maximum = self.maximum_charge(request)
        metadata = self.metadata()
        call_id = self.ledger.reserve(self.spend_scope, digest(request), maximum, run_limit_usd=self.run_limit,
                                      key_remaining_usd=metadata['limit_remaining'])
        try:
            response = self.base.call(request, plan_sha, timeout_seconds=timeout_seconds, provider=provider)
        except BaseException:
            self.ledger.finish(call_id, None)
            raise
        try:
            cost = response['usage']['cost']; units(cost)
        except (KeyError, TypeError, ValueError):
            self.ledger.finish(call_id, None)
            raise BudgetExhausted('Missing or invalid API charge; reconcile before further inference') from None
        self.ledger.finish(call_id, cost)
        return response
