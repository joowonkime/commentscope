"""No paid calls: reserve money before dispatch and retain uncertain charges."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from commentscope.providers.budget import BudgetExhausted, InferenceBudget
from commentscope.providers.openrouter_budget import SpendLedger, PaidBudget
from test_openrouter import deployment

PLAN = 'a'*64


def authored_provider(system, data, schema, max_tokens):
    return {'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
            'usage': {'cost': 0.0001}}


class SpendLedgerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/'money.sqlite'
        self.ledger = SpendLedger(self.path, 'authored-account', maximum_usd='1', opening_charge_usd='0.1')

    def reserve(self, *, plan=PLAN, amount='0.2', limit='0.5', remaining='0.9'):
        return self.ledger.reserve(plan, 'b'*64, amount, run_limit_usd=limit, key_remaining_usd=remaining)

    def test_actual_charge_releases_unused_reservation(self):
        call = self.reserve(); self.ledger.finish(call, '0.012345678901')
        self.assertEqual(self.ledger.summary()['charged_usd'], '0.112345678901')
        self.assertEqual(self.ledger.summary()['reserved_calls'], 0)
        self.reserve(amount='0.4')

    def test_plan_summary_excludes_opening_balance_and_other_runs(self):
        call = self.reserve(); self.ledger.finish(call, '0.01')
        other = self.reserve(plan='c'*64); self.ledger.finish(other, '0.02')
        own = self.ledger.summary(plan_sha256=PLAN)
        self.assertEqual(own['charged_usd'], '0.01'); self.assertEqual(own['calls'], 1)
        self.assertEqual(self.ledger.summary()['charged_usd'], '0.13')

    def test_finite_total_budget_refuses_before_a_call(self):
        with self.assertRaises(BudgetExhausted): self.reserve(amount='0.91', limit='1')
        self.assertEqual(self.ledger.summary()['calls'], 0)

    def test_run_budget_is_enforced_across_reopened_connections(self):
        call = self.reserve(); self.ledger.finish(call, '0.19')
        other = SpendLedger(self.path, 'authored-account', maximum_usd='1', opening_charge_usd='0.1')
        with self.assertRaises(BudgetExhausted):
            other.reserve(PLAN, 'c'*64, '0.32', run_limit_usd='0.5', key_remaining_usd='0.9')
        self.assertEqual(other.summary()['calls'], 1)

    def test_remote_key_remaining_is_checked_before_reservation(self):
        with self.assertRaises(BudgetExhausted): self.reserve(remaining='0.19')
        self.assertEqual(self.ledger.summary()['calls'], 0)

    def test_remaining_fraction_is_never_rounded_up_to_authorize_spending(self):
        with self.assertRaises(BudgetExhausted): self.reserve(remaining='0.1999999999999')

    def test_tiny_actual_charge_is_conservatively_rounded_up(self):
        call = self.reserve(); self.ledger.finish(call, '0.0000000000001')
        self.assertEqual(self.ledger.summary()['charged_usd'], '0.100000000001')

    def test_settlement_cannot_be_applied_twice(self):
        call = self.reserve(); self.ledger.finish(call, '0.01')
        with self.assertRaises(ValueError): self.ledger.finish(call, '0')
        self.assertEqual(self.ledger.summary()['charged_usd'], '0.11')

    def test_other_process_cannot_ignore_an_active_reservation(self):
        self.reserve()
        other = SpendLedger(self.path, 'authored-account', maximum_usd='1', opening_charge_usd='0.1')
        with self.assertRaises(BudgetExhausted):
            other.reserve('c'*64, 'd'*64, '0.1', run_limit_usd='0.5', key_remaining_usd='0.9')

    def test_uncertain_charge_keeps_reservation_and_holds_new_calls(self):
        call = self.reserve(); self.ledger.finish(call, None)
        self.assertEqual(self.ledger.summary()['charged_usd'], '0.3')
        self.assertEqual(self.ledger.summary()['uncertain_calls'], 1)
        with self.assertRaises(BudgetExhausted): self.reserve(plan='c'*64)

    def test_over_ceiling_charge_is_retained_and_holds_new_calls(self):
        call = self.reserve()
        with self.assertRaises(BudgetExhausted): self.ledger.finish(call, '0.21')
        self.assertEqual(self.ledger.summary()['charged_usd'], '0.31')
        with self.assertRaises(BudgetExhausted): self.reserve()

    def test_existing_account_and_run_limits_cannot_be_increased_on_resume(self):
        with self.assertRaises(ValueError):
            SpendLedger(self.path, 'authored-account', maximum_usd='2', opening_charge_usd='0.1')
        call = self.reserve(); self.ledger.finish(call, '0.01')
        with self.assertRaises(ValueError): self.reserve(limit='0.6')

    def test_invalid_money_is_rejected_without_reserving(self):
        for amount in ('NaN', 'Infinity', '-1', True):
            with self.subTest(amount=amount), self.assertRaises(ValueError): self.reserve(amount=amount)
        self.assertEqual(self.ledger.summary()['calls'], 0)


class PaidBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.ledger = SpendLedger(Path(temporary.name)/'money.sqlite', 'test', maximum_usd='1')
        self.base = Mock(); self.provider = Mock(); self.metadata = Mock(return_value={'limit_remaining': 1})
        self.base.call.return_value = {'usage': {'cost': 0.0001}}
        self.budget = PaidBudget(self.base, self.ledger, plan_sha256=PLAN, deployment=deployment(),
                                maximum_run_usd='0.1', paid_provider=self.provider, key_metadata=self.metadata)
        self.request = {'system': 's', 'data': {}, 'schema': {}, 'max_tokens': 100}

    def call(self):
        return self.budget.call(self.request, PLAN, timeout_seconds=30, provider=self.provider)

    def test_cost_is_reserved_before_dispatch_and_settled_from_first_response(self):
        def response(*args, **kwargs):
            self.assertEqual(self.ledger.summary()['reserved_calls'], 1)
            return {'usage': {'cost': 0.0001}}
        self.base.call.side_effect = response
        self.assertEqual(self.call()['usage']['cost'], 0.0001)
        self.assertEqual(self.ledger.summary()['charged_usd'], '0.0001')

    def test_missing_cost_preserves_reservation_and_prevents_a_second_dispatch(self):
        self.base.call.return_value = {'usage': {}}
        with self.assertRaises(BudgetExhausted): self.call()
        with self.assertRaises(BudgetExhausted): self.call()
        self.assertEqual(self.base.call.call_count, 1)

    def test_transport_interruption_is_not_refunded_or_retried(self):
        self.base.call.side_effect = TimeoutError('authored interruption')
        with self.assertRaises(TimeoutError): self.call()
        with self.assertRaises(BudgetExhausted): self.call()
        self.assertEqual(self.base.call.call_count, 1)

    def test_key_inspection_failure_prevents_dispatch_and_reservation(self):
        self.metadata.side_effect = OSError('authored metadata failure')
        with self.assertRaises(OSError): self.call()
        self.base.call.assert_not_called(); self.assertEqual(self.ledger.summary()['calls'], 0)

    def test_unknown_provider_cannot_bypass_money_accounting(self):
        with self.assertRaises(ValueError):
            self.budget.call(self.request, PLAN, timeout_seconds=30, provider=Mock())
        self.base.call.assert_not_called()

    def test_another_plan_cannot_use_this_spending_wrapper(self):
        with self.assertRaises(ValueError):
            self.budget.call(self.request, 'f'*64, timeout_seconds=30, provider=self.provider)
        self.base.call.assert_not_called(); self.metadata.assert_not_called()

    def test_explicit_local_provider_does_not_spend_api_money(self):
        local = Mock()
        budget = PaidBudget(self.base, self.ledger, plan_sha256=PLAN, deployment=deployment(),
                            maximum_run_usd='0.1', paid_provider=self.provider, key_metadata=self.metadata,
                            local_providers=(local,))
        budget.call(self.request, PLAN, timeout_seconds=30, provider=local)
        self.base.call.assert_called_once()
        self.metadata.assert_not_called(); self.assertEqual(self.ledger.summary()['calls'], 0)

    def test_real_bounded_worker_records_both_time_and_money(self):
        time_budget = InferenceBudget(self.ledger.path.parent/'time.sqlite', 'authored-integration', limit_seconds=30)
        budget = PaidBudget(time_budget, self.ledger, plan_sha256=PLAN, deployment=deployment(),
                            maximum_run_usd='0.1', paid_provider=authored_provider, key_metadata=self.metadata)
        result = budget.call(self.request, PLAN, timeout_seconds=15, provider=authored_provider)
        self.assertEqual(result['usage']['cost'], 0.0001)
        self.assertEqual(time_budget.summary()['calls'][0]['state'], 'ok')
        self.assertEqual(self.ledger.summary()['charged_usd'], '0.0001')


if __name__ == '__main__': unittest.main()
