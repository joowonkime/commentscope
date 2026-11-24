"""Stage checkpoints and spending guard for the single product worker."""
from decimal import Decimal, InvalidOperation

from commentscope.agents.web import WebError
from commentscope.factory.automatic_contract import digest
from commentscope.providers.budget import BudgetExhausted
from commentscope.product.store import decode, encode


class Interrupted(Exception):
    """The worker must publish the pause or close instead of proceeding."""


def amount(value):
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid cost') from None
    if not value.is_finite() or value < 0:
        raise ValueError('Invalid cost')
    return value


def room_at(db, rid):
    return decode(db.execute('SELECT data FROM rooms WHERE id=?', (rid,)).fetchone())


def check_active(room, job):
    if room['epoch'] != job['args']['epoch'] or room['state'] in ('closing', 'closed', 'pausing', 'paused'):
        raise Interrupted()


class Execution:
    def __init__(self, app, job, session, scope, limit):
        self.app, self.job, self.session = app, job, session
        self.rid = job['room_id']
        self.scope, self.limit = scope, limit

    def __call__(self, stage, payload):
        app = self.app
        key = digest([self.scope, stage])
        fingerprint = digest(payload)
        verification = stage.endswith('-verify')
        with app.store.transaction() as db:
            room = room_at(db, self.rid)
            check_active(room, self.job)
            app._internal_session(db, self.session['session_id'])
            app._analysis(self.session)
            stages = room.get('_stages', {})
            previous = stages.get(key)
            if previous:
                if previous['sha256'] != fingerprint:
                    raise ValueError('Debate checkpoint differs from the sealed request')
                return previous['response']
            if room.get('_call_count', 0) >= self.limit:
                raise WebError(409, 'call_limit')
            status = app.generation_status()
            if status != 'ready':
                raise WebError(409, status)
            verify_max = amount(app.decision_reservation())
            reserved = verify_max if verification else amount(app.reservation(payload)) + verify_max
            if amount(room['cost_usd']) + reserved > amount(room['maximum_cost_usd']):
                raise WebError(409, 'budget_exhausted')
            room['_call_count'] = room.get('_call_count', 0) + 1
            app._save_room(db, room)
        provider = app.decision if verification else app.model
        try:
            response = provider(stage, payload)
        except Exception as exc:
            known = getattr(exc, 'new_cost_usd', None)
            if known is not None:
                self.settle(key, fingerprint, known)
            raise
        charge = response.get('new_cost_usd', response.get('usage', {}).get('cost'))
        self.settle(key, fingerprint, charge, response)
        return response

    def settle(self, key, fingerprint, charge, response=None):
        try:
            charged = amount(charge)
        except ValueError:
            raise BudgetExhausted('Unknown room charge') from None
        with self.app.store.transaction() as db:
            room = room_at(db, self.rid)
            total = amount(room['cost_usd']) + charged
            room['cost_usd'] = str(total)
            if response is not None and room['state'] not in ('closing', 'closed'):
                room.setdefault('_stages', {})[key] = {'sha256': fingerprint, 'response': response}
            self.app._save_room(db, room)
        if total > amount(room['maximum_cost_usd']):
            raise BudgetExhausted('Settled charge exceeds local limit')

    def clear(self, room):
        room.pop('_stages', None)
