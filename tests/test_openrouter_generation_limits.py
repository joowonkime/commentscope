"""Reasoning headroom is bounded, measured, checkpointed and charged once."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from commentscope.agents.runtime import request
from commentscope.factory.automatic_contract import digest
from commentscope.providers import openrouter
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.providers.generation_limits import allocate
from commentscope.providers.openrouter_budget import PaidBudget, SpendLedger
from commentscope.storage import write_json_exclusive as write
from test_openrouter_schema import configured, receipt


def deployment():
    return {**configured(), 'context': 32768, 'temperature': None,
            'reasoning': {'effort': 'low'}, 'reasoning_output_tokens': 1024}


def logical():
    return {'system': 'Authored bounded comparison', 'data': {'text': '원문'},
            'schema': {'type': 'object', 'properties': {'same': {'type': 'boolean'}},
                       'required': ['same'], 'additionalProperties': False}, 'max_tokens': 128}


class OpenRouterGenerationTests(unittest.TestCase):
    def test_capacity_measures_the_exact_allocated_wire_request(self):
        client = openrouter.Client(deployment()); req = logical(); original = deepcopy(req)
        runtime = openrouter.generation_allocation(client.deployment, require_explicit=True)
        actual = allocate(req, runtime); measured = client.measure(req)
        self.assertEqual(actual['max_tokens'], 1152)
        self.assertEqual(measured['answer_tokens'], 128)
        self.assertEqual(measured['reasoning_output_tokens'], 1024)
        self.assertEqual(measured['output_reservation'], actual['max_tokens'])
        self.assertEqual(measured['request_sha256'], digest(req))
        self.assertEqual(measured['allocated_request_sha256'], digest(actual))
        wire = client.payload(actual['system'], actual['data'], actual['schema'], actual['max_tokens'])
        self.assertEqual(measured['input_upper_bound_tokens'],
                         len(json.dumps(wire, ensure_ascii=False, allow_nan=False).encode('utf-8')))
        self.assertNotIn('reasoning_output_tokens', wire)
        self.assertEqual(wire['reasoning'], {'effort': 'low'})
        self.assertEqual(req, original)

    def test_explicit_active_reasoning_requires_bounded_headroom_for_new_runs(self):
        value = deployment(); value.pop('reasoning_output_tokens')
        with self.assertRaisesRegex(ValueError, 'headroom'):
            openrouter.generation_allocation(value, require_explicit=True)
        # Old direct clients keep their original total-output payload semantics.
        self.assertEqual(openrouter.Client(value).payload('s', {}, logical()['schema'], 128)['max_tokens'], 128)

    def test_headroom_cannot_be_unbounded_or_added_to_disabled_or_implicit_reasoning(self):
        for tokens in (True, -1, 0, 2049, 1.5, '1024', None):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                openrouter.validate({**deployment(), 'reasoning_output_tokens': tokens})
        for reasoning in (None, {'enabled': False}, {'effort': 'none'}):
            with self.subTest(reasoning=reasoning), self.assertRaises(ValueError):
                openrouter.validate({**deployment(), 'reasoning': reasoning})

    def test_disabled_reasoning_preserves_the_answer_limit(self):
        for reasoning in ({'enabled': False}, {'effort': 'none'}):
            value = {**deployment(), 'reasoning': reasoning, 'reasoning_output_tokens': 0}
            self.assertEqual(allocate(logical(), openrouter.generation_allocation(value)), logical())

    def test_headroom_is_included_in_context_refusal(self):
        req = logical(); req['data'] = {'text': 'x'*2000}
        legacy = deployment(); legacy.pop('reasoning_output_tokens')
        old = openrouter.Client(legacy).measure(req)
        context = old['input_upper_bound_tokens'] + old['provider_margin'] + 128 + 512
        self.assertTrue(openrouter.Client({**legacy, 'context': context}).measure(req)['fits'])
        self.assertFalse(openrouter.Client({**deployment(), 'context': context}).measure(req)['fits'])

    def test_truncated_empty_and_partial_json_preserve_finish_usage_and_raw_receipt(self):
        client = openrouter.Client(configured())
        for content in (None, '', '{"same":', '{"same":true}'):
            with self.subTest(content=content):
                raw = receipt(None, finish='length'); raw['choices'][0]['message']['content'] = content
                original = deepcopy(raw)
                result = request('s', {}, logical()['schema'],
                                 lambda *args: client.decode_response(logical(), raw))
                self.assertIn('incomplete_generation', result['errors'])
                self.assertIsNone(result['output'])
                self.assertEqual(result['raw'], content)
                self.assertEqual(result['usage'], raw['usage'])
                self.assertEqual(raw, original)

    def test_allocated_paid_call_is_settled_and_reused_without_doubling_headroom(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); client = openrouter.Client(deployment())
            plan = {'deployment': client.deployment, 'limits': {'call_seconds': 30, 'analysis_seconds': None}}
            write(root/'plan.json', plan)
            from commentscope.factory.claim_clusters import read_json, sha
            ph = sha(root/'plan.json'); ledger = SpendLedger(root/'spend.sqlite', 'authored', maximum_usd=1)
            base = Mock(); raw = receipt({'same': True}); raw['usage']['cost'] = .0001
            base.call.return_value = raw
            paid = PaidBudget(base, ledger, plan_sha256=ph, deployment=client.deployment,
                              maximum_run_usd=.25, paid_provider=client.generate,
                              key_metadata=lambda: {'limit_remaining': 1})
            runner = CheckpointRunner(openrouter.Runner(root, plan, paid, client),
                                      openrouter.generation_allocation(client.deployment, require_explicit=True))
            first = runner.call('owner', logical()); second = runner.call('owner', logical())
            self.assertEqual(first, second); base.call.assert_called_once()
            self.assertEqual(base.call.call_args.args[0]['max_tokens'], 1152)
            stored = read_json(root/'calls/0001-owner.request.json')
            self.assertEqual(stored['request_sha256'], client.measure(logical())['allocated_request_sha256'])
            self.assertEqual(ledger.summary()['confirmed_usd'], '0.0001')
            self.assertEqual(ledger.summary()['uncertain_calls'], 0)


if __name__ == '__main__': unittest.main()
