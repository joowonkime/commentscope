from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from commentscope.factory import span_typing, bounded_span_typing
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.product_evaluation import execution_state
from commentscope.providers.local_nli import MODEL, REVISION
from commentscope.storage import write_json_exclusive as write
from experiments import span_integration_probe as probe
from experiments.fresh_grounded_pipeline import source_rows
import test_fresh_grounded_pipeline as fresh_tests


class ScenarioRunner:
    def __init__(self,directory,plan,budget):
        self.directory=directory;self.plan=plan;self.clock=time.monotonic
        self.started=self.clock();self.plan_sha=sha(directory/'plan.json');self.seq=0

    def call(self,stage,req,**kwargs):
        self.seq+=1
        if stage=='typing':
            # Synthetic, authored outputs; no claim of model behavior.
            if self.plan['typing_version']==bounded_span_typing.VERSION:
                prefix,source=next(iter(req['data']['MEMBER_SOURCES'].items()));sid=source['source_id']
                detail={'range_id':prefix+':1:1','kind':'normative_preference','required_fact':False}
                if self.plan.get('synthetic_case')=='bad_range' and sid.startswith('s0'):detail['range_id']='missing'
                if self.plan.get('synthetic_case')=='required_fact' and sid.startswith('s0'):
                    detail.update(kind='empirical_description',required_fact=True)
                value={'status':'classified','kind':'normative_preference','details':[detail]}
                return {'output':value,'raw':json.dumps(value),'errors':[]}
            sid,parts=next(iter(req['data']['MEMBER_SOURCES'].items()));part=parts[1]
            detail={'id':'D1','kind':'normative_preference','source_id':sid,'first':part['id'],'last':part['id']}
            required=[]
            if self.plan.get('synthetic_case')=='bad_range' and sid.startswith('s0'):
                detail['first']='not-a-source-range'
            if self.plan.get('synthetic_case')=='required_fact' and sid.startswith('s0'):
                detail['kind']='empirical_description';required=['D1']
            value={'status':'classified','kind':'normative_preference','details':[detail],'required_fact_ids':required}
        elif stage=='detail':value={'verdict':'supported','reason':'Synthetic fixture only'}
        elif stage=='facts':
            if any(c['evidence'] for c in req['data']['cases']):raise AssertionError('Fixture expects no evidence')
            return {'metadata':{'model':MODEL,'revision':REVISION,'threshold':.8,'local_files_only':True,
                                'id2label':{'0':'entailment','1':'neutral','2':'contradiction'}},
                    'results':[{'id':c['id'],'pairs':[],'state':'unassessed','supporting_ids':[],'refuting_ids':[]}
                               for c in req['data']['cases']]}
        else:raise AssertionError(stage)
        return {'output':value,'raw':json.dumps(value),'errors':[]}


