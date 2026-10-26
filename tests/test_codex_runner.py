from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, Mock

from commentscope.providers import codex_runner as cr
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner, PendingCallError
from commentscope.storage import write_json_exclusive as write
from experiments.compare_local_codex import request_pack


FAKE = '''#!/usr/bin/env python3
import json,sys,time,os
from pathlib import Path
MODE = %r
if MODE == 'sleep': time.sleep(60)
if MODE == 'cache':
    cache=Path(os.environ['CODEX_HOME'])/'plugins';cache.mkdir();(cache/'index.json').write_text('{}')
print(json.dumps({'type':'turn.started'}),flush=True)
if MODE == 'tool': print(json.dumps({'type':'item.completed','item':{'type':'command_execution'}}))
Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('{"ok":true}')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':50,'output_tokens':10}}),flush=True)
'''


class CodexContractTests(unittest.TestCase):
    def test_cloud_guard_does_not_require_local_weight_disk_or_gpu_reserves(self):
        sample={'available_mb':2048,'committed_bytes':2*1024**3,'commit_limit':4*1024**3,
                'disk_free_bytes':2*1024**3,'gpu_free_mb':0}
        self.assertFalse(cr.resource_reasons(sample))
        from commentscope.providers import host_resources
        self.assertIn('low_host_disk',host_resources.reasons(sample,host_resources.POLICY))
        sample['disk_free_bytes']=512*1024**2
        self.assertIn('low_host_disk',cr.resource_reasons(sample))

    def test_legacy_mock_runner_does_not_invent_a_provider_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Mock(directory=Path(tmp),plan_sha='a'*64)
            base.call.return_value={'output':{'ok':True},'errors':[]}
            cached=CheckpointRunner(base,{'context':8192,'reasoning':'off','reasoning_budget':0})
            cached.call('case',{'system':'Synthetic','data':{},'schema':{},'max_tokens':64})
            intent=json.loads(next((Path(tmp)/'checkpoints').glob('*.intent.json')).read_text())
            self.assertEqual(intent['provider'],'local_llama')

    def test_command_and_environment_do_not_use_paid_key_or_prior_context(self):
        root=Path(tempfile.gettempdir()).resolve()
        d = {'version':cr.VERSION,'executable':str(root/'codex'),'sha256':'a'*64,
             'cli_version':'test','model':'test-model','reasoning_effort':'low',
             'auth_home':str(root/'auth'),'call_seconds':600}
        argv = cr.command(d,root/'new-run')
        for flag in ('--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check','--output-schema'):
            self.assertIn(flag,argv)
        self.assertNotIn('resume',argv);self.assertNotIn('fork',argv)
        self.assertIn('read-only',argv)
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'not-a-real-key','OPENAI_API_KEY':'not-a-real-key',
                                   'CODEX_API_KEY':'not-a-real-key','OPENAI_BASE_URL':'https://example.invalid'}):
            env = cr.isolated_environment(root/'new-home',root/'new-work')
        self.assertFalse(any(k.endswith('_API_KEY') for k in env))
        self.assertNotIn('OPENAI_BASE_URL',env);self.assertEqual(env['CODEX_HOME'],str(root/'new-home'))

    def test_pack_contains_fixed_requests_without_expected_answers(self):
        pack = request_pack()
        self.assertEqual(len(pack['cases']),8)
        self.assertFalse(pack['independent_gold'])
        self.assertEqual(len({c['id'] for c in pack['cases']}),8)
        for case in pack['cases']:
            self.assertEqual(set(case),{'id','request'})
            self.assertEqual(set(case['request']),{'system','data','schema','max_tokens'})


