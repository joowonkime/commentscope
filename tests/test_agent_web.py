from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from commentscope.agents.web import ComparisonApp, ComparisonServer, WebError, SESSION_TTL
from commentscope.agents.runtime import AUDIT_SYSTEM
from test_agents import profile, response, answer


def bundle():
    return {'agents': [profile('A'), profile('B')], 'non_agents': [], 'dataset': {'sample_size': 10, 'reviewed_sources': 6},
            'expires_at': '2099-01-01T00:00:00Z', 'human_approved': False, 'accepted_perspectives': 0}


def provider(system, data, schema):
    if system == AUDIT_SYSTEM:
        return response({'verdict': 'supported', 'reason': 'SAME_MODEL_AUDIT'})
    return response(answer(data['YOUR_EVIDENCE'][0]['evidence_id'], text='SOURCE_BOUND_ANSWER'))


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = ComparisonApp(bundle(), 'test-hash', self.temp.name, {'model': 'synthetic'}, provider=provider)
        self.token = self.app.create()['token']

    def finish(self):
        deadline = time.monotonic() + 5
        while self.app.busy and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(self.app.busy, 'Worker did not finish')
        return self.app.state(self.token)

    def test_answer_progress_export_and_private_checkpoints(self):
        self.app.ask(self.token, 'question', 'request-1')
        state = self.finish()
        self.assertEqual(state['job']['status'], 'done')
        self.assertEqual(state['job']['model_calls'], 4)
        self.assertEqual(len(state['rounds'][0]['answers']), 2)
        self.assertNotIn('SAME_MODEL_AUDIT', json.dumps(state))
        self.assertNotIn('attempts', state['rounds'][0]['answers'][0])
        exported = json.loads(self.app.export(self.token, 'json'))
        self.assertIn('SAME_MODEL_AUDIT', json.dumps(exported))
        self.assertFalse(exported['human_approved'])
        self.assertIn('SOURCE_BOUND_ANSWER', self.app.export(self.token, 'html').decode())
        self.assertEqual(len(list(Path(self.temp.name).glob('*/*.json'))), 5)

    def test_rejected_drafts_hidden_in_state_and_html_but_retained_in_json(self):
        def rejecting(system, data, schema):
            if system == AUDIT_SYSTEM:
                return response({'verdict': 'revise', 'reason': 'BAD_REASON_PRIVATE'})
            return response(answer(data['YOUR_EVIDENCE'][0]['evidence_id'], text='BAD_DRAFT_PRIVATE'))
        self.app.provider = rejecting
        self.app.ask(self.token, 'question', 'r1')
        state = self.finish()
        self.assertEqual(state['rounds'][0]['answers'][0]['status'], 'abstain')
        for text in [json.dumps(state), self.app.export(self.token, 'html').decode()]:
            self.assertNotIn('BAD_DRAFT_PRIVATE', text)
            self.assertNotIn('BAD_REASON_PRIVATE', text)
        self.assertIn('BAD_DRAFT_PRIVATE', self.app.export(self.token, 'json').decode())

    def test_duplicate_submit_idempotent_and_different_payload_rejected(self):
        self.app.ask(self.token, 'question', 'r1'); self.finish()
        self.app.ask(self.token, 'question', 'r1')
        self.assertEqual(len(self.app.state(self.token)['rounds']), 1)
        with self.assertRaises(WebError) as exc:
            self.app.ask(self.token, 'different', 'r1')
        self.assertEqual(exc.exception.code, 'request_id_conflict')

    def test_one_inference_lane_reset_and_export_blocked_while_running(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set(); release.wait(5)
            return provider(*args)
        self.app.provider = slow
        second = self.app.create()['token']
        self.app.ask(self.token, 'question', 'r1')
        self.assertTrue(entered.wait(2))
        try:
            for action in [lambda: self.app.ask(second, 'other', 'r2'),
                           lambda: self.app.reset(self.token), lambda: self.app.export(self.token, 'json')]:
                with self.assertRaises(WebError) as exc:
                    action()
                self.assertEqual(exc.exception.code, 'inference_busy')
            self.assertFalse(self.app.state(second)['can_ask'])
        finally:
            release.set(); self.finish()

    def test_independent_browser_sessions_and_agent_histories(self):
        calls = []
        def capture(system, data, schema):
            if system != AUDIT_SYSTEM:
                calls.append(deepcopy(data))
            return provider(system, data, schema)
        self.app.provider = capture
        self.app.ask(self.token, 'first', 'r1'); self.finish()
        other = self.app.create()['token']
        self.app.ask(other, 'new-tab', 'r2'); self.finish()
        self.app.ask(self.token, 'follow-up', 'r3'); self.finish()
        self.assertEqual(calls[2]['OWN_HISTORY'], [])
        self.assertEqual(calls[3]['OWN_HISTORY'], [])
        self.assertEqual(calls[4]['OWN_HISTORY'][0]['question'], 'first')
        self.assertNotIn('B-0', json.dumps(calls[4]))
        self.assertNotIn('A-0', json.dumps(calls[5]))

    def test_failed_round_rolls_back_all_histories_and_hides_partial_results(self):
        def fail_second(system, data, schema):
            if system != AUDIT_SYSTEM and data['YOUR_EVIDENCE'][0]['evidence_id'].startswith('B'):
                raise RuntimeError('PRIVATE_ERROR')
            return provider(system, data, schema)
        self.app.provider = fail_second
        self.app.ask(self.token, 'question', 'r1')
        state = self.finish()
        self.assertEqual(state['job']['status'], 'error')
        self.assertEqual(state['rounds'], [])
        self.assertNotIn('PRIVATE_ERROR', json.dumps(state))
        self.assertTrue(all(not a.history for a in self.app.sessions[self.token]['agents']))

    def test_source_changes_block_inference(self):
        def changed():
            raise ValueError('source changed')
        self.app.revalidate = changed
        with self.assertRaises(WebError) as exc:
            self.app.ask(self.token, 'question', 'r1')
        self.assertEqual(exc.exception.code, 'source_validation_failed')
        self.assertFalse(self.app.busy)

    def test_failed_reset_keeps_previous_session(self):
        with patch('commentscope.agents.web.write_json_exclusive', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.app.reset(self.token)
        self.assertEqual(self.app.state(self.token)['rounds'], [])

    def test_source_changes_during_inference_block_publication(self):
        calls = []
        def changed_later():
            calls.append(True)
            if len(calls) > 1:
                raise ValueError('source changed')
        self.app.revalidate = changed_later
        self.app.ask(self.token, 'question', 'r1')
        state = self.finish()
        self.assertEqual(state['rounds'], [])
        self.assertEqual(state['job']['status'], 'error')

    def test_limits_bad_questions_and_session_reset(self):
        for value in ['', ' ', None, 'x' * 1001]:
            with self.assertRaises(WebError):
                self.app.ask(self.token, value, 'bad')
        for i in range(6):
            self.app.ask(self.token, 'question', f'r{i}'); self.finish()
        with self.assertRaises(WebError) as exc:
            self.app.ask(self.token, 'seventh', 'r7')
        self.assertEqual(exc.exception.code, 'question_limit')
        next_ = self.app.reset(self.token)
        self.assertEqual(next_['rounds'], [])
        self.assertNotEqual(next_['token'], self.token)
        with self.assertRaises(WebError):
            self.app.state(self.token)

    def test_expiry_capacity_and_unknown_session(self):
        with self.assertRaises(WebError):
            self.app.state('unknown')
        self.app.sessions[self.token]['touched'] -= SESSION_TTL + 1
        with self.assertRaises(WebError) as exc:
            self.app.state(self.token)
        self.assertEqual(exc.exception.code, 'session_expired')
        for _ in range(8):
            self.app.create()
        with self.assertRaises(WebError) as exc:
            self.app.create()
        self.assertEqual(exc.exception.code, 'session_capacity')
        self.app.bundle['expires_at'] = '2000-01-01T00:00:00Z'
        with self.assertRaises(WebError) as exc:
            self.app.create()
        self.assertEqual(exc.exception.code, 'dataset_expired')


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = ComparisonApp(bundle(), 'hash', self.temp.name, {}, provider=provider)
        self.server = ComparisonServer(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def request(self, path='/', method='GET', body=None, headers=None):
        conn = HTTPConnection(*self.server.server_address, timeout=3)
        self.addCleanup(conn.close)
        conn.request(method, path, body=body, headers=headers or {})
        response_ = conn.getresponse()
        return response_.status, dict(response_.getheaders()), response_.read()

    def post(self, path, value, headers=None):
        return self.request(path, 'POST', json.dumps(value),
                            {'Content-Type': 'application/json', 'Origin': self.origin, **(headers or {})})

    def test_assets_security_headers_and_no_arbitrary_file_serving(self):
        for path in ['/', '/app.js', '/app.css']:
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertNotIn('Access-Control-Allow-Origin', headers)
            self.assertTrue(body)
        self.assertEqual(self.request('/../../README.md')[0], 404)
        self.assertEqual(self.request('/data/snapshot.json')[0], 404)

    def test_dns_rebinding_cross_origin_and_missing_origin_blocked(self):
        self.assertEqual(self.request(headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.post('/api/session', {}, {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/session', 'POST', '{}', {'Content-Type': 'application/json'})[0], 403)
        self.assertEqual(self.post('/api/session', {}, {'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_session_token_required_for_state_exports_and_reset(self):
        for path in ['/api/state', '/api/export.html', '/api/export.json']:
            self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.post('/api/reset', {})[0], 401)
        status, _, raw = self.post('/api/session', {})
        self.assertEqual(status, 201)
        token = json.loads(raw)['token']
        status, _, raw = self.request('/api/state', headers={'X-Session-Token': token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['remaining_questions'], 6)
        status, headers, _ = self.request('/api/export.json', headers={'X-Session-Token': token})
        self.assertEqual(status, 200)
        self.assertIn('attachment', headers['Content-Disposition'])

    def test_bad_json_content_type_and_body_limits(self):
        for data in ['null', '[]', '"str"', '{invalid', 'x' * 8193]:
            self.assertEqual(self.request('/api/session', 'POST', data, {'Origin': self.origin, 'Content-Type': 'application/json'})[0], 400)
        self.assertEqual(self.request('/api/session', 'POST', '{}', {'Origin': self.origin, 'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.post('/api/session', {'unexpected': True})[0], 400)


if __name__ == '__main__':
    unittest.main()
