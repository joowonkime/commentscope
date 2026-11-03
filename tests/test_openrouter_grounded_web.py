"""Offline HTTP entry point checks with authored responses and real spend limits."""
from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.agents.grounded_web import GroundedServer
from commentscope.providers.budget import BudgetExhausted
from commentscope.providers.checkpoint_calls import PendingCallError
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.storage import write_json_exclusive as write
from experiments.grounding_contract_demo import fixture
from test_grounded_web import provider
from test_openrouter import deployment, DirectTestBudget
from tools import serve_openrouter_web as entry


class OpenRouterGroundedWebTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='runs', prefix='test-remote-web-')
        self.addCleanup(tmp.cleanup); self.root = Path(tmp.name); self.directory = self.root/'server'
        self.bundle = self.root/'bundle.json'; write(self.bundle, fixture())
        self.deployment = deployment(); self.deployment['context'] = 65536
        self.policy = {'account_id': 'authored-web', 'ledger': str(self.root/'spend.sqlite'),
                       'maximum_usd': '1', 'opening_charge_usd': '0'}
        self.cost = 0.00001
        def generate(system, data, schema, **kwargs):
            if data['QUESTION'] == 'What is the exact annual implementation cost?':
                # An authored model abstention exercises the transport bridge;
                # this fixture is not a semantic answerability classifier.
                value = {'answerability': 'not_in_evidence', 'claim_ids': [], 'limitation': 'missing_evidence'}
                answer = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value)}}]}
            else:
                answer = provider(system, data, schema, **kwargs)
            answer['usage'] = {'cost': self.cost, 'prompt_tokens': 12, 'completion_tokens': 5}
            return answer
        self.generate = patch.object(entry.openrouter.Client, 'generate', side_effect=generate).start()
        patch.object(entry, 'provider_preflight', return_value={'authored': True}).start()
        patch.object(entry, 'key_metadata', return_value={'limit_remaining': 1}).start()
        patch.object(entry, 'InferenceBudget', return_value=DirectTestBudget()).start()
        patch.dict(entry.os.environ, {'OPENROUTER_API_KEY': 'synthetic-test-key'}).start()
        self.addCleanup(patch.stopall)

    def prepare(self, maximum='0.25'):
        return entry.prepare(self.directory, self.bundle, self.deployment, self.policy, maximum)

    def ledger(self):
        return SpendLedger(Path(self.policy['ledger']), self.policy['account_id'], maximum_usd='1', opening_charge_usd='0')

    def finish(self, app, token):
        deadline = time.monotonic()+5
        while app.busy and time.monotonic()<deadline: time.sleep(.01)
        self.assertFalse(app.busy)
        return app.state(token)

    def test_prepare_freezes_bundle_and_limits_without_a_model_or_key_leak(self):
        plan = self.prepare()
        self.assertEqual(plan['bundle_sha256'], sha(self.bundle))
        self.assertEqual(plan['spend_policy'], self.policy)
        self.assertEqual(plan['maximum_cost_usd'], '0.25')
        self.assertNotIn('synthetic-test-key', (self.directory/'plan.json').read_text())
        self.generate.assert_not_called()

    def test_changed_bundle_or_plan_blocks_before_dispatch(self):
        self.prepare(); original = self.bundle.read_text(); self.bundle.write_text('{}')
        with self.assertRaises(ValueError): entry.build_app(self.directory)
        self.bundle.write_text(original)
        plan = json.loads((self.directory/'plan.json').read_text()); plan['maximum_cost_usd'] = '1'
        (self.directory/'plan.json').write_text(json.dumps(plan))
        with self.assertRaises(ValueError): entry.build_app(self.directory)
        self.generate.assert_not_called()

    def test_active_reasoning_needs_explicit_headroom_before_server_preflight(self):
        self.deployment['reasoning'] = {'effort': 'low'}
        with patch.object(entry, 'provider_preflight', return_value={'authored': True}) as preflight:
            with self.assertRaisesRegex(ValueError, 'headroom'): self.prepare()
        preflight.assert_not_called(); self.generate.assert_not_called()

    def test_runtime_uses_the_same_allocated_output_as_its_capacity_check(self):
        self.deployment.update(reasoning={'effort': 'low'}, reasoning_output_tokens=1024)
        self.prepare(); app = entry.build_app(self.directory); token = app.create()['token']
        app.ask(token, 'Your position?', 'q1')
        self.assertEqual(self.finish(app, token)['job'], 'done')
        stored = read_json(next((self.directory/'calls').glob('*.request.json')))['request']
        self.assertEqual(self.generate.call_args.kwargs['max_tokens'], stored['max_tokens'])
        self.assertEqual(stored['max_tokens'], 180+1024)
        self.assertEqual(self.ledger().summary()['confirmed_usd'], '0.00001')

    def test_copied_server_plan_cannot_reset_its_origin_or_cost_limit(self):
        self.prepare(); other = self.root/'copy'; shutil.copytree(self.directory, other)
        with self.assertRaises(ValueError): entry.build_app(other)
        self.generate.assert_not_called()

    def test_parsed_remote_response_reaches_existing_app_and_idempotent_source_flow(self):
        self.prepare(); app = entry.build_app(self.directory); token = app.create()['token']
        app.ask(token, 'Your position?', 'q1'); state = self.finish(app, token)
        self.assertEqual(state['job'], 'done')
        point = state['rounds'][0]['answers'][0]['points'][0]
        source_id = point['citations']['comment_evidence'][0]['source_id']
        self.assertTrue(app.source(token, source_id)['text'])
        self.assertNotIn('synthetic-test-key', json.dumps(state))
        self.assertNotIn('result', state['rounds'][0]['answers'][0])
        app.ask(token, 'Your position?', 'q1')
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(self.ledger().summary()['confirmed_usd'], '0.00001')

    def test_server_cost_ceiling_is_shared_across_sessions_and_restarts(self):
        self.deployment['provider']['max_price'] = {'prompt': 0, 'completion': 0, 'request': 0.1}
        self.cost = 0.1; self.prepare('0.15'); app = entry.build_app(self.directory)
        first = app.create()['token']; app.ask(first, 'Your position?', 'q1')
        self.assertEqual(self.finish(app, first)['job'], 'done')
        app = entry.build_app(self.directory)
        second = app.create()['token']; app.ask(second, 'What is the central position?', 'q2')
        state = self.finish(app, second)
        self.assertEqual(state['job'], 'error'); self.assertEqual(state['rounds'], [])
        self.assertFalse(state['can_ask'])
        self.assertEqual(state['remote_status'], 'budget_exhausted')
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(self.ledger().summary()['confirmed_usd'], '0.1')

    def test_unknown_charge_or_pending_request_blocks_startup(self):
        self.prepare(); ledger = self.ledger()
        call = ledger.reserve('a'*64, 'b'*64, '0.1', run_limit_usd='0.2', key_remaining_usd='1')
        ledger.finish(call, None)
        with self.assertRaises(BudgetExhausted): entry.build_app(self.directory)
        self.generate.assert_not_called()

    def test_incomplete_request_cannot_be_resent_on_server_restart(self):
        self.prepare(); write(self.directory/'checkpoints'/('a'*64+'.intent.json'), {'authored': 'pending'})
        with self.assertRaises(PendingCallError): entry.build_app(self.directory)
        self.generate.assert_not_called()

    def test_provider_failure_does_not_publish_a_successful_round_or_retry(self):
        self.prepare(); self.generate.side_effect = RuntimeError('private upstream failure')
        app = entry.build_app(self.directory); token = app.create()['token']
        app.ask(token, 'Your position?', 'q1'); state = self.finish(app, token)
        self.assertEqual(state['job'], 'error'); self.assertEqual(state['rounds'], [])
        self.assertFalse(state['can_ask'])
        self.assertEqual(state['remote_status'], 'reconcile_required')
        app.ask(token, 'Your position?', 'q1'); self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(self.ledger().summary()['uncertain_calls'], 1)

    def test_two_authored_profiles_roundtrip_through_HTTP_with_original_opinion_and_source(self):
        bundle = fixture(); second = deepcopy(bundle['candidates'][0]); second['id'] = 'P2'
        bundle['candidates'].append(second); self.bundle.write_text(json.dumps(bundle))
        self.prepare(); app = entry.build_app(self.directory); server = GroundedServer(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        conn = HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
        headers = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{server.server_address[1]}'}
        def post(path, body, token=None):
            h = {**headers, **({'X-Session-Token': token} if token else {})}
            conn.request('POST', path, body=json.dumps(body), headers=h)
            reply = conn.getresponse(); return reply.status, json.loads(reply.read())
        try:
            status, session = post('/api/session', {'ids': ['P1', 'P2'], 'initial_opinion': 'My original view.'})
            self.assertEqual(status, 201); token = session['token']
            status, _ = post('/api/ask', {'question': 'Your position?', 'request_id': 'q1'}, token)
            self.assertEqual(status, 202); self.finish(app, token)
            conn.request('GET', '/api/state', headers={'X-Session-Token': token})
            reply = conn.getresponse(); self.assertEqual(reply.status, 200); state = json.loads(reply.read())
            self.assertEqual(state['initial_opinion'], 'My original view.')
            self.assertEqual(len(state['rounds'][0]['answers']), 2)
            sid = state['rounds'][0]['answers'][0]['points'][0]['citations']['comment_evidence'][0]['source_id']
            status, source = post('/api/source', {'source_id': sid}, token)
            self.assertEqual(status, 200); self.assertTrue(source['text'])
            status, _ = post('/api/ask', {'question': 'What is the exact annual implementation cost?', 'request_id': 'q2'}, token)
            self.assertEqual(status, 202); final = self.finish(app, token)
            self.assertTrue(all(a['status'] == 'abstain' for a in final['rounds'][-1]['answers']))
        finally:
            conn.close(); server.shutdown(); server.server_close(); thread.join(2)

    def test_server_shutdown_finishes_an_active_bounded_request_before_releasing_its_lock(self):
        self.prepare(); entered = threading.Event(); original = self.generate.side_effect; apps = []
        def slow(*args, **kwargs):
            entered.set(); time.sleep(.1); return original(*args, **kwargs)
        self.generate.side_effect = slow
        class Server:
            server_address = ('127.0.0.1', 8766)
            def __init__(_, app, port): apps.append(app)
            def serve_forever(_):
                token = apps[0].create()['token']; apps[0].ask(token, 'Your position?', 'q1')
                self.assertTrue(entered.wait(2)); raise KeyboardInterrupt()
            def server_close(_): pass
        with patch.object(entry, 'GroundedServer', Server):
            result = entry.main(['serve', str(self.directory), '--experimental'])
        deadline = time.monotonic()+2
        busy_on_return = apps[0].busy
        while apps[0].busy and time.monotonic()<deadline: time.sleep(.01)
        self.assertFalse(busy_on_return)
        self.assertEqual(result, 0)


if __name__ == '__main__': unittest.main()
