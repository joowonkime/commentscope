from contextlib import ExitStack, nullcontext
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.checkpoint_calls import PendingCallError
from commentscope.providers.host_resources import POLICY
from commentscope.storage import write_json_exclusive as write
from experiments import source_bound_comparison as c
from tests import test_source_bound_comparison as fixture


class FakeBase:
    calls = []
    interrupt_member = False

    def __init__(self, directory, plan, budget):
        self.directory = directory; self.plan_sha = sha(directory/'plan.json'); self.seq = 0
        self.fake = fixture.FakeRunner()

    def call(self, stage, req, *, provider=None, maximum=None):
        self.seq += 1; self.calls.append((stage, deepcopy(req)))
        write(self.directory/'calls'/f'{self.seq:04}-{stage}.request.json', req)
        if self.interrupt_member and not stage.endswith('-proposals'):
            raise KeyboardInterrupt()
        return self.fake.call(stage, req)


class ResumableComparisonTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.directory = self.root/'comparison'; self.frames = self.root/'frames'
        data = fixture.SourceBoundComparisonTests(); data.setUp()
        for row in data.records:
            write(self.frames/'frames'/(row['source']['id']+'.json'), row)
        write(self.frames/'plan.json', {'requests':[{'id':r['source']['id'], 'source':r['source']} for r in data.records]})
        write(self.frames/'completed.json', {'plan_sha256':sha(self.frames/'plan.json'),
            'completed_calls':6, 'call_errors':0, 'frame_binding_errors':[]})
        self.source = self.root/'source.json'
        self.deployment = {'server':{'path':'synthetic','sha256':'0'*64},
            'models':{'baseline':{'path':'synthetic','sha256':'0'*64}},
            'runtime':{'context':8192,'reasoning':'on','reasoning_budget':1024}}
        write(self.source, {'deployment':self.deployment})
        self.cycle = self.root/'cycle.json'
        write(self.cycle, {'goal_revision':'factory-goal-20261014-r4','cycle_id':'mvp-factory-20261014',
                          'limit_seconds':None,'analysis_seconds':None,'ledger':str(self.root/'ledger.sqlite')})
        stack = ExitStack(); self.addCleanup(stack.close)
        for p in (patch.object(c,'PRIVATE_ROOT',self.root), patch.object(c,'file_hash',return_value='0'*64),
                  patch.object(c,'code_hashes',return_value={}), patch.object(c,'Runner',FakeBase),
                  patch.object(c,'preflight',return_value={})):
            stack.enter_context(p)
        self.server = stack.enter_context(patch.object(c,'owned_server',side_effect=lambda *args:nullcontext()))
        budget = Mock(); budget.summary.return_value = {'calls':[]}
        stack.enter_context(patch.object(c,'InferenceBudget',return_value=budget))
        FakeBase.calls = []; FakeBase.interrupt_member = False
        c.prepare(self.directory,self.frames,self.source,self.cycle)

    def test_two_phases_reuse_only_proposals_and_keep_all_memberships(self):
        stage = c.run(self.directory,proposals_only=True)
        self.assertFalse(stage['execution_complete']); self.assertFalse(stage['quality_gate_passed'])
        self.assertEqual(stage['membership_judgments'],0)
        self.assertEqual([s for s,_ in FakeBase.calls],['frame_views-proposals','source_bound-proposals'])
        self.assertEqual([r['max_tokens'] for _,r in FakeBase.calls],[5120,5120])
        report = c.run(self.directory)
        self.assertTrue(report['execution_complete']); self.assertFalse(report['quality_gate_passed'])
        self.assertEqual(len(FakeBase.calls),26)
        self.assertEqual(sum(s.endswith('-proposals') for s,_ in FakeBase.calls),2)
        self.assertEqual(report['arms']['frame_views']['completed_pair_count'],6)
        self.assertEqual(report['arms']['source_bound']['completed_pair_count'],18)
        self.assertFalse(report['cross_run_response_reuse'])
        before = len(FakeBase.calls); c.run(self.directory)
        self.assertEqual(len(FakeBase.calls),before); self.assertEqual(self.server.call_count,2)

    def test_repeated_proposal_checkpoint_does_not_load_a_model(self):
        first = c.run(self.directory,proposals_only=True)
        second = c.run(self.directory,proposals_only=True)
        self.assertEqual(first,second); self.assertEqual(self.server.call_count,1)
        self.assertEqual(len(FakeBase.calls),2)

    def test_pending_interruption_does_not_repeat_inference_or_refund(self):
        FakeBase.interrupt_member = True
        with self.assertRaises(KeyboardInterrupt): c.run(self.directory)
        before = len(FakeBase.calls); FakeBase.interrupt_member = False
        with self.assertRaises(PendingCallError): c.run(self.directory)
        self.assertEqual(len(FakeBase.calls),before)
        self.assertTrue((self.directory/'attempts/0001.failed.json').exists())
        self.assertTrue((self.directory/'attempts/0002.failed.json').exists())
        self.assertFalse((self.directory/'completed.json').exists())

    def test_mutated_saved_candidate_is_not_silently_accepted(self):
        c.run(self.directory,proposals_only=True)
        path = self.directory/'artifacts/source_bound/proposals.json'
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'checkpoint changed'):
            c.run(self.directory,proposals_only=True)
        self.assertEqual(self.server.call_count,1)

    def test_changed_input_prevents_resume_before_loading(self):
        c.run(self.directory,proposals_only=True)
        self.source.write_text('{}')
        with self.assertRaisesRegex(ValueError,'Frozen input'):
            c.run(self.directory)
        self.assertEqual(self.server.call_count,1)


