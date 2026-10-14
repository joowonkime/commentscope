from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from experiments import fresh_direct_pipeline as p
from tests import test_candidate_completion_pipeline as existing
from tests import test_source_span_product_probe as span_tests
from commentscope.storage import write_json_exclusive as write


class SyntheticRunner(span_tests.SpanRunner):
    stages=[]
    def call(self,stage,req,**kwargs):
        self.stages.append(stage)
        if stage=='direct-ground-selection':
            self.seq+=1
            return {'errors':[],'output':{'status':'selected','node_ids':[],'essential_node_ids':[]}}
        return super().call(stage,req,**kwargs)


class FreshDirectPipelineTests(unittest.TestCase):
    def run_synthetic(self,tmp,fail=False):
        root=Path(tmp);source=root/'source';directory=root/'fresh'
        existing.CandidateCompletionPipelineTests().run_synthetic(source,False)
        configuration=p.read_json(source/'plan.json')
        configuration['argument_control_measurement']={'negative_false_approvals':1,'development_controls_passed':False}
        # Foreign history is deliberately present in the configuration input.
        configuration['cached_membership']={'FORBIDDEN':'historical model result'}
        configuration['review']={'FORBIDDEN':'human label'}
        path=root/'configuration.json';write(path,configuration)
        snapshot=Path(configuration['snapshot'])
        loaded=SimpleNamespace(snapshot=SimpleNamespace(comments=list(existing.SOURCES),
                               usage=SimpleNamespace(expires_at=configuration['expires_at'])),sha256=p.sha(snapshot))
        with patch.object(p,'validate'),patch.object(p.base,'load_snapshot',return_value=loaded):
            p.prepare(directory,snapshot,path)
        plan=p.read_json(directory/'plan.json')
        self.assertNotIn('cached_membership',plan);self.assertNotIn('review',plan)
        self.assertFalse(plan['cross_run_response_reuse']);self.assertFalse(plan['runtime_reference_labels'])
        budget=Mock();budget.summary.return_value={'charged_seconds':0,'remaining_seconds':9000}
        SyntheticRunner.stages=[]
        with patch.object(p,'validate'),patch.object(p,'InferenceBudget',return_value=budget), \
             patch.object(p,'Runner',SyntheticRunner),patch.object(p.base,'owned_server'),patch.object(p.downstream,'owned_server'), \
             patch.object(p.base,'load_snapshot',return_value=loaded),patch.object(p.base,'normalize_snapshot',return_value=existing.NORMALIZED), \
             patch.object(SyntheticRunner,'audit_fails',fail):
            p.execute(directory)
        return p.read_json(directory/'completed.json'),directory

    def test_complete_fresh_path_uses_new_discovery_selection_membership_and_direct_grounds(self):
        with TemporaryDirectory() as tmp:
            r,d=self.run_synthetic(tmp)
            self.assertTrue(r['fresh_analysis']);self.assertTrue(r['within_one_hour'])
            self.assertEqual(r['screened_inputs'],2);self.assertEqual(r['qualified_agents'],0)
            self.assertFalse(r['quality_gate_passed']);self.assertEqual(r['retrieval_neighborhoods'],2)
            for stage in ('embedding','source-extraction','discovery-candidates','support-ranking',
                          'source-span-selection','direct-ground-selection','argument-audit'):
                self.assertIn(stage,SyntheticRunner.stages)
            self.assertTrue(any(s.startswith('core-SS-') for s in SyntheticRunner.stages))
            self.assertNotIn('member-extraction',SyntheticRunner.stages)
            for q in p.read_json(d/'selected-queue.json'):self.assertEqual(len(q['sources']),6)

    def test_failed_audit_keeps_fresh_pipeline_unapproved_and_empty(self):
        with TemporaryDirectory() as tmp:
            r,d=self.run_synthetic(tmp,True)
            self.assertEqual(r['screened_inputs'],0)
            self.assertTrue(all(o['state']=='argument_audit_failed' for o in r['outcomes']))

    def test_qa_reserve_is_enforced_before_calls_and_candidate_slots(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=existing.fixture()
            plan={'limits':deepcopy(p.base.LIMITS),'expires_at':fixture['expires_at'],
                  'classifier':fixture['model'],'documents':[]}
            write(root/'plan.json',plan)
            budget=Mock();budget.summary.return_value={'remaining_seconds':p.QA_RESERVE_SECONDS+53}
            runner=p.Runner(root,plan,budget)
            self.assertEqual(runner.timeout(90),50)
            budget.summary.return_value={'remaining_seconds':p.QA_RESERVE_SECONDS+3}
            with self.assertRaises(TimeoutError):runner.timeout(90)
            budget.summary.return_value={'remaining_seconds':p.QA_RESERVE_SECONDS+599}
            outcomes,_,compiled=p.complete(root,plan,runner,[{'id':'unprocessed','sources':{'a':'text'}}])
            self.assertEqual(outcomes,[{'id':'unprocessed','state':'unprocessed_preparation_budget'}])
            self.assertEqual(compiled['profiles'],[])


if __name__=='__main__':unittest.main()
