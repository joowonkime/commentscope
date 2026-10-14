from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from commentscope.factory import product_evaluation, source_first
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import fresh_grounded_pipeline as pipeline
from experiments.grounding_contract_demo import fixture
import test_fresh_grounded_pipeline as fresh_tests
from test_source_first import output


class ScenarioRunner:
    def __init__(self, directory, plan, budget):
        self.directory=directory; self.plan=plan; self.clock=time.monotonic
        self.started=self.clock(); self.plan_sha=sha(directory/'plan.json'); self.seq=0

    def timeout(self, maximum): return maximum

    def call(self, stage, req, **kwargs):
        self.seq+=1
        if stage=='embedding':
            positions=['Safety reviews should be required.', 'Safety reviews should be voluntary.']
            raw={'sources':{f's{i}{j}':{'text':text+f' Additional context {j}.'} for i,text in enumerate(positions) for j in range(3)},
                 'clusters':[{'id':f'C{i}','members':[f's{i}{j}' for j in range(3)]} for i in range(2)]}
            write(Path(req['data']['output']),raw)
            return {'sha256':sha(req['data']['output'])}
        if stage=='source-extraction':
            text=req['data']['TARGET'].split(' Additional')[0]
            value=output(text,stance='support' if 'required' in text else 'oppose')
        elif stage=='unit-candidates':
            units=req['data']['units']
            return source_first.candidates(units,[[1.,0.] for _ in units],req['data']['sources'])
        elif stage=='membership': value={'verdict':'supported','reason':'Synthetic fixture only.'}
        elif stage=='typing': value={'status':'classified','kind':'normative_preference','details':[],'required_fact_ids':[]}
        else: raise AssertionError(stage)
        return {'output':value,'raw':json.dumps(value),'errors':[]}


class SourceFirstPipelineTests(unittest.TestCase):
    def test_complete_synthetic_diagnostic_never_approves_real_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp); f=fixture()
            deployment={'models':{'baseline':{'path':'synthetic','sha256':'fixture'}},'server':{'path':'synthetic','sha256':'fixture'},'runtime':{}}
            measurement={'development_gate_passed':False,'all_relations_complete':False,'observed_evaluation':14,'planned_evaluation':100}
            evaluation=product_evaluation.execution_state(measurement,'product_diagnostic')
            plan={'artifact_kind':'fresh-grounded-pipeline-0.3','snapshot':str(directory/'snapshot.json'),
                  'expires_at':f['expires_at'],'evaluation':evaluation,'candidate_algorithm':source_first.VERSION,
                  'membership_policy':fresh_tests.FreshGroundedPipelineTests().policy(),'inputs':{},'code_sha256':{},'model_files':{},
                  'deployments':{'proposal':deepcopy(deployment),'membership':deepcopy(deployment)},
                  'budget':{'ledger':str(directory/'unused.sqlite'),'cycle_id':'synthetic'},
                  'classifier':f['model'],'documents':[],'selections':[],
                  'limits':{'analysis_seconds':3600,'groups':20,'call_seconds':90,'embedding_seconds':300,
                            'fact_seconds':240,'source_analysis_seconds':1800,'source_request_bytes':27000,'candidate_threshold':.45}}
            write(directory/'plan.json',plan);write(directory/'snapshot.json',{'synthetic':True})
            budget=Mock();budget.summary.return_value={'calls':[],'charged_seconds':0}
            with patch.object(pipeline,'Runner',ScenarioRunner),patch.object(pipeline,'file_hash',return_value='fixture'), \
                 patch.object(pipeline,'InferenceBudget',return_value=budget),patch.object(pipeline,'owned_server'):
                pipeline.execute(directory)
            report=read_json(directory/'completed.json')
            self.assertEqual(report['screened_inputs'],2);self.assertEqual(report['qualified_agents'],0)
            self.assertFalse(report['quality_gate_passed']);self.assertEqual(report['evaluation'],evaluation)
            self.assertEqual(report['coverage']['scheduled'],6)
            self.assertEqual(report['coverage']['model_calls'],6)
            compiled=read_json(directory/'compiled.json')
            self.assertEqual([p['model_core_support_count'] for p in compiled['profiles']],[3,3])
            self.assertTrue(all(e['kind']=='value' for p in compiled['profiles'] for e in p['prompt_entries']))
            self.assertFalse((directory/'failed.json').exists())
