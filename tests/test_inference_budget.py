import json
from pathlib import Path
import tempfile
import time
import unittest

from commentscope.providers.budget import InferenceBudget, BudgetExhausted

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
        for cycle,limit in [('new-cycle',60),('test',120),('test',30)]:
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


if __name__ == '__main__': unittest.main()
