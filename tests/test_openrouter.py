"""Synthetic HTTP responses only; no API key, network or paid inference."""
from io import BytesIO
import json
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from commentscope.agents.runtime_probe import runtime_probe, runtime_check
from commentscope.factory.claim_clusters import read_json
from commentscope.providers import openrouter as remote
from commentscope.providers.checkpoint_calls import CheckpointRunner, PendingCallError
from commentscope.storage import write_json_exclusive as write
import test_minimal_pipeline as fixture


def deployment():
    return {'version': remote.VERSION, 'model': 'test/authored-model', 'context': 8192,
            'call_seconds': 30, 'provider': {'only': ['test-provider'],
            'max_price': {'prompt': 0.1, 'completion': 0.3, 'request': 0}}}


class DirectTestBudget:
    """Exercises the real client without creating a multiprocessing worker."""
    def call(self, req, plan_sha, *, timeout_seconds, provider):
        return provider(req['system'], req['data'], req['schema'], max_tokens=req['max_tokens'])


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(remote.os.environ, {'OPENROUTER_API_KEY': 'synthetic-test-key'})
        env.start(); self.addCleanup(env.stop)
        self.opener = Mock()
        transport = patch.object(remote, 'build_opener', return_value=self.opener)
        transport.start(); self.addCleanup(transport.stop)

    def test_logical_request_and_schema_are_preserved_and_routing_is_explicit(self):
        self.opener.open.return_value = BytesIO(b'{}')
        schema = {'anyOf': [{'type': 'object'}, {'type': 'array'}]}
        remote.Client(deployment()).generate('source-only system', {'text': '한국어 원문'}, schema, 512)
        call = self.opener.open.call_args
        req = call.args[0]; payload = json.loads(req.data)
        self.assertEqual(req.full_url, remote.ENDPOINT)
        self.assertEqual(req.get_header('Authorization'), 'Bearer synthetic-test-key')
        self.assertEqual(json.loads(payload['messages'][1]['content']), {'text': '한국어 원문'})
        self.assertEqual(payload['messages'][0]['content'], 'source-only system')
        self.assertEqual(payload['response_format']['json_schema']['schema'], schema)
        self.assertEqual(payload['model'], deployment()['model'])
        self.assertEqual(payload['max_tokens'], 512)
        self.assertEqual(call.kwargs['timeout'], 30)
        self.assertIs(payload['provider']['require_parameters'], True)
        self.assertIs(payload['provider']['allow_fallbacks'], False)
        self.assertEqual(payload['provider']['max_price'], deployment()['provider']['max_price'])
        self.assertNotIn('reasoning', payload)

    def test_optional_reasoning_setting_is_preserved(self):
        self.opener.open.return_value = BytesIO(b'{}')
        d = deployment(); d['reasoning'] = {'enabled': False}
        remote.Client(d).generate('s', {}, {}, 12)
        self.assertEqual(json.loads(self.opener.open.call_args.args[0].data)['reasoning'], {'enabled': False})

    def test_client_never_serializes_the_environment_key(self):
        client = remote.Client(deployment())
        self.assertNotIn(b'synthetic-test-key', pickle.dumps(client))
        self.assertNotIn('synthetic-test-key', json.dumps(client.deployment))

    def test_missing_key_refuses_before_network(self):
        with patch.dict(remote.os.environ, {'OPENROUTER_API_KEY': ''}):
            with self.assertRaisesRegex(ValueError, 'not configured'):
                remote.Client(deployment()).generate('s', {}, {}, 12)
        self.opener.open.assert_not_called()

    def test_bad_configuration_cannot_relax_routing_or_embed_keys(self):
        for field, value in [('call_seconds', float('nan')), ('context', True),
                             ('model', ''), ('api_key', 'never-store-a-key'),
                             ('provider', {'allow_fallbacks': True}),
                             ('provider', {'max_price': {'prompt': float('inf'), 'completion': 1, 'request': 0}})]:
            with self.subTest(field=field):
                d = deployment(); d[field] = value
                with self.assertRaises(ValueError): remote.Client(d)

    def test_output_limits_are_checked_before_network(self):
        for value in (True, 0, -1, 8192):
            with self.subTest(value=value), self.assertRaises(ValueError):
                remote.Client(deployment()).generate('s', {}, {}, value)
        self.opener.open.assert_not_called()

    def test_http_errors_are_not_automatically_retried(self):
        self.opener.open.side_effect = HTTPError(remote.ENDPOINT, 429, 'test limit', {}, None)
        with self.assertRaises(HTTPError): remote.Client(deployment()).generate('s', {}, {}, 12)
        self.assertEqual(self.opener.open.call_count, 1)

    def test_full_pipeline_and_agent_turns_use_remote_shape_without_a_local_server(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        plan = {'deployment': deployment(), 'limits': {'call_seconds': 30, 'analysis_seconds': None}}
        write(root/'plan.json', plan)
        scripted = fixture.ScriptedRunner()
        def respond(req, *, timeout):
            payload = json.loads(req.data)
            logical = {'system': payload['messages'][0]['content'],
                       'data': json.loads(payload['messages'][1]['content']),
                       'schema': payload['response_format']['json_schema']['schema'],
                       'max_tokens': payload['max_tokens']}
            value = scripted.call('synthetic-http', logical)['output']
            response = {'choices': [{'message': {'content': json.dumps(value)}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 12, 'completion_tokens': 5, 'cost': 0.0001}}
            return BytesIO(json.dumps(response).encode())
        self.opener.open.side_effect = respond
        runner = CheckpointRunner(remote.Runner(root, plan, DirectTestBudget(), remote.Client(deployment())),
                                  {'context': 8192, 'reasoning': 'off', 'reasoning_budget': 0})
        factory = fixture.MinimalPipelineTests(); factory.setUp()
        output = factory.process(runner)
        runtime = runtime_probe(output['agent_inputs']['bundle'], runner)
        runtime_check(runtime, output['agent_inputs']['compiled'])
        self.assertEqual(len(output['agent_inputs']['compiled']['profiles']), 2)
        self.assertEqual(len(runtime['turns']), 6)
        self.assertEqual(output['errors'], [])
        for path in (root/'checkpoints').glob('*.intent.json'):
            self.assertEqual(read_json(path)['provider'], remote.Runner.provider_identity)
        raw = '\n'.join(p.read_text() for p in (root/'calls').glob('*.json'))
        self.assertNotIn('synthetic-test-key', raw)
        self.assertIn('"cost": 0.0001', raw)
        # Reuse the original stored logical request, not a new HTTP operation.
        stored = read_json(next((root/'calls').glob('*.request.json')))['request']
        before = self.opener.open.call_count
        original_stage = next((root/'calls').glob('*.request.json')).name.split('-', 1)[1].removesuffix('.request.json')
        runner.call(original_stage, stored)
        self.assertEqual(self.opener.open.call_count, before)
        intent = next(p for p in (root/'checkpoints').glob('*.intent.json')
                      if read_json(p)['stage'] == original_stage)
        intent.with_name(intent.name.replace('.intent.json', '.result.json')).unlink()
        with self.assertRaises(PendingCallError): runner.call(original_stage, stored)
        self.assertEqual(self.opener.open.call_count, before)


if __name__ == '__main__': unittest.main()
