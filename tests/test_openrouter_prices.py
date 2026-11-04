"""Cache writes and all advertised context tiers belong in billing admission."""
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.providers import openrouter
from commentscope.providers.budget import BudgetExhausted
from commentscope.providers.openrouter_budget import PaidBudget, SpendLedger
from experiments import openrouter_factory_pipeline as executor
from test_openrouter import deployment
from test_openrouter_budget import authored_provider, PLAN


def prices():
    return {'prompt': '.000002', 'completion': '.00001', 'input_cache_read': '.0000001',
            'input_cache_write': '.0000025', 'overrides': [{'min_prompt_tokens': 272000,
                'prompt': '.000004', 'completion': '.000015', 'input_cache_write': '.000005'}]}


def configured():
    value = deployment(); value['context'] = 1000
    value['provider']['max_price'] = {'prompt': 2, 'completion': 10, 'request': 0}
    value['billing_ceiling'] = {'prompt': 5, 'completion': 15, 'request': 0}
    return value


class OpenRouterPriceTests(unittest.TestCase):
    def test_all_cache_classes_and_context_tiers_contribute_to_the_ceiling(self):
        self.assertEqual(openrouter.endpoint_price_ceiling(prices()),
                         {'prompt': Decimal(5), 'completion': Decimal(15), 'request': Decimal(0)})

    def test_cache_write_is_a_total_rate_not_added_twice(self):
        self.assertEqual(openrouter.endpoint_price_ceiling({'prompt': '.000001', 'completion': '.000002',
            'input_cache_write': '.00000125'})['prompt'], Decimal('1.25'))

    def test_malformed_or_nonfinite_prices_fail_before_admission(self):
        for field, value in [('prompt', '-1'), ('completion', 'NaN'), ('input_cache_write', 'Infinity'),
                             ('overrides', [None]), ('overrides', {})]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                openrouter.endpoint_price_ceiling({**prices(), field: value})

    def test_host_ceiling_must_be_complete_finite_and_cannot_lower_routing_caps(self):
        for value in [{'prompt': 5}, {'prompt': True, 'completion': 15, 'request': 0},
                      {'prompt': 1, 'completion': 15, 'request': 0},
                      {'prompt': 5, 'completion': float('inf'), 'request': 0}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                openrouter.validate({**configured(), 'billing_ceiling': value})

    def test_preflight_requires_the_declared_ceiling_to_cover_cache_and_long_tiers(self):
        value = configured()
        endpoint = {'tag': value['provider']['only'][0], 'status': 0, 'provider_name': 'Authored',
                    'context_length': 1000, 'supported_parameters': list(openrouter.required_parameters(value)),
                    'pricing': prices()}
        def check(d, e=endpoint):
            with patch.object(executor, 'build_opener') as opener:
                opener.return_value.open.return_value = BytesIO(json.dumps({'data': {'endpoints': [e]}}).encode())
                return executor.provider_preflight(d)
        legacy = deepcopy(value); legacy.pop('billing_ceiling')
        with self.assertRaises(ValueError): check(legacy)
        self.assertEqual(check(value)['tag'], endpoint['tag'])
        with self.assertRaises(ValueError): check({**value, 'billing_ceiling': {'prompt': 4, 'completion': 15, 'request': 0}})
        expensive = deepcopy(endpoint); expensive['pricing']['prompt'] = '.000003'
        with self.assertRaises(ValueError): check(value, expensive)

    def test_cache_write_charge_is_covered_by_the_money_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SpendLedger(Path(tmp)/'spend.sqlite', 'authored', maximum_usd='.01')
            base = Mock(); base.call.return_value = {'usage': {'cost': .0055}}
            paid = PaidBudget(base, ledger, plan_sha256=PLAN, deployment=configured(), maximum_run_usd='.01',
                              paid_provider=authored_provider, key_metadata=lambda: {'limit_remaining': .01})
            req = {'system': 's', 'data': {}, 'schema': {}, 'max_tokens': 100}
            paid.call(req, PLAN, timeout_seconds=30, provider=authored_provider)
            self.assertEqual(ledger.summary()['confirmed_usd'], '0.0055')
            self.assertEqual(ledger.summary()['uncertain_calls'], 0)

    def test_insufficient_cache_write_budget_refuses_before_the_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SpendLedger(Path(tmp)/'spend.sqlite', 'authored', maximum_usd='.01')
            base = Mock()
            paid = PaidBudget(base, ledger, plan_sha256=PLAN, deployment=configured(), maximum_run_usd='.006',
                              paid_provider=authored_provider, key_metadata=lambda: {'limit_remaining': .01})
            with self.assertRaises(BudgetExhausted):
                paid.call({'system': 's', 'data': {}, 'schema': {}, 'max_tokens': 100}, PLAN,
                          timeout_seconds=30, provider=authored_provider)
            base.call.assert_not_called(); self.assertEqual(ledger.summary()['calls'], 0)

    def test_host_billing_ceiling_changes_plan_identity_without_changing_API_payload(self):
        current = configured(); legacy = deepcopy(current); legacy.pop('billing_ceiling')
        self.assertEqual(openrouter.Client(current).payload('s', {}, {}, 32),
                         openrouter.Client(legacy).payload('s', {}, {}, 32))
        self.assertNotEqual(openrouter.Client(current).deployment, openrouter.Client(legacy).deployment)


if __name__ == '__main__': unittest.main()
