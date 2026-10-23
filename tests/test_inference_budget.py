import json
import math
from pathlib import Path
import tempfile
import time
import unittest

from commentscope.providers.budget import InferenceBudget, BudgetExhausted, remaining_allowance, LEGACY_VERSION

REQUEST = {'system':'synthetic','data':{},'schema':{},'max_tokens':10}
PLAN = 'a'*64


def respond(system, data, schema, max_tokens):
    return {'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}


def fail(system, data, schema, max_tokens):
    raise OSError('private value must not appear in the error log')


def stall(system, data, schema, max_tokens):
    time.sleep(10)


class InferenceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'budget.sqlite'
        self.budget = InferenceBudget(self.path,'test',limit_seconds=60)

    def test_success_persists_and_reopens(self):
        result = self.budget.call(REQUEST,PLAN,timeout_seconds=10,provider=respond)
        self.assertIn('choices',result)
        summary = InferenceBudget(self.path,'test',limit_seconds=60).summary()
        self.assertEqual(summary['calls'][0]['state'],'ok')
        self.assertGreater(summary['charged_seconds'],0)
        self.assertEqual(summary['unfinished_reservations'],0)

    def test_error_is_charged_without_exception_message(self):
        with self.assertRaises(RuntimeError):
            self.budget.call(REQUEST,PLAN,timeout_seconds=10,provider=fail)
        summary = self.budget.summary()
        self.assertEqual(summary['calls'][0]['state'],'error')
        self.assertGreater(summary['charged_seconds'],0)
        self.assertNotIn('private value',json.dumps(summary))

    def test_hard_deadline_terminates_worker(self):
        start = time.monotonic()
        with self.assertRaises(RuntimeError):
            self.budget.call(REQUEST,PLAN,timeout_seconds=.2,provider=stall)
        self.assertLess(time.monotonic()-start,5)
        summary = self.budget.summary()
        self.assertEqual(summary['calls'][0]['state'],'timeout')
        self.assertGreaterEqual(summary['charged_seconds'],3.2)

    def test_unfinished_reservation_survives_restart(self):
        self.budget.reserve(REQUEST,PLAN,40)
        reopened = InferenceBudget(self.path,'test',limit_seconds=60)
        self.assertEqual(reopened.summary()['charged_seconds'],43)
        with self.assertRaises(BudgetExhausted): reopened.reserve(REQUEST,PLAN,15)

    def test_cycle_cannot_reset_or_change_limit(self):
        for cycle,limit in [('new-cycle',60),('test',120),('test',30),('test',None)]:
            with self.assertRaises(ValueError): InferenceBudget(self.path,cycle,limit_seconds=limit)
        self.assertEqual(self.budget.summary()['limit_seconds'],60)

    def test_no_double_finish_or_negative_refund(self):
        cid = self.budget.reserve(REQUEST,PLAN,10)
        with self.assertRaises(ValueError): self.budget.finish(cid,-1,'ok',{})
        self.budget.finish(cid,2,'ok',{})
        with self.assertRaises(ValueError): self.budget.finish(cid,0,'ok',{})
        self.assertEqual(self.budget.summary()['charged_seconds'],2)

    def test_invalid_limits_and_identity_rejected(self):
        for limit in [True,0,-1,float('inf'),float('nan')]:
            with self.assertRaises(ValueError): self.budget.reserve(REQUEST,PLAN,limit)
        with self.assertRaises(ValueError): self.budget.reserve(REQUEST,'bad',1)
        with self.assertRaises(ValueError): self.budget.reserve({**REQUEST,'expected':'supported'},PLAN,1)

    def test_interrupted_call_keeps_full_charge(self):
        cid = self.budget.reserve(REQUEST,PLAN,10)
        self.budget.finish(cid,1,'interrupted',error='KeyboardInterrupt')
        self.assertEqual(self.budget.summary()['charged_seconds'],13)

    def test_uncapped_cycle_records_more_than_eight_hours_and_reopens(self):
        path = Path(self.tmp.name)/'uncapped.sqlite'
        budget = InferenceBudget(path, 'uncapped', limit_seconds=None)
        cid = budget.reserve(REQUEST, PLAN, 10)
        budget.finish(cid, 28801, 'ok', {})
        reopened = InferenceBudget(path, 'uncapped')
        reopened.reserve(REQUEST, PLAN, 10)
        summary = reopened.summary()
        self.assertIsNone(summary['limit_seconds'])
        self.assertIsNone(summary['remaining_seconds'])
        self.assertEqual(summary['charged_seconds'], 28814)
        self.assertEqual(summary['unfinished_reservations'], 1)
        self.assertEqual(len(summary['calls']), 2)
        json.dumps(summary, allow_nan=False)
        self.assertTrue(math.isinf(remaining_allowance(summary)))
        with self.assertRaises(ValueError):
            InferenceBudget(path, 'uncapped', limit_seconds=28800)

    def test_uncapped_cycle_still_terminates_timed_out_worker(self):
        budget = InferenceBudget(Path(self.tmp.name)/'uncapped.sqlite', 'uncapped', limit_seconds=None)
        with self.assertRaises(RuntimeError):
            budget.call(REQUEST, PLAN, timeout_seconds=.2, provider=stall)
        summary = budget.summary()
        self.assertEqual(summary['calls'][0]['state'], 'timeout')
        self.assertGreaterEqual(summary['charged_seconds'], 3.2)
        self.assertEqual(summary['unfinished_reservations'], 0)

    def test_uncapped_cycle_still_requires_finite_call_timeout(self):
        budget = InferenceBudget(Path(self.tmp.name)/'uncapped.sqlite', 'uncapped', limit_seconds=None)
        for timeout in (None, True, 0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError): budget.reserve(REQUEST, PLAN, timeout)
        self.assertEqual(budget.summary()['calls'], [])

    def test_legacy_policy_reopens_without_being_rewritten(self):
        with self.budget.transaction() as db:
            db.execute('UPDATE policy SET version=? WHERE id=1', (LEGACY_VERSION,))
        reopened = InferenceBudget(self.path, 'test')
        self.assertEqual(reopened.summary()['artifact_kind'], LEGACY_VERSION)
        self.assertEqual(reopened.summary()['limit_seconds'], 60)
        with self.assertRaises(BudgetExhausted): reopened.reserve(REQUEST, PLAN, 60)
        with self.assertRaises(ValueError): InferenceBudget(self.path, 'test', limit_seconds=None)

    def test_allowance_rejects_ambiguous_or_invalid_summary(self):
        for summary in ({'remaining_seconds': None}, {'remaining_seconds': None, 'limit_seconds': 60},
                        {'remaining_seconds': math.inf}, {'remaining_seconds': -1}, {'remaining_seconds': True}):
            with self.assertRaises(ValueError): remaining_allowance(summary)
        self.assertEqual(remaining_allowance({'remaining_seconds': 0}), 0)
        self.assertEqual(remaining_allowance({'remaining_seconds': 60}), 60)

    def test_invalid_cycle_limits_are_rejected(self):
        for limit in (True, 0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                InferenceBudget(Path(self.tmp.name)/'invalid.sqlite', 'invalid', limit_seconds=limit)


if __name__ == '__main__': unittest.main()
