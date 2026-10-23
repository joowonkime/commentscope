from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from experiments import fresh_product_pipeline as p
from experiments.grounding_contract_demo import fixture
from commentscope.factory import source_first
from commentscope.storage import write_json_exclusive as write
from test_source_first import output
import test_fresh_grounded_pipeline as fresh_tests


class ScenarioRunner:
    def __init__(self, directory, plan, budget):
        self.directory=directory; self.plan=plan; self.seq=0; self.clock=time.monotonic
        self.started=self.clock(); self.plan_sha=p.sha(directory/'plan.json')

    def timeout(self, maximum): return maximum

    def call(self, stage, req, **kwargs):
        self.seq += 1
        if stage == 'embedding':
            positions=['Safety reviews should be required.','Safety reviews should be voluntary.']
            raw={'sources':{f's{i}{j}':{'text':t+f' Additional context {j}.'} for i,t in enumerate(positions) for j in range(3)},
                 'clusters':[{'id':f'G{i}','members':[f's{i}{j}' for j in range(3)]} for i in range(2)]}
            write(req['data']['output'],raw); return {'sha256':p.sha(req['data']['output'])}
        if stage == 'source-extraction':
            text=req['data']['TARGET'].split(' Additional')[0]; value=output(text,stance='support' if 'required' in text else 'oppose')
        elif stage == 'unit-candidates':
            units=req['data']['units']; vectors=[[1.,0.] if 'required' in u['claim'] else [0.,1.] for u in units]
            return {**source_first.candidates(units,vectors,req['data']['sources']),
                    'unit_ids':[u['claim_id'] for u in units],
                    'embedding_texts':[source_first.embedding_text(u) for u in units], 'vectors':vectors}
        elif stage in ('target-ranking','neighborhood-ranking'):
            return {'rows':[{'id':r['id'],'pair_sha256':p.digest(r),'errors':[],
                    'scores':{'entailment':.98,'neutral':.01,'contradiction':.01}} for r in req['data']['pairs']]}
        elif stage in ('core-baseline','core-alternative','core-neighborhood'): value={'verdict':'supported','reason':'Synthetic test only.'}
        elif stage == 'core-kind': value={'kind':'value'}
        elif stage == 'argument-selection': value={'status':'selected','node_ids':[],'essential_node_ids':[]}
        else: raise AssertionError(stage)
        return {'output':value,'raw':json.dumps(value),'errors':[]}


class FreshProductPipelineTests(unittest.TestCase):
    def selection(self, pid, texts, *, core='Safety reviews should be required.'):
        claim={'id':'C','text':core,'kind':'fact','scope':{'entity':'general','time':'','conditions':''},'requires':[]}
        proposal={'id':pid,'sources':texts,'claims':{'C':claim}}
        rows=p.source_rows([proposal],fresh_tests.FreshGroundedPipelineTests().policy())
        return {'proposals':[proposal],'rows':rows,'actual':{r['id']:'supported' for r in rows}}

    def test_identical_target_merges_canonical_votes_not_people_or_semantics(self):
        left=self.selection('SC1',{s:'Safety reviews should be required.' for s in 'abc'})
        right=self.selection('SN1',{s:'Safety reviews should be required.' for s in 'bcd'})
        merged=p.combine(left,right)
        self.assertEqual(len(merged['proposals']),1); self.assertEqual(len(merged['rows']),4)
        self.assertEqual(merged['proposals'][0]['retrieval_candidate_ids'],['SC1','SN1'])
        right=self.selection('SN1',{s:'Safety reviews should be voluntary.' for s in 'def'},core='Safety reviews should be voluntary.')
        self.assertEqual(len(p.combine(left,right)['proposals']),2)

    def test_conflicting_duplicate_cannot_vote_or_be_retried(self):
        left=self.selection('SC1',{s:'Same source.' for s in 'abc'})
        right=self.selection('SN1',{s:'Same source.' for s in 'abc'})
        right['actual'][right['rows'][0]['id']]='partial'
        with self.assertRaises(ValueError): p.combine(left,right)
        runner=Mock(); runner.seq=7; runner.call.return_value={'errors':['timeout'],'output':None}
        memo=p.Relations(runner); row=left['rows'][0]
        self.assertEqual(memo.judge([row],'core-baseline')[row['id']],'error')
        self.assertEqual(memo.judge([row],'core-neighborhood')[row['id']],'error')
        self.assertEqual(runner.call.call_count,1); self.assertTrue(memo.trace[1]['reused_within_run'])

    def test_incomplete_population_and_budget_are_explicit(self):
        left=self.selection('SC1',{s:'A source.' for s in 'abc'})
        right=self.selection('SN1',{s:'Another source.' for s in 'def'},core='Reviews should be voluntary.')
        result=p.combine(left,right,limit=1)
        self.assertEqual(len(result['proposals']),1)
        self.assertEqual(result['deferred'][0]['reason'],'profile_capacity_budget')
        bad=deepcopy(right);bad['rows']=bad['rows'][:-1]
        with self.assertRaises(ValueError):p.combine(left,bad)
        with self.assertRaises(ValueError):p.combine(left,right,limit=0)

    def test_fresh_end_to_end_uses_no_historical_outputs_and_never_approves_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp); f=fixture()
            d={'models':{'baseline':{'path':'synthetic','sha256':'fixture'}},'server':{'path':'synthetic','sha256':'fixture'},'runtime':{}}
            measurement={'development_gate_passed':False,'all_relations_complete':False,'observed_evaluation':14,'planned_evaluation':100}
            plan={'artifact_kind':p.VERSION,'snapshot':str(directory/'snapshot.json'),'expires_at':f['expires_at'],
                  'inputs':{},'code_sha256':{},'model_files':{},'limits':deepcopy(p.LIMITS),
                  'retrieval_limits':deepcopy(p.semantic_neighborhood.LIMITS),'profile_extra_tokens':768,
                  'evaluation':p.product_evaluation.execution_state(measurement,'product_diagnostic'),
                  'membership_policy':fresh_tests.FreshGroundedPipelineTests().policy(),
                  'deployments':{k:deepcopy(d) for k in ('extraction','membership','profile')},
                  'budget':{'ledger':str(directory/'unused.sqlite'),'cycle_id':'synthetic'},
                  'classifier':f['model'],'documents':[],'selections':[]}
            write(directory/'plan.json',plan);write(directory/'snapshot.json',{'synthetic':True})
            budget=Mock();budget.summary.return_value={'calls':[],'charged_seconds':0}
            with patch.object(p,'Runner',ScenarioRunner),patch.object(p,'file_hash',return_value='fixture'), \
                 patch.object(p,'InferenceBudget',return_value=budget),patch.object(p,'owned_server'):
                p.execute(directory)
            report=p.read_json(directory/'completed.json')
            self.assertEqual(report['screened_inputs'],2);self.assertEqual(report['qualified_agents'],0)
            self.assertFalse(report['quality_gate_passed']);self.assertTrue(report['fresh_analysis'])
            self.assertEqual(report['coverage']['model_calls'],6)
            self.assertEqual(report['relation_reuse_within_run'],6)
            selection=p.read_json(directory/'selection.json')
            self.assertEqual(len(selection['proposals']),2)
            self.assertEqual(len(selection['rows']),6)
            self.assertTrue(all(len(x['retrieval_candidate_ids'])==2 for x in selection['proposals']))


if __name__ == '__main__': unittest.main()