@unittest.skipUnless(os.name == 'posix','Isolated CLI process ownership uses Linux/WSL')
class CodexOwnedProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.auth = self.root/'auth';self.auth.mkdir()
        (self.auth/'auth.json').write_text(json.dumps({'auth_mode':'chatgpt','OPENAI_API_KEY':None}))
        self.exe = self.root/'fake-codex';self.exe.write_text(FAKE % 'ok');self.exe.chmod(0o755)
        self.plan = {'deployment':{'version':cr.VERSION,'executable':str(self.exe),
            'sha256':cr.file_sha256(self.exe),'cli_version':'fake','model':'test-model',
            'reasoning_effort':'low','auth_home':str(self.auth),'call_seconds':5}}
        self.run = self.root/'run';write(self.run/'plan.json',self.plan)
        self.budget = InferenceBudget(self.root/'ledger.sqlite','test',limit_seconds=None)
        self.request = {'system':'Return the object.','data':{'text':'synthetic'},
            'schema':{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False},
            'max_tokens':64}

    def runner(self,guard=lambda:None):
        return cr.CodexRunner(self.run,self.plan,self.budget,guard)

    def states(self):
        with sqlite3.connect(self.root/'ledger.sqlite') as db:
            return db.execute('select state from calls').fetchall()

    def test_success_is_recorded_once_and_checkpoint_names_provider(self):
        original = (self.auth/'auth.json').read_bytes()
        runner = self.runner();cached = CheckpointRunner(runner,{'context':8192,'reasoning':'off','reasoning_budget':0})
        first = cached.call('case',self.request)
        self.assertEqual(first['output'],{'ok':True})
        self.assertEqual(cached.call('case',self.request),first)
        self.assertEqual(self.states(),[('ok',)])
        intent = json.loads(next((self.run/'checkpoints').glob('*.intent.json')).read_text())
        self.assertEqual(intent['provider'],'codex_chatgpt_cli')
        self.assertFalse(list((self.run/'codex').glob('*/home/auth.json')))
        self.assertEqual((self.auth/'auth.json').read_bytes(),original)
        started=json.loads(next((self.run/'codex').glob('*/started.json')).read_text())
        self.assertFalse(Path(started['work_directory']).is_relative_to(self.run))
        self.assertFalse(started['repository_context'])
        self.assertFalse(Path(started['work_directory']).exists())

    def test_timeout_stops_process_and_canceled_checkpoint_cannot_replay(self):
        self.exe.write_text(FAKE % 'sleep');self.plan['deployment']['sha256']=cr.file_sha256(self.exe)
        self.plan['deployment']['call_seconds']=0.15
        (self.run/'plan.json').write_text(json.dumps(self.plan))
        cached = CheckpointRunner(self.runner(),{'context':8192,'reasoning':'off','reasoning_budget':0})
        with self.assertRaises(TimeoutError):cached.call('case',self.request)
        self.assertEqual(self.states(),[('timeout',)])
        stop = json.loads(next((self.run/'codex').glob('*/stopped.json')).read_text())
        with self.assertRaises(ProcessLookupError):os.kill(stop['pid'],0)
        with self.assertRaises(PendingCallError):cached.call('case',self.request)
        self.assertFalse(list((self.run/'codex').glob('*/home/auth.json')))

    def test_tool_using_result_is_rejected_and_failure_keeps_no_credential_link(self):
        self.exe.write_text(FAKE % 'tool');self.plan['deployment']['sha256']=cr.file_sha256(self.exe)
        (self.run/'plan.json').write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError,'Tool-using'):self.runner().call('case',self.request)
        self.assertEqual(self.states(),[('error',)])
        self.assertFalse(list((self.run/'codex').glob('*/home/auth.json')))

    def test_cli_cache_does_not_break_completion_or_leave_authentication(self):
        self.exe.write_text(FAKE % 'cache');self.plan['deployment']['sha256']=cr.file_sha256(self.exe)
        (self.run/'plan.json').write_text(json.dumps(self.plan))
        self.assertEqual(self.runner().call('case',self.request)['output'],{'ok':True})
        self.assertEqual(self.states(),[('ok',)])
        self.assertFalse(list((self.run/'codex').glob('*/home/auth.json')))
        self.assertTrue(list((self.run/'codex').glob('*/home/plugins/index.json')))

    def test_api_auth_and_changed_executable_are_rejected_before_dispatch(self):
        (self.auth/'auth.json').write_text(json.dumps({'auth_mode':'apikey','OPENAI_API_KEY':'synthetic'}))
        with self.assertRaisesRegex(ValueError,'ChatGPT authentication'):self.runner().call('case',self.request)
        self.assertFalse(self.states())
        self.exe.write_text('changed')
        with self.assertRaisesRegex(ValueError,'executable changed'):self.runner().call('case',self.request)

    def test_guard_failure_after_workdir_creation_removes_authentication_link(self):
        checks = []
        def guard():
            checks.append(True)
            if len(checks)==2:raise RuntimeError('quota held')
        with self.assertRaisesRegex(RuntimeError,'quota held'):self.runner(guard).call('case',self.request)
        self.assertFalse(self.states())
        self.assertFalse(list((self.run/'codex').glob('*/home/auth.json')))
