"""Registered pool, cumulative finance and server plan invariants; no paid calls."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
import secrets,time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import threading
from unittest.mock import patch

from tools import prepared_video_trial as t
import test_minimal_pipeline as pipeline_fixture


class PreparedVideoTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(dir='runs',prefix='prepared-video-test-');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();h=pipeline_fixture.MinimalPipelineTests();h.setUp();self.snapshot=h.snapshot
        self.snapshot_file=self.root/'snapshot.json';t.write(self.snapshot_file,self.snapshot.to_dict())
        self.refs=self.root/'references.json';t.write(self.refs,{'documents':[],'selections':[]})
        self.policy_file=self.root/'policy.json'
        self.policy={'account_id':'synthetic-test','ledger':str(self.root/'spend.sqlite'),
            'maximum_usd':'150','opening_charge_usd':'0.1'}
        t.write(self.policy_file,self.policy)
        self.owner_file=self.root/'owner.json'
        self.owner={'maximum_usd':'150','shared_policy_file':str(self.policy_file),
            'shared_policy_sha256':t.sha(self.policy_file),'historical_charges_preserved':True,
            'generation_deployment':{**deepcopy(t.e.remote.SOL),'model':'openai/gpt-5.2'},
            'deadline':'2020-01-01T00:00:00Z'}
        t.write(self.owner_file,self.owner)
        self.money=t.e.ledger(self.policy)
        call=self.money.reserve(t.sha(self.owner_file),'a'*64,'1',run_limit_usd='150',key_remaining_usd='150')
        self.money.finish(call,'0.3')
        self.addCleanup(patch.stopall)
        self.network=[]
        for module,name in [(t.e,'key_metadata'),(t.e,'provider_preflight'),(t.e,'embedding_preflight'),(t.decisions,'preflight')]:
            self.network.append(patch.object(module,name,return_value={'limit':150,'limit_remaining':149}).start())
        patch.object(t.e,'archive_sources').start()

    def prepare(self,name='execution'):
        root=self.root/name
        t.prepare(root,self.snapshot_file,self.refs,self.owner_file,self.policy_file,
            user_request='Synthetic user requests registered video and existing web integration.')
        return root,t.read_json(root/'plan.json')

    def rewrite_plan(self,root,plan):
        (root/'plan.json').write_text(json.dumps(plan))
        (root/'frozen.json').write_text(json.dumps({'plan_sha256':t.sha(root/'plan.json')}))

    def test_entire_pool_and_original_owner_preserved_without_new_calls(self):
        before=self.money.summary();root,plan=self.prepare()
        self.assertEqual(plan['input_comment_count'],6)
        self.assertEqual(plan['scope_ids'],sorted(t.sources(self.snapshot,include_video_context=True)))
        self.assertEqual(plan['spend_scope_sha256'],t.sha(self.owner_file))
        self.assertEqual(self.money.summary(),before)
        self.assertFalse(t.guard(plan)['new_money_owner'])
        self.assertEqual(plan['admission_policy'],t.seed_policy.POLICY)
        self.assertFalse(plan['quality_gate_passed'])

    def test_second_plan_keeps_same_cumulative_owner_and_old_charges(self):
        _,first=self.prepare('first');_,second=self.prepare('second')
        self.assertEqual(first['spend_scope_sha256'],second['spend_scope_sha256'])
        self.assertEqual(self.money.summary(plan_sha256=second['spend_scope_sha256'])['charged_usd'],'0.3')
        self.assertEqual(self.money.summary()['charged_usd'],'0.4')

    def test_historical_financial_model_does_not_override_new_pinned_execution_roles(self):
        before=self.owner_file.read_bytes();owner_sha=t.sha(self.owner_file)
        root,plan=self.prepare()
        self.assertNotEqual(self.owner['generation_deployment'],plan['deployment'])
        self.assertEqual(plan['deployment'],t.e.remote.SOL)
        self.assertEqual(plan['verification_deployment'],t.e.remote.SOL)
        self.assertEqual(plan['membership_deployment'],t.decisions.DEPLOYMENT)
        self.assertEqual(plan['spend_scope_sha256'],owner_sha)
        self.assertEqual(self.owner_file.read_bytes(),before)
        self.assertEqual(self.money.summary(plan_sha256=owner_sha)['charged_usd'],'0.3')
        changed=deepcopy(plan);changed['deployment']=deepcopy(self.owner['generation_deployment'])
        self.rewrite_plan(root,changed)
        with self.assertRaises(ValueError):t.guard(changed)

    def test_constructed_execution_session_keeps_existing_owner_and_costs_nothing(self):
        root,plan=self.prepare();before=self.money.summary()
        session=t.Session(root,plan,t.host_resources.RemoteCallGuard())
        self.assertEqual(session.plan['spend_scope_sha256'],t.sha(self.owner_file))
        self.assertEqual(session.charged(),Decimal('0.3'))
        self.assertEqual(self.money.summary(),before)

    def test_unsettled_cost_blocks_preparation_before_provider_metadata(self):
        self.money.reserve(t.sha(self.owner_file),'b'*64,'1',run_limit_usd='150',key_remaining_usd='150')
        with self.assertRaises(t.e.BudgetExhausted):self.prepare()
        for provider in self.network:provider.assert_not_called()

    def test_source_reads_keep_integrity_while_reserved_cost_blocks_new_dispatch(self):
        root,plan=self.prepare()
        self.money.reserve(t.sha(self.owner_file),'b'*64,'1',run_limit_usd='150',key_remaining_usd='150')
        with self.assertRaises(t.e.BudgetExhausted):t.guard(plan)
        t.guard(plan,allow_expired=True,require_settled=False)
        (self.snapshot_file).write_text('{}')
        with self.assertRaises(ValueError):t.guard(plan,allow_expired=True,require_settled=False)

    def test_frozen_scope_money_model_and_evidence_cannot_be_substituted(self):
        root,original=self.prepare()
        for change in ({'scope_ids':original['scope_ids'][:1]}, {'maximum_cost_usd':'151'},
                       {'spend_scope_sha256':'b'*64}, {'documents':[{}]},
                       {'membership_deployment':{}}, {'limits':{'call_seconds':999,'analysis_seconds':None}}):
            plan={**deepcopy(original),**change};self.rewrite_plan(root,plan)
            with self.subTest(change=change),self.assertRaises(ValueError):t.guard(plan)

    def test_expired_new_execution_does_not_reopen_old_owner_deadline(self):
        root,plan=self.prepare();auth=t.read_json(plan['authorization']['file'])
        end=datetime.fromisoformat(auth['deadline'])
        with self.assertRaises(TimeoutError):t.window(auth,now=end)
        t.window(auth,now=end,allow_expired=True)
        self.assertEqual(t.read_json(self.owner_file)['deadline'],'2020-01-01T00:00:00Z')
        with self.assertRaises(ValueError):t.window({**auth,'deadline':(end+timedelta(hours=1)).isoformat()})

    def test_completed_run_reentry_is_read_only_and_checks_integrity(self):
        root,plan=self.prepare();t.write(root/'artifacts/report.json',{'synthetic':True})
        done={'plan_sha256':t.sha(root/'plan.json'),'artifacts':{'artifacts/report.json':t.sha(root/'artifacts/report.json')},'report':{'synthetic':True}}
        t.write(root/'completed.json',done)
        with patch.object(t,'guard',side_effect=AssertionError('No new call')):
            self.assertEqual(t.run(root),{'synthetic':True})
        (root/'artifacts/report.json').write_text('{}')
        with self.assertRaises(ValueError):t.run(root)

    def test_copied_plan_cannot_dispatch_from_a_new_directory(self):
        root,plan=self.prepare()
        with self.assertRaisesRegex(ValueError,'original prepared-video directory'):
            t.Session(self.root/'copied',plan,None)

    def test_settled_graph_failure_uses_existing_hold_proof_without_retry(self):
        from commentscope.factory.shared_admission import PriorRequestUnavailable
        root,plan=self.prepare();session=t.Session(root,plan,t.host_resources.RemoteCallGuard())
        session.save=lambda *args:None;sid=next(iter(session.allowed))
        request={'system':'Synthetic','data':{'ORIGINAL':{'source_id':sid}},'schema':{},'max_tokens':128}
        with patch.object(t.shared.Session,'call',side_effect=t.ModelResponseUnavailable('stage','a','b')) as provider,patch.object(t.previous,'settled_hold',side_effect=PriorRequestUnavailable('settled')) as hold:
            with self.assertRaises(PriorRequestUnavailable):session.call('source-evidence-proposal',request)
            self.assertEqual(provider.call_count,1)
            self.assertEqual(hold.call_args.args[2],request)

    def test_failed_runtime_keeps_known_charge_without_retry(self):
        session=t.Session.__new__(t.Session);values=iter([Decimal('0.3'),Decimal('0.32')])
        session.runtime_lock=threading.Lock()
        session.charged=lambda:next(values)
        def fail():raise ValueError('Provider output rejected')
        with self.assertRaises(ValueError) as observed:session.accounting(fail)
        self.assertEqual(observed.exception.new_cost_usd,'0.02')

    def test_changed_source_text_and_foreign_embedding_stage_do_not_dispatch(self):
        root,plan=self.prepare();session=t.Session(root,plan,t.host_resources.RemoteCallGuard())
        exact={sid:session.registry[sid]['text'] for sid in session.allowed}
        with patch.object(t.shared.Session,'embed',return_value={'synthetic':True}) as provider:
            self.assertEqual(session.embed('sources',exact),{'synthetic':True})
            changed=deepcopy(exact);changed[next(iter(changed))]='Invented source'
            for stage,value in [('sources',changed),('sources',{}),('unregistered',exact)]:
                with self.subTest(stage=stage),self.assertRaises(ValueError):session.embed(stage,value)
            self.assertEqual(provider.call_count,1)

    def test_typed_membership_cannot_use_foreign_source_or_changed_generated_candidate(self):
        root,plan=self.prepare();session=t.Session(root,plan,t.host_resources.RemoteCallGuard())
        sid=next(iter(session.allowed));candidate={'id':'c','text':'Adopt P.'}
        t.write(root/'artifacts/initial-candidates.json',[candidate])
        t.write(root/'artifacts/membership-search.json',{'policy':t.SEARCH,'pairs':[{'source_id':sid,'candidate_id':'c'}]})
        payload={'state':{'READING_INPUT':{'ORIGINAL':t.mc.packet(session.registry[sid]),'CANDIDATE':{'text':'Adopt P.'}}}}
        with patch.object(t.shared.Session,'decide',return_value={'synthetic':True}) as provider:
            self.assertEqual(session.decide('synthetic',payload),{'synthetic':True})
            changed=deepcopy(payload);changed['state']['READING_INPUT']['ORIGINAL']['source_id']='foreign'
            with self.assertRaises(ValueError):session.decide('synthetic',changed)
            (root/'artifacts/initial-candidates.json').write_text('[]')
            with self.assertRaises(ValueError):session.decide('synthetic',payload)
            self.assertEqual(provider.call_count,1)

    def test_prepared_product_build_runs_seeded_generation_and_verification_on_same_owner(self):
        from commentscope.product.analysis import Analysis
        from commentscope.providers import openai_schema
        from test_seeded_perspectives import seeded_bundle
        from test_seeded_runtime import response,verifier
        root,plan=self.prepare();t.write(root/'artifacts/report.json',{'synthetic':True})
        t.write(root/'completed.json',{'plan_sha256':t.sha(root/'plan.json'),'report':{},
            'artifacts':{'artifacts/report.json':t.sha(root/'artifacts/report.json')}})
        analysis=Analysis(seeded_bundle(),{'synthetic':True})
        def reply(request,*args,**kwargs):
            if kwargs.get('typed_request'):return verifier(request)
            value=response()
            if openai_schema.compile_schema(request['schema'])['wrapped']:value={'result':value}
            return {'provider':'OpenAI','model':t.e.remote.SOL['model'],
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
                'usage':{'cost':0.00001,'prompt_tokens':1,'completion_tokens':1}}
        with patch.object(t,'from_factory',return_value=analysis),patch.object(t.e,'check_quota'),patch.object(t.e,'InferenceBudget') as budget:
            budget.return_value.call.side_effect=reply
            app,legacy,session=t.build(root)
            try:
                token=secrets.token_urlsafe(32)
                _,s=app.handle('POST','/api/v1/sessions',token,{'analysis_id':analysis.id,
                    'bundle_revision':analysis.revision,'initial_opinion':'','request_id':'create'})
                _,r=app.handle('POST','/api/v1/sessions/'+s['session_id']+'/rooms',token,
                    {'mode':'one_to_one','participant_ids':['P1'],'initial_revision':1,'request_id':'room'})
                path='/api/v1/rooms/'+r['room_id']
                _,j=app.handle('POST',path+'/start',token,{'opening_question':'Why?',
                    'expected_revision':r['revision'],'request_id':'start'})
                end=time.monotonic()+3
                while time.monotonic()<end:
                    job=app.handle('GET','/api/v1/jobs/'+j['job_id'],token)[1]
                    if job['state'] not in ('queued','running'):break
                    time.sleep(.01)
                self.assertEqual(job['state'],'succeeded',job)
                message=app.handle('GET',path,token)[1]['messages'][-1]
                self.assertEqual([p['origin'] for p in message['points']],['original_comment','ai_reasoning'])
                self.assertEqual(session.charged(),Decimal('0.300011'))
                self.assertEqual(budget.return_value.call.call_count,2)
                self.assertEqual(self.money.summary()['charged_usd'],'0.400011')
            finally:app.close()