class CpuComparisonAdmissionTests(unittest.TestCase):
    def deployment(self):
        from experiments.audit_model_compare import RUNTIME
        return {'server':{'path':'synthetic'},'models':{'baseline':{'path':'synthetic'}},
            'runtime':{**deepcopy(RUNTIME),'context':8192,'gpu_layers':0,'memory_profile':{
                'version':'local-memory-profile-0.4','load_mode':'mmap','cache_ram_mib':0,'cache_idle_slots':False,
                'host_resource_policy':deepcopy(POLICY),'kv_cache':{'k':'q8_0','v':'q8_0'},'flash_attention':'on',
                'batch_size':512,'ubatch_size':128,'host_buffer':False,'repack':False,'device':'none','op_offload':False}}}

    def test_cpu_admission_uses_its_own_finite_deadline_and_unchanged_live_guard(self):
        deployment = self.deployment(); admission, limits = c.execution_contract(deployment)
        self.assertEqual(admission,c.HOST_ONLY_PREFLIGHT); self.assertEqual(limits['call_seconds'],1800)
        self.assertIsNone(limits['analysis_seconds'])
        self.assertEqual(deployment['runtime']['memory_profile']['host_resource_policy'],POLICY)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); plan = {'preflight':admission,'deployment':deployment}
            write(directory/'plan.json',plan)
            report = c.preflight(directory,plan,observe=lambda:{'available_mb':8000,'committed_bytes':20*1024**3,
                'commit_limit':28*1024**3,'disk_free_bytes':18*1024**3})
            self.assertTrue(report['admitted']); self.assertFalse(report['quality_gate_passed'])

    def test_qualification_rejects_failed_or_mismatched_trial(self):
        deployment = self.deployment()
        for field,value in [('call_errors',1),('resource_stop',True),('completed_calls',5),('minimum_available_mb',0)]:
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp); path = directory/'plan.json'
                write(path,{'artifact_kind':'local-resource-profile-probe-0.1','deployment':deployment})
                write(directory/'completed.json',{'plan_sha256':sha(path),'completed_calls':6,'call_errors':0,
                    'frame_binding_errors':[],'resource_stop':False,'observation_errors':0,'eligible_for_whole_corpus_trial':True,
                    'minimum_available_mb':8000,'minimum_commit_headroom_bytes':2*1024**3,'minimum_disk_free_bytes':18*1024**3,
                    field:value})
                write(directory/'server/stopped.json',{'returncode':0})
                write(directory/'server/runtime.json',{'command':c.command(deployment,'baseline')})
                with self.assertRaises(ValueError): c.qualification(path,deployment)