class SpanIntegrationTests(unittest.TestCase):
    def fixture(self):
        policy=fresh_tests.FreshGroundedPipelineTests().policy();proposals=[]
        for i in range(3):
            core=['Safety reviews should be required.','Safety reviews should be voluntary.','Reviews should be public.'][i]
            claim={'id':'C','text':core,'kind':'fact','scope':{'entity':'','time':'','conditions':''},'requires':[]}
            sources={f's{i}{j}':core+' I value prevention. '+f'Context {i}{j}.' for j in range(3)}
            proposals.append({'id':f'C{i}','claims':{'C':claim},'sources':sources})
        rows=source_rows(proposals,policy)
        return {'proposals':proposals,'rows':rows,'actual':{r['id']:'supported' for r in rows}},policy

    def test_freezes_all_candidates_and_bound_requests_without_mutation(self):
        selected,policy=self.fixture();before=deepcopy(selected)
        requests,maximum=probe.frozen_typing(selected,policy)
        self.assertEqual([r['candidate_id'] for r in requests],['C0','C1','C2'])
        self.assertEqual(maximum,18);self.assertEqual(selected,before)
        self.assertTrue(all(len(r['request']['data']['MEMBER_SOURCES'])==3 for r in requests))

    def test_source_target_request_and_inventory_tampering_fail(self):
        selected,policy=self.fixture()
        def mutate(s,field):
            if field=='text':s['rows'][0]['text']='Changed source'
            elif field=='claim':s['rows'][0]['claim']={**s['rows'][0]['claim'],'text':'Changed claim'}
            elif field=='hash':s['rows'][0]['request_sha256']='0'*64
            elif field=='decision':s['actual'].pop(s['rows'][0]['id'])
            elif field=='duplicate':s['rows'].append(deepcopy(s['rows'][0]))
            elif field=='support':s['actual'][s['rows'][0]['id']]='partial'
        for field in ('text','claim','hash','decision','duplicate','support'):
            with self.subTest(field=field):
                s=deepcopy(selected);mutate(s,field)
                with self.assertRaises(ValueError):probe.frozen_typing(s,policy)

    def execute_fixture(self,directory,case='normal',typer=span_typing):
        selected,policy=self.fixture();requests,maximum=probe.frozen_typing(selected,policy,typer=typer)
        info={'path':'synthetic','sha256':'fixture'}
        plan={'artifact_kind':probe.VERSION,'typing_version':typer.VERSION,'expires_at':'2099-01-01T00:00:00Z',
              'inputs':{},'code_sha256':{},'model_files':{},'selection':selected,'typing_requests':requests,
              'membership_policy':policy,'deployment':{'server':info,'models':{'baseline':info}},
              'budget':{'ledger':str(directory/'unused.sqlite'),'cycle_id':'synthetic'},
              'classifier':{'name':MODEL,'revision':REVISION,'weights_sha256':'a'*64,'runtime_sha256':'b'*64},
              'documents':[],'selections':[],'limits':{'analysis_seconds':900,'call_seconds':90,'fact_seconds':240,'detail_relations':maximum},
              'evaluation':execution_state({'development_gate_passed':False,'all_relations_complete':False},'product_diagnostic'),
              'synthetic_case':case}
        write(directory/'plan.json',plan);budget=Mock();budget.summary.return_value={'charged_seconds':0}
        with patch.object(probe,'Runner',ScenarioRunner),patch.object(probe,'InferenceBudget',return_value=budget), \
             patch.object(probe,'file_hash',return_value='fixture'),patch.object(probe,'owned_server'):
            probe.execute(directory)
        return read_json(directory/'completed.json'),read_json(directory/'bundle.json'),read_json(directory/'compiled.json')

    def test_all_three_synthetic_candidates_compile_but_are_not_quality_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,bundle,compiled=self.execute_fixture(Path(tmp))
        self.assertEqual(report['selected_candidates'],3);self.assertEqual(report['screened_inputs'],3)
        self.assertEqual(report['detail_relations'],9);self.assertEqual(report['fact_claims'],0)
        self.assertFalse(report['fresh_analysis']);self.assertFalse(report['quality_gate_passed'])
        self.assertEqual(report['qualified_agents'],0)
        self.assertFalse(report['evaluation']['relation_target_met'])
        self.assertTrue(all(p['model_core_support_count']==3 for p in compiled['profiles']))

    def test_bad_range_defers_candidate_without_repair_or_discarding_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,bundle,compiled=self.execute_fixture(Path(tmp),'bad_range')
        self.assertEqual(report['selected_candidates'],3);self.assertEqual(report['screened_inputs'],2)
        self.assertEqual(report['typing_deferred'],[{'id':'C0','reason':'typing_contract'}])

    def test_unverified_required_fact_is_preserved_and_defers_dependent_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,bundle,compiled=self.execute_fixture(Path(tmp),'required_fact')
        self.assertEqual(report['typed_candidates'],3);self.assertEqual(report['fact_claims'],1)
        self.assertEqual(report['screened_inputs'],2)
        core=next(c for c in bundle['claims'] if c['id']=='C0:C')
        self.assertEqual(core['requires'],['C0:R1'])
        self.assertEqual(compiled['claim_decisions']['C0:R1']['fact_state'],'unassessed')
        self.assertNotIn('C0',[p['candidate_id'] for p in compiled['profiles']])

    def test_bounded_contract_keeps_all_candidates_and_fact_deferral_policy(self):
        for case,count in [('normal',3),('bad_range',2),('required_fact',2)]:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                report,bundle,compiled=self.execute_fixture(Path(tmp),case,bounded_span_typing)
            self.assertEqual(report['selected_candidates'],3);self.assertEqual(report['screened_inputs'],count)
            self.assertEqual(report['qualified_agents'],0)
            if case=='required_fact':
                self.assertEqual(next(c for c in bundle['claims'] if c['id']=='C0:C')['requires'],['C0:R1'])
                self.assertEqual(compiled['claim_decisions']['C0:R1']['fact_state'],'unassessed')
