"""Provider dialect compatibility must preserve the canonical host contract."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.agents import grounded_runtime
from commentscope.contracts import structured_output
from commentscope.contracts.perspective_draft import obj
from commentscope.providers import openrouter
from commentscope.providers.openrouter_budget import PaidBudget, SpendLedger
from commentscope.storage import write_json_exclusive as write
from test_openrouter import deployment

POLICY = 'openai-strict-schema-20261104-v1'


def configured():
    value = deployment()
    value['provider']['only'] = ['openai']
    value['schema_policy'] = POLICY
    return value


def receipt(value, *, finish='stop'):
    return {'id': 'authored-generation', 'model': 'test/authored-model', 'provider': 'OpenAI',
            'choices': [{'message': {'content': json.dumps(value)}, 'finish_reason': finish}],
            'usage': {'cost': .001, 'prompt_tokens': 100, 'completion_tokens': 10}}


class OpenRouterSchemaTests(unittest.TestCase):
    def test_root_union_and_unique_items_are_lowered_without_mutating_canonical_schema(self):
        canonical = grounded_runtime.schema(['E1', 'E2']); original = deepcopy(canonical)
        payload = openrouter.Client(configured()).payload('system', {}, canonical, 512)
        wire = payload['response_format']['json_schema']['schema']
        self.assertEqual(wire['type'], 'object')
        self.assertEqual(wire['required'], ['result'])
        self.assertFalse(wire['additionalProperties'])
        self.assertNotIn('uniqueItems', json.dumps(wire))
        self.assertIn('anyOf', wire['properties']['result'])
        self.assertEqual(canonical, original)

    def test_all_answerability_branches_round_trip_unchanged(self):
        canonical = grounded_runtime.schema(['E1']); client = openrouter.Client(configured())
        req = {'schema': canonical}
        for value in [{'answerability': 'grounded', 'claim_ids': ['E1'], 'limitation': 'none'},
                      {'answerability': 'partial', 'claim_ids': ['E1'], 'limitation': 'missing_evidence'},
                      {'answerability': 'not_in_evidence', 'claim_ids': [], 'limitation': 'missing_evidence'}]:
            raw = receipt({'result': value}); original = deepcopy(raw)
            decoded = client.decode_response(req, raw)
            self.assertEqual(json.loads(decoded['choices'][0]['message']['content']), value)
            self.assertEqual(raw, original)

    def test_wire_may_allow_duplicate_ids_but_host_still_rejects_them(self):
        client = openrouter.Client(configured()); canonical = grounded_runtime.schema(['E1'])
        duplicate = {'answerability': 'grounded', 'claim_ids': ['E1', 'E1'], 'limitation': 'none'}
        wire = client.payload('s', {}, canonical, 512)['response_format']['json_schema']['schema']
        self.assertFalse(structured_output.check_output(wire, {'result': duplicate})['errors'])
        with self.assertRaises(ValueError): client.decode_response({'schema': canonical}, receipt({'result': duplicate}))

    def test_empty_allowlist_keeps_abstention_without_an_empty_enum(self):
        canonical = grounded_runtime.schema([]); client = openrouter.Client(configured())
        value = {'answerability': 'not_in_evidence', 'claim_ids': [], 'limitation': 'missing_evidence'}
        client.payload('s', {}, canonical, 128)
        decoded = client.decode_response({'schema': canonical}, receipt({'result': value}))
        self.assertEqual(json.loads(decoded['choices'][0]['message']['content']), value)
        with self.assertRaises(ValueError):
            client.decode_response({'schema': canonical}, receipt({'result': {**value, 'claim_ids': ['E1']}}))

    def test_foreign_ids_extra_envelope_fields_and_state_mismatches_are_never_repaired(self):
        client = openrouter.Client(configured()); canonical = grounded_runtime.schema(['E1'])
        valid = {'answerability': 'grounded', 'claim_ids': ['E1'], 'limitation': 'none'}
        for value in [{'result': {**valid, 'claim_ids': ['foreign']}},
                      {'result': valid, 'extra': 'not allowed'},
                      {'result': {**valid, 'answerability': 'not_in_evidence'}},
                      {'result': {**valid, 'limitation': 'missing_evidence'}}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.decode_response({'schema': canonical}, receipt(value))

    def test_a_property_named_unique_items_is_data_not_a_schema_keyword(self):
        canonical = obj({'uniqueItems': {'type': 'string', 'enum': ['keep']}})
        wire = openrouter.Client(configured()).payload('s', {}, canonical, 128)['response_format']['json_schema']['schema']
        self.assertEqual(wire, canonical)

    def test_unsupported_keywords_and_open_objects_fail_before_http(self):
        opener = Mock()
        with patch.object(openrouter, 'build_opener', return_value=opener), \
                patch.dict(openrouter.os.environ, {'OPENROUTER_API_KEY': 'synthetic-key'}):
            for schema in [obj({'x': {'allOf': [{'type': 'string'}]}}),
                           obj({'x': {}}),
                           {'type': 'object', 'properties': {'x': {'type': 'string'}}},
                           {'type': 'object', 'properties': {'x': {'type': 'string'}},
                            'required': [], 'additionalProperties': False}]:
                with self.subTest(schema=schema), self.assertRaises(ValueError):
                    openrouter.Client(configured()).generate('s', {}, schema, 128)
        opener.open.assert_not_called()

    def test_schema_size_and_depth_fail_locally(self):
        client = openrouter.Client(configured())
        deep = {'type': 'string'}
        for _ in range(12): deep = obj({'nested': deep})
        for schema in [obj({'id': {'type': 'integer', 'enum': list(range(1001))}}), deep,
                       obj({'id': {'type': 'string', 'enum': ['x'*120001]}}),
                       obj({'id': {'type': 'string', 'enum': [str(i)+'x'*64 for i in range(251)]}})]:
            with self.subTest(schema_kind=list(schema)), self.assertRaises(ValueError):
                client.measure({'system': 's', 'data': {}, 'schema': schema, 'max_tokens': 128})

    def test_policy_cannot_be_enabled_for_another_provider_or_unknown_dialect(self):
        wrong = configured(); wrong['provider']['only'] = ['test-provider']
        for value in [wrong, {**configured(), 'schema_policy': 'arbitrary-relaxation'}]:
            with self.assertRaises(ValueError): openrouter.Client(value)

    def test_legacy_openai_incompatible_schema_fails_before_http_without_silent_lowering(self):
        value = configured(); value.pop('schema_policy')
        opener = Mock()
        with patch.object(openrouter, 'build_opener', return_value=opener), \
                patch.dict(openrouter.os.environ, {'OPENROUTER_API_KEY': 'synthetic-key'}):
            with self.assertRaises(ValueError):
                openrouter.Client(value).generate('s', {}, grounded_runtime.schema(['E1']), 128)
        opener.open.assert_not_called()

    def test_http_worker_retains_the_original_provider_receipt(self):
        raw = receipt({'result': {'answerability': 'not_in_evidence', 'claim_ids': [], 'limitation': 'missing_evidence'}})
        opener = Mock(); opener.open.return_value = BytesIO(json.dumps(raw).encode())
        with patch.object(openrouter, 'build_opener', return_value=opener), \
                patch.dict(openrouter.os.environ, {'OPENROUTER_API_KEY': 'synthetic-key'}):
            actual = openrouter.Client(configured()).generate('s', {}, grounded_runtime.schema(['E1']), 128)
        self.assertEqual(actual, raw)

    def test_invalid_canonical_reply_is_settled_and_kept_before_host_rejection(self):
        raw = receipt({'result': {'answerability': 'grounded', 'claim_ids': ['E1', 'E1'], 'limitation': 'none'}})
        raw['usage']['cost'] = .0001  # Within the fixture's declared price ceiling.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); client = openrouter.Client(configured())
            plan = {'deployment': client.deployment, 'limits': {'call_seconds': 30, 'analysis_seconds': None}}
            write(directory/'plan.json', plan)
            from commentscope.factory.claim_clusters import sha
            ph = sha(directory/'plan.json')
            ledger = SpendLedger(directory/'spend.sqlite', 'authored', maximum_usd=1)
            base = Mock(); base.call.return_value = raw
            budget = PaidBudget(base, ledger, plan_sha256=ph, deployment=client.deployment,
                                maximum_run_usd=.25, paid_provider=client.generate,
                                key_metadata=lambda: {'limit_remaining': 1})
            runner = openrouter.Runner(directory, plan, budget, client)
            result = runner.call('runtime', {'system': 's', 'data': {},
                                 'schema': grounded_runtime.schema(['E1']), 'max_tokens': 128})
            self.assertIn('invalid_response', result['errors'])
            self.assertIsNone(result['output'])
            self.assertEqual(result['transport']['provider_response'], raw)
            self.assertEqual(ledger.summary()['confirmed_usd'], '0.0001')
            self.assertEqual(ledger.summary()['uncertain_calls'], 0)
            self.assertEqual(json.loads((directory/'calls/0001-runtime.result.json').read_text()), result)


if __name__ == '__main__': unittest.main()
