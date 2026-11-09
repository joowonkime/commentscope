from copy import deepcopy
from decimal import Decimal
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import serve_mvp as server
from commentscope.product.analysis import Analysis
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.providers.budget import BudgetExhausted
from experiments.grounding_contract_demo import fixture
from test_openrouter import deployment


class ProductServerPlanTests(unittest.TestCase):
    def product_cycle(self):
        from commentscope.providers.execution_cycle import PRODUCT_CYCLE_VERSION
        self.cycle.update(version=PRODUCT_CYCLE_VERSION,tasks=['TASK-011','TASK-012'],
            user_request='Complete the remaining MVP',maximum_additional_usd='1',historical_charges_preserved=True,
            shared_policy_sha256=sha(self.root/'policy.json'))
        self.cycle_file.write_text(json.dumps(self.cycle))

    def test_product_cycle_keeps_shared_history_without_requiring_research_task(self):
        self.product_cycle();directory,plan=self.prepare()
        self.assertEqual(plan['cycle']['tasks'],['TASK-011','TASK-012']);self.base.call.assert_not_called()
        product,legacy,broker=server.build(directory)
        try:self.assertEqual(self.compare(product)['state'],'succeeded')
        finally:product.close()
        self.assertEqual(broker.ledger.summary()['confirmed_usd'],'0.10001')

    def test_product_cycle_does_not_authorize_factory_or_reset_its_cap(self):
        from commentscope.providers.execution_cycle import bind_cycle,cycle_guard
        self.product_cycle()
        with self.assertRaisesRegex(ValueError,'Product-only'):
            bind_cycle(self.cycle_file,self.cycle['selected_deployment'],self.policy,'1')
        for change in ({'maximum_additional_usd':'2.01'},{'user_request':' '},{'tasks':['TASK-005']},{'shared_policy_sha256':'f'*64}):
            with self.subTest(change=change),self.assertRaises(ValueError):cycle_guard({**self.cycle,**change})

    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='runs',prefix='mvp-plan-test-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.addCleanup(patch.stopall)
        patch.dict(os.environ,{'OPENROUTER_API_KEY':'synthetic-test-key'}).start()
        self.analysis=Analysis(fixture(),{'synthetic':True})
        self.factory=self.root/'factory';write(self.factory/'snapshot.json',{'synthetic':True})
        write(self.factory/'plan.json',{'snapshot':str(self.factory/'snapshot.json'),'snapshot_sha256':sha(self.factory/'snapshot.json')})
        write(self.factory/'artifacts/agent-inputs.json',{'bundle':fixture()});write(self.factory/'artifacts/output.json',{})
        self.policy={'account_id':'synthetic-test','ledger':str(self.root/'spend.sqlite'),
                     'maximum_usd':'50','opening_charge_usd':'0.1'}
        write(self.root/'policy.json',self.policy)
        self.cycle={'version':server.CYCLE_VERSION,'tasks':['TASK-004'],
            'started_at':datetime.now(timezone.utc).isoformat(),
            'deadline':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            'maximum_additional_usd':'5','selected_deployment':{**deployment(),'context':65536},
            'shared_policy_file':str(self.root/'policy.json')}
        self.cycle_file=self.root/'cycle.json';write(self.cycle_file,self.cycle)
        patch.object(server,'from_factory',return_value=self.analysis).start()
        patch.object(server,'source_code_hashes',return_value={'synthetic.py':'fixed'}).start()
        patch.object(server,'archive_sources').start()
        patch.object(server,'provider_preflight',return_value={'synthetic':True}).start()
        patch.object(server,'key_metadata',return_value={'limit_remaining':50}).start()
        self.base=patch.object(server,'InferenceBudget').start().return_value
        self.base.call.side_effect=self.response

    def response(self,request,*args,**kwargs):
        data=request['data'];output={'items':[{'relation':'agreement','user_span_ids':['I000'],
            'perspective_claim_ids':[data['PERSPECTIVE_CLAIMS'][0]['id']],
            'explanation':'Synthetic comparison.','consideration_question':None}]}
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}],
                'usage':{'cost':0.00001,'prompt_tokens':1,'completion_tokens':1}}

    def prepare(self,name='server'):
        directory=self.root/name
        plan=server.prepare(directory,self.factory,self.cycle_file,session_ttl_seconds=3600,room_maximum_usd='1')
        return directory,plan

    def compare(self,app):
        token=secrets.token_urlsafe(32)
        _,session=app.handle('POST','/api/v1/sessions',token,{'analysis_id':self.analysis.id,
            'bundle_revision':self.analysis.revision,'initial_opinion':'I support it.','request_id':'create'})
        path='/api/v1/sessions/'+session['session_id']
        _,job=app.handle('POST',path+'/comparisons',token,{'perspective_id':'P1','initial_revision':1,'request_id':'compare'})
        until=time.monotonic()+3
        while time.monotonic()<until:
            result=app.handle('GET','/api/v1/jobs/'+job['job_id'],token)[1]
            if result['state'] not in ('queued','running'):return result
            time.sleep(.01)
        self.fail('Job did not settle')

    def test_prepare_does_not_infer_and_does_not_publish_key_or_approval(self):
        directory,plan=self.prepare()
        self.base.call.assert_not_called()
        self.assertEqual(plan['spend_scope_sha256'],sha(self.cycle_file))
        self.assertFalse(plan['quality_gate_passed'])
        self.assertNotIn('synthetic-test-key',(directory/'plan.json').read_text(encoding='utf-8'))

    def test_two_server_plans_share_one_existing_cycle_charge(self):
        for name in ('first','second'):
            directory,_=self.prepare(name)
            product,legacy,broker=server.build(directory)
            try:self.assertEqual(self.compare(product)['state'],'succeeded')
            finally:product.close()
        ledger=SpendLedger(self.policy['ledger'],self.policy['account_id'],maximum_usd='50',opening_charge_usd='0.1')
        own=ledger.summary(plan_sha256=sha(self.cycle_file))
        self.assertEqual(own['charged_usd'],'0.00002');self.assertEqual(own['maximum_usd'],'5')
        self.assertEqual(self.base.call.call_count,2)

    def test_changed_cycle_and_bundle_refuse_before_inference(self):
        directory,_=self.prepare()
        value=read_json(self.cycle_file);value['maximum_additional_usd']='6';self.cycle_file.write_text(json.dumps(value))
        with self.assertRaises(ValueError):server.build(directory)
        self.base.call.assert_not_called()

    def test_expired_cycle_refuses_new_call_and_keeps_read_and_save_available(self):
        directory,_=self.prepare();product,legacy,broker=server.build(directory)
        try:
            with patch.object(server,'cycle_guard',side_effect=TimeoutError('deadline')):
                self.assertEqual(broker.status(),'cycle_deadline')
                self.assertEqual(product.handle('GET','/api/v1/analyses','')[0],200)
        finally:product.close()
        self.base.call.assert_not_called()

    def trial_fixture(self,*,trial_opening='0.4'):
        self.product_cycle()
        trial_file=self.root/'trial.json';write(trial_file,{'synthetic':True})
        factory=read_json(self.factory/'plan.json')
        factory.update(trial={'file':str(trial_file),'sha256':sha(trial_file),'authorization':read_json(trial_file)},
            deployment=self.cycle['selected_deployment'],spend_policy=self.policy,spend_scope_sha256='a'*64,
            maximum_cost_usd='8',opening_scope_charge_usd=trial_opening,subcap_usd='1.50')
        (self.factory/'plan.json').write_text(json.dumps(factory))
        write(self.factory/'artifacts/runtime.json',{'synthetic':True})
        write(self.factory/'completed.json',{'execution_complete':True,
            'plan_sha256':sha(self.factory/'plan.json'),'output_sha256':sha(self.factory/'artifacts/output.json'),
            'runtime_sha256':sha(self.factory/'artifacts/runtime.json'),'compiled_agents':2,
            'binding_errors':0,'capacity_holds':0})
        patch.object(server.trial_budget.shared,'validate',side_effect=lambda _:read_json(self.factory/'plan.json')).start()
        patch.object(server.trial_budget.shared,'guard').start()
        money=SpendLedger(self.policy['ledger'],self.policy['account_id'],maximum_usd='50',opening_charge_usd='0.1')
        for scope,cost,limit in (('a'*64,'0.8','8'),(sha(self.cycle_file),'0.05','1')):
            call=money.reserve(scope,'b'*64,cost,run_limit_usd=limit,key_remaining_usd='50');money.finish(call,cost)
        return trial_file,money

    def linked_prepare(self,trial_file,name='linked'):
        directory=self.root/name
        plan=server.prepare(directory,self.factory,self.cycle_file,session_ttl_seconds=3600,
                            room_maximum_usd='1',factory_trial=trial_file)
        return directory,plan

    def test_product_and_factory_share_trial_and_product_anchor_across_server_plans(self):
        trial,money=self.trial_fixture();anchors=[]
        for name in ('linked1','linked2'):
            directory,plan=self.linked_prepare(trial,name);anchors.append(plan['factory_trial'])
            self.assertEqual(plan['spend_scope_sha256'],'a'*64)
            self.assertEqual(plan['money_owner_limit_usd'],'8')
            product,_,broker=server.build(directory)
            try:self.assertEqual(self.compare(product)['state'],'succeeded')
            finally:product.close()
        self.assertEqual(anchors[0]['anchor'],anchors[1]['anchor'])
        self.assertEqual(anchors[0]['anchor']['opening_scope_charge_usd'],'0.8')
        self.assertEqual(anchors[0]['anchor']['subcap_usd'],'0.95')
        self.assertEqual(money.summary(plan_sha256='a'*64)['charged_usd'],'0.80002')
        self.assertEqual(money.summary(plan_sha256=sha(self.cycle_file))['charged_usd'],'0.05')

    def test_existing_product_spend_limits_shared_money_without_reset(self):
        trial,money=self.trial_fixture();directory,plan=self.linked_prepare(trial)
        product,_,broker=server.build(directory)
        try:
            call=broker.ledger.reserve('a'*64,'c'*64,'0.9',run_limit_usd='8',key_remaining_usd='50')
            broker.ledger.finish(call,'0.9')
            with self.assertRaises(BudgetExhausted):
                broker.ledger.reserve('a'*64,'d'*64,'0.06',run_limit_usd='8',key_remaining_usd='50')
            _,again=self.linked_prepare(trial,'next-server')
            self.assertEqual(again['factory_trial']['anchor'],plan['factory_trial']['anchor'])
            self.assertEqual(money.summary(plan_sha256='a'*64)['charged_usd'],'1.7')
        finally:product.close()

    def test_later_factory_cost_also_reduces_available_product_trial_money(self):
        trial,money=self.trial_fixture(trial_opening='0');directory,_=self.linked_prepare(trial)
        product,_,broker=server.build(directory)
        try:
            call=money.reserve('a'*64,'c'*64,'0.6',run_limit_usd='8',key_remaining_usd='50');money.finish(call,'0.6')
            with self.assertRaises(BudgetExhausted):
                broker.ledger.reserve('a'*64,'d'*64,'0.11',run_limit_usd='8',key_remaining_usd='50')
            self.assertEqual(money.summary(plan_sha256='a'*64)['charged_usd'],'1.4')
        finally:product.close()

    def test_changed_old_product_cycle_charge_blocks_linked_generation(self):
        trial,money=self.trial_fixture();directory,_=self.linked_prepare(trial)
        product,_,broker=server.build(directory)
        try:
            call=money.reserve(sha(self.cycle_file),'c'*64,'0.01',run_limit_usd='1',key_remaining_usd='50')
            money.finish(call,'0.01')
            self.assertEqual(broker.status(),'reconcile_required')
            self.assertEqual(product.handle('GET','/api/v1/analyses','')[0],200)
            self.base.call.assert_not_called()
        finally:product.close()

    def test_different_trial_cannot_reuse_existing_product_cycle_anchor(self):
        trial,_=self.trial_fixture();self.linked_prepare(trial)
        alternate=self.root/'other-trial.json';write(alternate,{'other':True})
        with self.assertRaises(ValueError):self.linked_prepare(alternate,'other')
        self.base.call.assert_not_called()

    def test_unfinished_factory_or_insufficient_agents_does_not_create_anchor(self):
        trial,_=self.trial_fixture();path=self.factory/'completed.json';done=read_json(path)
        for change in ({'execution_complete':False},{'compiled_agents':1},{'binding_errors':1},
                       {'capacity_holds':1},{'runtime_sha256':'f'*64}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                path.write_text(json.dumps({**done,**change}));self.linked_prepare(trial)
        self.assertFalse(self.cycle_file.with_name(self.cycle_file.stem+'.factory-trial.json').exists())
        self.base.call.assert_not_called()

    def test_linked_model_and_policy_must_match_existing_product_authorization(self):
        trial,_=self.trial_fixture();path=self.factory/'plan.json';factory=read_json(path)
        for field,value in (('deployment',{**factory['deployment'],'model':'other-model'}),
                            ('spend_policy',{**self.policy,'account_id':'other'})):
            changed={**factory,field:value};path.write_text(json.dumps(changed))
            done=read_json(self.factory/'completed.json');done['plan_sha256']=sha(path)
            (self.factory/'completed.json').write_text(json.dumps(done))
            with self.subTest(field=field),self.assertRaises(ValueError):self.linked_prepare(trial)
        self.base.call.assert_not_called()

    def test_expired_factory_window_blocks_new_product_call_but_keeps_read(self):
        trial,_=self.trial_fixture();directory,_=self.linked_prepare(trial);product,_,broker=server.build(directory)
        try:
            def guard(_,*,allow_expired=False,**kwargs):
                if not allow_expired:raise TimeoutError('trial deadline')
            with patch.object(server.trial_budget.shared,'guard',side_effect=guard):
                self.assertEqual(broker.status(),'cycle_deadline')
                self.assertEqual(product.handle('GET','/api/v1/analyses','')[0],200)
        finally:product.close()
        self.base.call.assert_not_called()

    def test_room_reservation_matches_actual_allocated_wire_budget(self):
        directory,plan=self.prepare();product,_,broker=server.build(directory)
        try:
            req={'system':'Compare.', 'data':{'text':'A short opinion.'},
                 'schema':{'type':'object','properties':{},'additionalProperties':False},'max_tokens':128}
            actual=server.allocate(req,plan['generation_allocation'])
            expected=broker.runner.base.budget.maximum_charge(actual)
            self.assertEqual(Decimal(broker.reservation(req)),expected)
            old=(Decimal(plan['deployment']['context'])*Decimal(str(server.openrouter.billing_prices(plan['deployment'])['prompt']))+
                 Decimal(actual['max_tokens'])*Decimal(str(server.openrouter.billing_prices(plan['deployment'])['completion'])))/1_000_000
            self.assertLess(expected,old)
        finally:product.close()
