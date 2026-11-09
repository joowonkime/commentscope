"""Unknown downstream work cannot turn a partial estimate into full admission."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

from commentscope.factory import cost_planning as c
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.storage import write_json_exclusive as write
from tools import plan_factory_cost as tool
from test_openrouter import deployment
from commentscope.providers import remote_verification as remote


def cost_workload():
    return {'version':c.VERSION,'goal':'mvp','counts':dict.fromkeys(c.STAGES,100),
            'assumptions':['Synthetic finite request envelope; not a real model quality result.'],
            'multiplier':'1.25','headroom_usd':'0.15'}


def cost_profile(plan):
    return {'artifact_kind':c.PROFILE,'origin':'authored synthetic cost fixture',
        'stages':{s:{'calls':2,'cost_usd':'0.00002','maximum_cost_usd':'0.00001',
            'deployment_sha256':digest(c.deployment(plan,s))} for s in c.STAGES}}


class CostPlanningTests(unittest.TestCase):
    def setUp(self):
        self.plan={'scope_ids':[str(i) for i in range(6)],'deployment':deployment(),
                   'verification_deployment':remote.SOL,'embedding_deployment':remote.EMBEDDING}
        self.candidates=[{'id':'a','nominees':{'0':'hash','1':'hash','2':'hash'}},
                         {'id':'b','nominees':{'3':'hash','4':'hash','5':'hash'}}]
        self.work=cost_workload();self.profile=cost_profile(self.plan)

    def estimate(self,**kwargs):
        return c.estimate(self.plan,self.candidates,self.work['counts'],[self.profile],
                          available_usd=kwargs.pop('available_usd','1.5'),**kwargs)

    def test_complete_estimate_is_not_financial_semantic_or_completion_approval(self):
        r=self.estimate();self.assertTrue(r['estimated_feasible'])
        self.assertFalse(r['financial_authorization']);self.assertFalse(r['semantic_approval'])
        self.assertFalse(r['completion_guaranteed']);self.assertEqual(r['unknown_stages'],[])

    def test_unknown_count_or_unit_keeps_total_unknown_without_losing_known_cost(self):
        for stage in ('argument-dependencies','facts','runtime'):
            with self.subTest(stage=stage):
                self.work=cost_workload();self.work['counts'][stage]=None
                r=self.estimate();self.assertIsNone(r['estimated_remaining_usd'])
                self.assertFalse(r['estimated_feasible']);self.assertGreater(Decimal(r['known_remaining_estimate_usd']),0)
                self.assertIn(stage,r['unknown_stages'])
        self.work=cost_workload();self.profile['stages'].pop('argument-dependencies')
        self.assertIn('argument-dependencies',self.estimate()['unknown_stages'])

    def test_model_changes_and_missing_stages_cannot_reuse_a_cost_reference_silently(self):
        self.profile['stages']['runtime']['deployment_sha256']='other'
        self.assertIn('runtime',self.estimate()['unknown_stages'])
        del self.work['counts']['facts']
        with self.assertRaises(c.CostPlanError):self.estimate()

    def test_existing_usage_safety_margin_and_headroom_are_all_applied(self):
        r=self.estimate(completed={'source-context':20})
        self.assertEqual(next(s for s in r['stages'] if s['stage']=='source-context')['remaining_calls'],80)
        self.assertFalse(self.estimate(available_usd='0.15')['estimated_feasible'])
        expected=Decimal(r['estimated_remaining_usd'])*Decimal('1.25')+Decimal('0.15')
        self.assertEqual(Decimal(r['required_with_margin_usd']),expected)

    def test_shared96_has480_pairs_and_many_nominees_do_not_disappear(self):
        ids=[str(i) for i in range(96)]
        cs=[{'id':str(i),'nominees':{ids[i]:'hash'}} for i in range(5)]
        self.assertEqual(c.pair_schedule(ids,cs)['exact_total'],480)
        cs=[{'id':str(i),'nominees':{'0':'hash'}} for i in range(8)]
        self.assertEqual(c.pair_schedule(self.plan['scope_ids'],cs)['total_upper_bound'],38)
        self.assertIsNone(c.pair_schedule(self.plan['scope_ids'],cs)['exact_total'])

    def test_underplanned_pairs_or_no_agent_runtime_budget_is_refused(self):
        for stage,value in (('membership-raw',11),('runtime',0),('argument-node-metadata',0)):
            self.work=cost_workload();self.work['counts'][stage]=value
            with self.subTest(stage=stage):self.assertIn('stage_cap_too_small:'+stage,self.estimate()['issues'])

    def test_nonfinite_negative_and_boolean_values_are_refused(self):
        for value in ('NaN','Infinity','-1',True):
            with self.subTest(value=value),self.assertRaises(c.CostPlanError):self.estimate(available_usd=value)
        self.work['counts']['runtime']=True
        with self.assertRaises(c.CostPlanError):self.estimate()

    def test_proposals_aliased_to_core_are_not_misreported_as_core_validation(self):
        self.assertEqual(c.canonical('verification-core-'+'a'*20,{'data':{'ORIGINALS':[]}}),'shared-discovery')
        self.assertEqual(c.canonical('verification-core-'+'a'*20,{'data':{'CANDIDATE':{}}}),'core')
        self.assertEqual(c.canonical('generation-runtime'),'runtime')

    def test_same_checkpoint_is_free_but_new_request_and_independent_stage_consume_caps(self):
        caps=dict.fromkeys(c.STAGES,1);limits=c.CallLimits(caps)
        stage='verification-membership-initial-raw-'+'a'*20;req={'data':'same original'}
        limits.admit(stage,req);limits.admit(stage,deepcopy(req))
        self.assertEqual(limits.used['membership-raw'],1)
        with self.assertRaises(c.CostPlanError):limits.admit(stage,{'data':'different original'})
        limits.admit('verification-raw-own-evidence-'+'a'*20,req)
        self.assertEqual(limits.used['raw-own-evidence'],1)
        restarted=c.CallLimits(caps,[(stage,req)])
        with self.assertRaises(c.CostPlanError):restarted.admit(stage,{'data':'different original'})


class CostReviewTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='runs',prefix='full-cost-test-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.run=self.root/'run'
        self.plan={'scope_ids':[str(i) for i in range(6)],'deployment':deployment(),
            'verification_deployment':remote.SOL,'embedding_deployment':remote.EMBEDDING,
            'spend_policy':{'ledger':str(self.root/'money.sqlite'),'account_id':'synthetic',
                'maximum_usd':'50','opening_charge_usd':'10'},
            'spend_scope_sha256':'a'*64,'maximum_cost_usd':'8','subcap_usd':'1.50','opening_scope_charge_usd':'0'}
        write(self.run/'plan.json',self.plan)
        write(self.run/'artifacts/initial-candidates.json',[{'id':'a','nominees':{'0':'hash'}},{'id':'b','nominees':{'1':'hash'}}])
        write(self.run/'proposal-ready.json',{'plan_sha256':sha(self.run/'plan.json'),
            'candidates_sha256':sha(self.run/'artifacts/initial-candidates.json')})
        self.work=self.root/'work.json';write(self.work,cost_workload())
        self.profile=self.root/'profile.json';write(self.profile,cost_profile(self.plan))
        self.reference_verifier=tool.verify_profile
        stub=patch.object(tool,'verify_profile');stub.start();self.addCleanup(stub.stop)

    def review(self):return tool.prepare_review(self.run,self.work,[self.profile])

    def test_missing_review_and_unknown_downstream_work_refuse_full_execution(self):
        with self.assertRaises(c.CostPlanError):tool.require_review(self.run,self.plan)
        work=read_json(self.work);work['counts']['argument-dependencies']=None;self.work.write_text(json.dumps(work))
        review=self.review();self.assertFalse(review['preview']['estimated_feasible'])
        with self.assertRaises(c.CostPlanError):tool.require_review(self.run,self.plan)

    def test_rejected_estimate_can_be_corrected_without_repaying_proposals_or_resetting_money(self):
        work=read_json(self.work);work['counts']['facts']=None;self.work.write_text(json.dumps(work))
        rejected=self.review();self.assertFalse(rejected['preview']['estimated_feasible'])
        self.assertFalse((self.run/'cost-preflight.json').exists())
        self.assertTrue(list(self.run.glob('cost-preflight-rejected-*.json')))
        self.work.write_text(json.dumps(cost_workload()));accepted=self.review()
        self.assertTrue(accepted['preview']['estimated_feasible']);tool.require_review(self.run,self.plan)
        self.assertEqual(tool.available(self.plan),Decimal('1.50'))
        self.assertFalse((self.run/'calls').exists())

    def test_later_scope_spend_reduces_remaining_money_without_a_new_scope(self):
        self.review();tool.require_review(self.run,self.plan)
        p=self.plan['spend_policy'];money=SpendLedger(p['ledger'],p['account_id'],maximum_usd='50',opening_charge_usd='10')
        call=money.reserve('a'*64,'b'*64,'1.4',run_limit_usd='8',key_remaining_usd='40');money.finish(call,'1.4')
        with self.assertRaises(c.CostPlanError):tool.require_review(self.run,self.plan)
        self.assertEqual(money.summary()['charged_usd'],'11.4')

    def test_changed_candidates_profile_or_embedded_workload_is_not_admitted(self):
        self.review();report_path=self.run/'cost-preflight.json';report=read_json(report_path)
        report['workload']['counts']['runtime']=999
        report['integrity_sha256']=digest({k:v for k,v in report.items() if k!='integrity_sha256'})
        report_path.write_text(__import__('json').dumps(report))
        with self.assertRaises(c.CostPlanError):tool.require_review(self.run,self.plan)

    def test_changed_candidate_file_and_cost_profile_are_refused(self):
        self.review()
        for path in (self.run/'artifacts/initial-candidates.json',self.profile):
            original=path.read_text();path.write_text(original+' ')
            with self.subTest(path=path.name),self.assertRaises(c.CostPlanError):tool.require_review(self.run,self.plan)
            path.write_text(original)

    def test_orphan_checkpoint_blocks_before_any_retry(self):
        self.review();write(self.run/'checkpoints/orphan.intent.json',{'pending':True})
        with self.assertRaisesRegex(c.CostPlanError,'Pending'):tool.require_review(self.run,self.plan)

    def archived_response(self):
        source=self.run/'frozen-code/synthetic.py';source.parent.mkdir(parents=True,exist_ok=True)
        source.write_text('# Synthetic archived source\n')
        self.plan['code_sha256']={'synthetic.py':sha(source)}
        (self.run/'plan.json').write_text(json.dumps(self.plan))
        write(self.run/'frozen.json',{'plan_sha256':sha(self.run/'plan.json')})
        req={'system':'Synthetic source observation','data':{},'schema':{},'max_tokens':20}
        stage='verification-source-world-'+'a'*20
        request_file=self.run/'calls'/('0001-'+stage+'.request.json')
        write(request_file,{'plan_sha256':sha(self.run/'plan.json'),'request_sha256':digest(req),'request':req})
        result={'usage':{'cost':0.001},'transport':{'provider_response':{'model':remote.SOL['model'],
            'provider':'OpenAI','usage':{'cost':0.001,'prompt_tokens':100,'completion_tokens':10,
            'prompt_tokens_details':{'cached_tokens':80,'cache_write_tokens':10}}}}}
        result_file=request_file.with_name(request_file.name.replace('.request.json','.result.json'));write(result_file,result)
        identity={'plan_sha256':sha(self.run/'plan.json'),'stage':stage,'request_sha256':digest(req)}
        write(self.run/'checkpoints/original.intent.json',identity)
        write(self.run/'checkpoints/original.result.json',{'identity':identity,'result':result,'result_sha256':digest(result)})
        return request_file,result_file

    def test_audit_binds_real_receipt_cost_cache_and_archive_without_any_model_call(self):
        request_file,_=self.archived_response()
        write(request_file.with_name('0002-verification-source-world-'+ 'b'*20+'.request.json'),
            {'plan_sha256':sha(self.run/'plan.json'),'request_sha256':digest({'pending':True}),'request':{'pending':True}})
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network permitted')):
            report=tool.audit(self.run)
        self.assertEqual(report['completed_responses'],1);self.assertEqual(report['pending_requests'],1)
        self.assertEqual(report['total_confirmed_usd'],'0.001')
        self.assertEqual(report['stages']['source-world']['cached_prompt_tokens'],80)
        self.assertEqual(report['stages']['source-world']['cache_detail_responses'],1)
        self.assertFalse(report['semantic_input_reuse']);self.assertEqual(report['new_model_calls'],0)
        self.reference_verifier(report)
        changed=deepcopy(report);changed['stages']['source-world']['cost_usd']='0.00001'
        with self.assertRaises(c.CostPlanError):self.reference_verifier(changed)

    def test_changed_cost_or_archived_source_is_rejected(self):
        _,result_file=self.archived_response();result=read_json(result_file)
        result['usage']['cost']=0.002;result_file.write_text(json.dumps(result))
        with self.assertRaises(c.CostPlanError):tool.audit(self.run)
        (self.run/'frozen-code/synthetic.py').write_text('# Changed original\n')
        with self.assertRaises(c.CostPlanError):tool.audit(self.run)

    def test_stage_limit_refuses_before_actual_remote_and_embedding_dispatch(self):
        from tools import shared_factory_trial as trial
        session=trial.Session.__new__(trial.Session);session.plan=self.plan
        session.cost_limits=c.CallLimits(dict.fromkeys(c.STAGES,0))
        req={'system':'Source','data':{},'schema':{},'max_tokens':20}
        with patch.object(trial.executor.RemoteSession,'call') as parent:
            with self.assertRaises(c.CostPlanError):session.call('source-world-'+'a'*20,req)
            parent.assert_not_called()
        with patch.object(trial.executor.RemoteSession,'embed') as parent:
            with self.assertRaises(c.CostPlanError):session.embed('sources',{'s':'Full original'})
            parent.assert_not_called()

    def test_inherited_trial_opening_cannot_be_refunded_by_empty_history(self):
        self.plan['opening_scope_charge_usd']='1'
        with self.assertRaisesRegex(c.CostPlanError,'history'):tool.available(self.plan)

    def test_template_keeps_unknown_downstream_costs_and_binds_the_target_version(self):
        path=self.run/'artifacts/initial-candidates.json';rows=read_json(path)
        for row in rows:row['text']='Synthetic cost candidate '+row['id']
        path.write_text(json.dumps(rows))
        work=tool.template(self.run)
        self.assertEqual(work['counts']['membership-raw'],12)
        self.assertIsNone(work['counts']['argument-dependencies'])
        self.assertIsNone(work['counts']['raw-own-evidence'])
        self.assertEqual(work['candidate_sha256'],sha(path))
        work['target_plan_sha256']='other'
        with self.assertRaises(c.CostPlanError):tool.calculate(self.run,work,[cost_profile(self.plan)],'1.5')


if __name__=='__main__':unittest.main()
