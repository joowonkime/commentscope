from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from experiments.fresh_grounded_pipeline import Runner, proposals_from_groups, source_rows, classify, prepare
from experiments.grounding_contract_demo import fixture
from commentscope.factory import grounded_factory
from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.providers.budget import BudgetExhausted
from commentscope.storage import write_json_exclusive as write


class FakeRunner:
    def __init__(self):self.calls=[]
    def call(self,stage,req):
        self.calls.append((stage,req))
        if stage=='proposal':
            sid,text=next(iter(req['data']['COMMENTS'].items()))
            value={'decision':'candidate','text':text,'anchor_id':sid,'quote':text}
        elif stage=='typing':
            value={'status':'classified','kind':'normative_preference','details':[],'required_fact_ids':[]}
        else:raise AssertionError('Unexpected stage')
        return {'output':value,'errors':[]}


class FreshGroundedPipelineTests(unittest.TestCase):
    def raw(self):
        positions=['Safety reviews should be required.','Decisions should be voluntary.']
        return {'clusters':[{'id':f'C{i}','members':[f's{i}{j}' for j in range(3)]} for i in range(2)],
                'sources':{f's{i}{j}':{'text':text} for i,text in enumerate(positions) for j in range(3)}}

    def test_synthetic_pipeline_needs_no_runtime_labels(self):
        runner=FakeRunner(); proposals,deferred=proposals_from_groups(self.raw(),runner)
        self.assertFalse(deferred)
        rows=source_rows(proposals,512)
        self.assertEqual([r['candidate_id'] for r in rows],['C0','C1']*3)
        actual={r['id']:'supported' for r in rows}
        typed,derived,deferred=classify(proposals,rows,actual,runner)
        self.assertFalse(deferred)
        self.assertTrue(all(r['request']['max_tokens']==512 for r in derived))
        self.assertTrue(all(r['claim']['kind']=='value' for r in derived))
        self.assertEqual(grounded_factory.detail_requests(typed,derived,actual),[])
        f=fixture()
        bundle=grounded_factory.bundle(typed,derived,actual,[],{},expires_at=f['expires_at'],model=f['model'])
        compiled=compile_inputs(bundle)
        self.assertEqual(len(compiled['profiles']),2)
        self.assertFalse(compiled['quality_gate_passed'])
        self.assertTrue(all(p['model_core_support_count']==3 for p in compiled['profiles']))

    def test_insufficient_support_never_calls_typing(self):
        runner=FakeRunner(); proposals,_=proposals_from_groups(self.raw(),runner)
        rows=source_rows(proposals,180);actual={r['id']:'partial' for r in rows}
        typed,derived,deferred=classify(proposals,rows,actual,runner)
        self.assertEqual(typed,[]);self.assertEqual(derived,[])
        self.assertEqual(len(deferred),2)
        self.assertTrue(all(stage=='proposal' for stage,_ in runner.calls))

    def test_proposal_bad_anchor_is_not_repaired(self):
        runner=Mock()
        runner.call.return_value={'errors':[],'output':{'decision':'candidate','text':'Claim',
                                'anchor_id':'missing','quote':'Claim'}}
        proposals,deferred=proposals_from_groups(self.raw(),runner)
        self.assertEqual(proposals,[]);self.assertEqual(len(deferred),2)

    def test_failed_source_gate_cannot_prepare_trial(self):
        with tempfile.TemporaryDirectory() as tmp,patch('experiments.fresh_grounded_pipeline.checkpoint',return_value={'development_gate_passed':False}):
            out=Path(tmp)/'new'
            with self.assertRaisesRegex(ValueError,'source gate'):
                prepare(out,None,None,None,None,None)
            self.assertFalse(out.exists())

    def runner(self,budget,clock):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=Path(tmp.name);plan={'limits':{'analysis_seconds':10,'call_seconds':90}}
        write(path/'plan.json',plan)
        return Runner(path,plan,budget,clock=clock)

    def test_remaining_analysis_deadline_caps_call(self):
        clock=Mock(side_effect=[100,104,107]); runner=self.runner(Mock(),clock)
        self.assertEqual(runner.timeout(90),3)
        with self.assertRaises(TimeoutError):runner.timeout(90)

    def test_exhausted_cycle_is_not_an_ordinary_model_rejection(self):
        budget=Mock();budget.call.side_effect=BudgetExhausted('exhausted')
        runner=self.runner(budget,lambda:100)
        req={'system':'test','data':{},'schema':{},'max_tokens':1}
        with self.assertRaises(BudgetExhausted):runner.call('membership',req)

    def test_transport_failure_is_recorded_not_repaired(self):
        budget=Mock();budget.call.side_effect=RuntimeError('timeout')
        runner=self.runner(budget,lambda:100)
        req={'system':'test','data':{},'schema':{},'max_tokens':1}
        result=runner.call('membership',req)
        self.assertEqual(result['errors'],['bounded_call_failed'])
        self.assertEqual(budget.call.call_count,1)
