from contextlib import nullcontext
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import pickle
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.providers import host_resources, llama_runtime as runtime
from commentscope.providers.checkpoint_calls import CheckpointRunner, PendingCallError
from commentscope.providers.runtime_runner import RuntimeRunner
from commentscope.storage import write_json_exclusive as write


def deployment(root):
    model, server = root/'test.gguf', root/'test-server'
    model.write_bytes(b'synthetic model identity')
    server.write_bytes(b'synthetic executable identity')
    server.chmod(0o755)
    return {'version': runtime.VERSION,
            'model': {'name': 'synthetic-small', 'repository': 'test/model',
                      'revision': 'a'*40, 'path': str(model), 'sha256': runtime.file_hash(model)},
            'server': {'path': str(server), 'sha256': runtime.file_hash(server), 'libraries': ''},
            'runtime': {'context': 8192, 'threads': 2, 'gpu_layers': 99,
                        'port': 18091, 'batch_size': 128, 'ubatch_size': 64,
                        'call_seconds': 600, 'startup_seconds': 60, 'thinking': False},
            'startup': deepcopy(runtime.STARTUP), 'resource_policy': deepcopy(host_resources.POLICY)}


def observation():
    return {'available_mb': 8192, 'committed_bytes': 8*1024**3,
            'commit_limit': 16*1024**3, 'disk_free_bytes': 10*1024**3, 'gpu_free_mb': 7000}


class PortableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.d = deployment(self.root)

    def test_model_changes_do_not_change_business_request(self):
        opener = Mock()
        opener.open.side_effect = [BytesIO(b'{}'), BytesIO(b'{}')]
        other = deepcopy(self.d)
        other['model']['name'] = 'another-family'
        other['model']['sha256'] = 'b'*64
        with patch.object(runtime, 'build_opener', return_value=opener):
            for d in (self.d, other):
                client = pickle.loads(pickle.dumps(runtime.Client(d)))
                client.generate('system', {'text': '한국어 원문'}, {'type': 'object'}, 512)
        a, b = opener.open.call_args_list
        self.assertEqual(a.args[0].data, b.args[0].data)
        self.assertEqual(a.args[0].full_url, 'http://127.0.0.1:18091/v1/chat/completions')
        payload = json.loads(a.args[0].data)
        self.assertEqual(payload['chat_template_kwargs'], {'enable_thinking': False})
        self.assertEqual(payload['max_tokens'], 512)
        self.assertEqual(a.kwargs['timeout'], 600)

    def test_measure_uses_same_client_and_complete_native_template(self):
        client = runtime.Client(self.d)
        calls = []
        def post(path, payload, **kwargs):
            calls.append((path, payload))
            return {'prompt': 'native template with 한국어'} if path == '/apply-template' else {'tokens': [1]*8000}
        req = {'system': 's', 'data': {'text': '원문 보존'}, 'schema': {}, 'max_tokens': 100}
        with patch.object(client, 'post', side_effect=post):
            result = client.measure(req)
        self.assertFalse(result['fits'])
        self.assertEqual(calls[0][1]['chat_template_kwargs'], {'enable_thinking': False})
        self.assertEqual(json.loads(calls[0][1]['messages'][1]['content']), req['data'])

    def test_safety_settings_cannot_be_silently_relaxed(self):
        for field, value in [('thinking', True), ('context', 4096), ('threads', True),
                             ('port', 80), ('call_seconds', float('inf'))]:
            bad = deepcopy(self.d); bad['runtime'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                runtime.command(bad)
        bad = deepcopy(self.d); bad['resource_policy']['minimum_disk_free_bytes'] = 1
        with self.assertRaises(ValueError):
            runtime.command(bad)

    def test_resource_refusal_prevents_process_creation(self):
        obs = observation(); obs['disk_free_bytes'] = 6*1024**3 - 1
        with patch.object(runtime.subprocess, 'Popen') as spawn, self.assertRaises(RuntimeError):
            with runtime.owned_server(self.d, self.root/'run', lambda: obs, lambda: None):
                self.fail('Must refuse before yielding')
        spawn.assert_not_called()

    def test_changed_weight_is_rejected_before_start(self):
        Path(self.d['model']['path']).write_bytes(b'different model')
        with patch.object(runtime.subprocess, 'Popen') as spawn, self.assertRaises(ValueError):
            with runtime.owned_server(self.d, self.root/'run', observation, lambda: None):
                pass
        spawn.assert_not_called()

    def test_busy_port_is_not_reused_or_killed(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen()
            self.d['runtime']['port'] = listener.getsockname()[1]
            with patch.object(runtime.subprocess, 'Popen') as spawn, self.assertRaises(OSError):
                with runtime.owned_server(self.d, self.root/'run', observation, lambda: None):
                    pass
            spawn.assert_not_called()

    def test_request_exception_still_stops_owned_process(self):
        proc = Mock(pid=12345, returncode=0)
        proc.poll.return_value = None
        with patch.object(runtime.subprocess, 'Popen', return_value=proc), \
             patch.object(runtime.host_resources, 'watch', return_value=nullcontext()), \
             patch.object(runtime.Client, 'post', return_value={'status': 'ok'}):
            with self.assertRaisesRegex(RuntimeError, 'request failed'):
                with runtime.owned_server(self.d, self.root/'run', observation, lambda: None):
                    raise RuntimeError('request failed')
        proc.send_signal.assert_called_once()
        proc.wait.assert_called_once_with(timeout=15)
        self.assertTrue((self.root/'run/stopped.json').is_file())

    def test_existing_checkpoint_contract_records_normalized_output(self):
        root = self.root/'calls-run'
        plan = {'deployment': self.d, 'limits': {'call_seconds': 600, 'analysis_seconds': None}}
        write(root/'plan.json', plan)
        budget = Mock()
        budget.call.return_value = {'choices': [{'message': {'content': '{"answer":"ok"}'},
                                                  'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 20}}
        client = runtime.Client(self.d)
        runner = RuntimeRunner(root, plan, budget, client)
        checkpoint = CheckpointRunner(runner, {'reasoning': 'off', 'reasoning_budget': 0, 'context': 8192})
        req = {'system': 's', 'data': {}, 'schema': {}, 'max_tokens': 512}
        result = checkpoint.call('extract', req)
        self.assertEqual(result['output'], {'answer': 'ok'})
        self.assertEqual(checkpoint.call('extract', req), result)
        budget.call.assert_called_once()
        self.assertEqual(budget.call.call_args.kwargs['provider'], client.generate)
        self.assertEqual(checkpoint.reused, 1)
        intent = next((root/'checkpoints').glob('*.intent.json'))
        intent.with_name(intent.name.replace('.intent.json', '.result.json')).unlink()
        with self.assertRaises(PendingCallError):
            checkpoint.call('extract', req)
        budget.call.assert_called_once()

    def test_unclean_server_shutdown_vetoes_completed_operation(self):
        proc = Mock(pid=12345, returncode=1)
        proc.poll.return_value = None
        with patch.object(runtime.subprocess, 'Popen', return_value=proc), \
             patch.object(runtime.host_resources, 'watch', return_value=nullcontext()), \
             patch.object(runtime.Client, 'post', return_value={'status': 'ok'}):
            with self.assertRaisesRegex(RuntimeError, 'shutdown was not clean'):
                with runtime.owned_server(self.d, self.root/'run', observation, lambda: None):
                    pass
        self.assertEqual(json.loads((self.root/'run/stopped.json').read_text())['returncode'], 1)

    def test_replacement_client_cannot_use_other_deployment_plan(self):
        plan = {'deployment': deepcopy(self.d)}
        plan['deployment']['model']['sha256'] = 'f'*64
        with self.assertRaises(ValueError):
            RuntimeRunner(self.root, plan, Mock(), runtime.Client(self.d))


if __name__ == '__main__':
    unittest.main()
