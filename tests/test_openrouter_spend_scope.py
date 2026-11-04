"""A user cycle cap spans frozen plans without losing request provenance."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from commentscope.providers.budget import BudgetExhausted
from commentscope.providers.openrouter_budget import PaidBudget, SpendLedger
from test_openrouter import deployment


class SharedSpendScopeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ledger = SpendLedger(Path(temp.name)/'money.sqlite', 'synthetic', maximum_usd='50')
        self.provider = Mock()
        self.base = Mock()
        self.base.call.return_value = {'usage': {'cost': 0.0005}}
        self.req = {'system': '', 'data': {}, 'schema': {}, 'max_tokens': 10}
        self.scope = 'a'*64

    def budget(self, plan, limit='0.001', scope=None):
        return PaidBudget(self.base, self.ledger, plan_sha256=plan, deployment=deployment(),
                          maximum_run_usd=limit, paid_provider=self.provider,
                          key_metadata=lambda: {'limit_remaining': 50},
                          spend_scope_sha256=scope)

    def test_two_plans_share_one_cap_and_keep_actual_execution_plan(self):
        first = self.budget('1'*64, scope=self.scope)
        first.call(self.req, '1'*64, timeout_seconds=1, provider=self.provider)
        self.assertEqual(self.base.call.call_args.args[1], '1'*64)
        second = self.budget('2'*64, scope=self.scope)
        with self.assertRaises(BudgetExhausted):
            second.call(self.req, '2'*64, timeout_seconds=1, provider=self.provider)
        self.assertEqual(self.base.call.call_count, 1)
        self.assertEqual(self.ledger.summary(plan_sha256=self.scope)['charged_usd'], '0.0005')

    def test_scope_limit_cannot_be_increased_by_next_plan(self):
        first = self.budget('1'*64, scope=self.scope)
        first.call(self.req, '1'*64, timeout_seconds=1, provider=self.provider)
        second = self.budget('2'*64, limit='0.1', scope=self.scope)
        with self.assertRaisesRegex(ValueError, 'Frozen run spending limit changed'):
            second.call(self.req, '2'*64, timeout_seconds=1, provider=self.provider)
        self.assertEqual(self.base.call.call_count, 1)

    def test_default_scope_is_actual_plan_and_wrong_plan_stays_rejected(self):
        budget = self.budget('1'*64)
        with self.assertRaisesRegex(ValueError, 'different plan'):
            budget.call(self.req, '2'*64, timeout_seconds=1, provider=self.provider)
        budget.call(self.req, '1'*64, timeout_seconds=1, provider=self.provider)
        self.assertEqual(self.ledger.summary(plan_sha256='1'*64)['calls'], 1)
        with self.assertRaises(ValueError): self.budget('2'*64, scope='unbound')

    def test_unknown_charge_in_one_plan_blocks_the_next(self):
        self.base.call.return_value = {'usage': {}}
        with self.assertRaises(BudgetExhausted):
            self.budget('1'*64, scope=self.scope).call(
                self.req, '1'*64, timeout_seconds=1, provider=self.provider)
        with self.assertRaises(BudgetExhausted):
            self.budget('2'*64, scope=self.scope).call(
                self.req, '2'*64, timeout_seconds=1, provider=self.provider)
        self.assertEqual(self.base.call.call_count, 1)


if __name__ == '__main__': unittest.main()
