"""Offline transport, role and money boundaries for the all-HTTP Factory."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.providers import remote_verification as remote, openrouter
from commentscope.providers.openrouter_budget import SpendLedger, PaidBudget
from commentscope.providers.budget import BudgetExhausted
from commentscope.factory import argument_dependencies as deps, fact_checks as facts, remote_fact_records
from commentscope.factory.automatic_contract import digest

PLAN='a'*64


def embedding(count=1,**usage):
    return {'model':remote.EMBEDDING['model'],'data':[{'index':i,'embedding':[1.]+[0.]*1535} for i in range(count)],
            'usage':{'prompt_tokens':count*3,'total_tokens':count*3,**usage}}


def parsed(output):
    raw={'model':remote.SOL['model'],'provider':'OpenAI','usage':{'cost':0.0001},
         'choices':[{'message':{'content':json.dumps(output)},'finish_reason':'stop'}]}
    return {'output':output,'raw':json.dumps(output),'errors':[],
            'transport':{'provider_response':raw,'provider_response_sha256':digest(raw)}}


class RemoteVerificationTests(unittest.TestCase):
    def test_only_registered_families_dispatch_to_explicit_roles(self):
        self.assertEqual(remote.role('extract-'+'a'*20),'generation')
        self.assertEqual(remote.role('argument-dependency-'+'b'*20),'verification')
        self.assertEqual(remote.role('runtime'),'interaction')
        for key in ('unknown','extract-invented','runtime-arbitrary'):
            with self.assertRaises(ValueError):remote.role(key)

    def test_wire_reservation_includes_schema_margin_and_allocated_reasoning_once(self):
        request={'system':'s','data':{'text':'한글'*20},'schema':{'type':'object','properties':{},'required':[],'additionalProperties':False},'max_tokens':1524}
        budget=remote.WireBudget(Mock(),Mock(),plan_sha256=PLAN,deployment=remote.SOL,
            maximum_run_usd='8',paid_provider=Mock(),key_metadata=Mock())
        wire=openrouter.Client(remote.SOL).payload(**request)
        bound=len(json.dumps(wire,ensure_ascii=False,allow_nan=False).encode())+8192
        expected=(Decimal(bound)*5+Decimal(1524)*15)/1_000_000
        self.assertEqual(budget.maximum_charge(request),expected)
        self.assertLess(budget.maximum_charge(request),Decimal('0.1'))
        legacy=PaidBudget(Mock(),Mock(),plan_sha256=PLAN,deployment=remote.SOL,
            maximum_run_usd='8',paid_provider=Mock(),key_metadata=Mock())
        self.assertGreater(legacy.maximum_charge(request),5)

    def test_complete_multibyte_chunks_are_bounded_and_reassembled(self):
        texts={'ko':'한글 abc '*2500,'en':'value'}
        batches=remote.batches(texts)
        self.assertEqual(''.join(p['text'] for b in batches for p in b if p['id']=='ko'),texts['ko'])
        self.assertTrue(all(len(p['text'].encode())<=6000 for b in batches for p in b))
        self.assertEqual(remote.combine(texts,[embedding(len(b)) for b in batches])['ko'][0],1)
        with self.assertRaises(ValueError):remote.combine(texts,[])

    def test_embedding_rejects_wrong_models_duplicate_indices_nan_zero_and_missing_usage(self):
        mutations=[]
        a=embedding();a['model']='other';mutations.append(a)
        a=embedding(2);a['data'][1]['index']=0;mutations.append(a)
        a=embedding();a['data'][0]['embedding'][0]=float('nan');mutations.append(a)
        a=embedding();a['data'][0]['embedding']=[0.]*1536;mutations.append(a)
        a=embedding();a['usage']={};mutations.append(a)
        for value in mutations:
            with self.assertRaises(ValueError):remote.embedding_vectors(value,len(value['data']))

    def test_embedding_accepts_provider_response_model_id_but_rejects_other_model_or_provider(self):
        value=embedding();value.update(model='text-embedding-3-small',provider='OpenAI')
        self.assertEqual(len(remote.embedding_vectors(value,1)[0]),1536)
        for model,provider in [('text-embedding-3-large','OpenAI'),('text-embedding-3-small','Azure')]:
            changed=deepcopy(value);changed.update(model=model,provider=provider)
            with self.assertRaises(ValueError):remote.embedding_vectors(changed,1)

    def budget(self,response):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        ledger=SpendLedger(Path(directory.name)/'spend.sqlite','test',maximum_usd='50')
        base=Mock();base.call.return_value=response;provider=Mock()
        budget=remote.EmbeddingBudget(base,ledger,plan_sha256=PLAN,spend_scope_sha256='b'*64,
            maximum_run_usd='8',paid_provider=provider,key_metadata=lambda:{'limit_remaining':50})
        req={'system':remote.VERSION,'data':{'input':['hello']},'schema':{},'max_tokens':1}
        return budget,ledger,base,provider,req

    def test_valid_embedding_without_cost_retains_full_reservation_as_conservative(self):
        budget,ledger,base,provider,req=self.budget(embedding())
        budget.call(req,PLAN,timeout_seconds=180,provider=provider)
        self.assertEqual(ledger.summary()['conservative_usd'],'0.00016384')
        self.assertEqual(ledger.summary()['confirmed_usd'],'0')
        self.assertEqual(ledger.summary()['uncertain_calls'],0)

    def test_invalid_embedding_without_cost_holds_charge_and_blocks_repeat(self):
        response=embedding();response['data']=[]
        budget,ledger,base,provider,req=self.budget(response)
        with self.assertRaises(ValueError):budget.call(req,PLAN,timeout_seconds=180,provider=provider)
        with self.assertRaises(BudgetExhausted):budget.call(req,PLAN,timeout_seconds=180,provider=provider)
        self.assertEqual(base.call.call_count,1)
        self.assertEqual(ledger.summary()['uncertain_calls'],1)

    def test_embedding_known_cost_settled_before_invalid_content_is_rejected(self):
        response=embedding(cost=0.000001);response['data']=[]
        budget,ledger,base,provider,req=self.budget(response)
        with self.assertRaises(ValueError):budget.call(req,PLAN,timeout_seconds=180,provider=provider)
        self.assertEqual(ledger.summary()['confirmed_usd'],'0.000001')
        self.assertEqual(ledger.summary()['uncertain_calls'],0)

    def test_wrong_provider_or_model_receipt_cannot_be_accepted(self):
        remote.receipt({'model':'openai/gpt-6.1-sol-20260929','provider':'OpenAI'},remote.SOL)
        for response in ({'model':remote.SOL['model'],'provider':'Azure'},
                         {'model':'openai/gpt-5.2','provider':'OpenAI'}):
            with self.assertRaises(ValueError):remote.receipt(response,remote.SOL)

    def test_chat_graph_receipt_has_no_manufactured_probabilities_and_binds_choices(self):
        case=json.loads(Path('tests/fixtures/jev-transfer-controls.json').read_text(encoding='utf-8'))['sources'][0]
        task=deps.tasks(case['record'],case['cores'])[0]
        requests=deps.chat_requests(task)
        results=[parsed({k:('value' if k.startswith('kind_') else 'asserted' if k.startswith('authorship_')
                           else 'complete' if k.startswith('coverage_') else 'none')
                         for k in p['schema']['properties']}) for p in requests]
        check=deps.bind_chat(task,results,remote.SOL)
        self.assertNotIn('probabilities',json.dumps(check))
        changed=deepcopy(results);changed[0]['output'].pop(next(iter(changed[0]['output'])))
        with self.assertRaises(ValueError):deps.bind_chat(task,changed,remote.SOL)
        changed=deepcopy(results);changed[0]['transport']['provider_response']['model']='typesafe/jev-1.14'
        with self.assertRaises(ValueError):deps.bind_chat(task,changed,remote.SOL)

    def test_remote_fact_record_binds_scope_citations_model_and_original_response(self):
        from experiments.grounding_contract_demo import fixture, verdict
        bundle=fixture();bound=facts.packet(bundle['claims'][1],bundle['documents'],bundle['checks'][0]['selections'],bundle['expires_at'])
        model={'kind':'remote_llm','name':remote.SOL['model'],'revision':remote.SOL['model'],'provider':'OpenAI',
               'deployment_sha256':digest(remote.SOL),'runtime_sha256':'c'*64,'language_scope':'multilingual'}
        record=remote_fact_records.bind(bound,model,parsed(verdict()))
        self.assertTrue(remote_fact_records.validate_record(record,bound,model))
        self.assertNotIn('weights_sha256',record['model'])
        relabeled=deepcopy(bundle['checks'][0]['record']);relabeled['model']=deepcopy(model)
        with self.assertRaises(ValueError):facts.validate_record(relabeled,bound,model)
        changed=deepcopy(bound);changed['claim']['scope']['time']='2098'
        with self.assertRaises(ValueError):remote_fact_records.validate_record(record,changed,model)
        changed=deepcopy(record);changed['result']['output']['verdict']='insufficient'
        changed['result']['raw']=json.dumps(changed['result']['output'])
        with self.assertRaises(ValueError):remote_fact_records.validate_record(changed,bound,model)
        with self.assertRaises(ValueError):remote_fact_records.bind(bound,model,parsed(verdict('supported',['invented'])))

    def test_chat_graph_source_audits_compile_and_keep_owner_scope_vetoes(self):
        import test_jev_audit_integration as fixture
        from commentscope.factory import argument_observations as obs,source_arguments as sa
        f=fixture.JevAuditIntegrationTests();f.setUp();self.addCleanup(f.doCleanups)
        h=f.h;checks=[]
        for record in h.records:
            for task in deps.tasks(record,h.cores):
                responses=[]
                for req in deps.chat_requests(task):
                    output={k:('value' if k.startswith('kind_') else 'asserted' if k.startswith('authorship_')
                               else 'complete' if k.startswith('coverage_') else 'none') for k in req['schema']['properties']}
                    responses.append(parsed(output))
                checks.append(deps.bind_chat(task,responses,remote.SOL))
        def audits(bad=False):
            result=[]
            for task in f.f.tasks:
                req=sa.audit_request(h.records,h.cores,[task],protocol=obs.CHAT_SPLIT,core_checks=h.checks)
                helper=deepcopy(req)
                for row in helper['data']['TASKS']:
                    if row['kind']=='unit':row['LINK_TARGETS']=[]
                response=h.result(helper)
                for row in response['output']['observations']:
                    row.pop('dependency_fidelity');row.pop('owner_relations',None)
                    row['basis']='coverage_agrees' if task['kind']=='coverage' else 'normative_assertion'
                    if bad and task['kind']=='unit':row['conditions_fidelity']='no'
                result.append(sa.bind_audit(h.records,h.cores,[task],response,protocol=obs.CHAT_SPLIT,
                    core_checks=h.checks,owner_checks=f.f.checks(),dependency_checks=checks))
            return result
        self.assertEqual(len(h.prepare(audits())['compiled']['profiles']),2)
        self.assertEqual(h.prepare(audits(True))['compiled']['profiles'],[])

    def test_remote_fact_compilation_uses_remote_records_and_never_nli(self):
        from experiments.grounding_contract_demo import fixture,verdict
        from commentscope.factory import pipeline_stages as stages
        from types import SimpleNamespace
        bundle=fixture();bundle['claims']=[bundle['claims'][1]]
        model={'kind':'remote_llm','name':remote.SOL['model'],'revision':remote.SOL['model'],'provider':'OpenAI',
               'deployment_sha256':digest(remote.SOL),'runtime_sha256':'c'*64,'language_scope':'multilingual'}
        with patch.object(stages.ma,'prepare',return_value={'bundle':bundle}) as prepare,patch.object(stages.nli_fact_records,'invocation',side_effect=AssertionError('No local NLI')):
            _,checks=stages.compile_agents(SimpleNamespace(usage=SimpleNamespace(expires_at=bundle['expires_at'])),[],[],[],[],[],
                lambda req:parsed(verdict()),model=model,documents=bundle['documents'],selections=bundle['checks'][0]['selections'])
        self.assertEqual(prepare.call_count,2)
        self.assertEqual(checks[0]['record']['artifact_kind'],remote_fact_records.VERSION)


class RemoteExecutorTests(unittest.TestCase):
    def setUp(self):
        from datetime import datetime,timedelta,timezone
        from commentscope.providers import scoped_authorization as auth,openrouter_decisions as od
        from commentscope.storage import write_json_exclusive as write
        from experiments import remote_factory_pipeline as executor
        self.e=executor
        tmp=tempfile.TemporaryDirectory(dir='runs',prefix='test-sol-');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.run=self.root/'benchmark'
        self.gen=deepcopy(remote.SOL);self.gen.update(model='openai/gpt-5.2',context=400000)
        self.gen.pop('billing_ceiling');self.gen['provider']['max_price']={'prompt':1.75,'completion':14,'request':0}
        policy={'account_id':'test-sol','ledger':str(self.root/'spend.sqlite'),'maximum_usd':'50','opening_charge_usd':'0'}
        self.policy_file=self.root/'policy.json';write(self.policy_file,policy)
        now=datetime.now(timezone.utc);owner=self.root/'owner.json'
        write(owner,{'version':auth.VERSION,'tasks':['TASK-005','TASK-006'],'gates':['G1','G2','G3'],
            'started_at':now.isoformat(),'deadline':(now+timedelta(hours=1)).isoformat(),'maximum_additional_usd':'8',
            'shared_policy_file':str(self.policy_file),'chat_deployment':self.gen,'decisions_deployment':od.DEPLOYMENT})
        self.auth=self.root/'authorization.json';executor.authorize(self.auth,owner)
        self.materials=self.root/'materials.json';write(self.materials,{'documents':[],'selections':[],
            'model_files':{'/nonexistent/local-model':'a'*64},'classifier':{'obsolete':True}})
        self.addCleanup(patch.stopall)
        from types import SimpleNamespace
        space_class=executor.api_resources.SpaceGuard
        patch.object(executor.api_resources,'SpaceGuard',side_effect=lambda directory,policy:space_class(
            directory,policy,disk_usage=lambda path:SimpleNamespace(free=10*1024**3))).start()
        patch.object(executor,'provider_preflight',return_value={}).start()
        patch.object(executor,'embedding_preflight',return_value={}).start()
        patch.object(executor,'source_code_hashes',side_effect=lambda:{p:executor.sha(p) for p in executor.RUNTIME_FILES}).start()
        source=self.root/'fact-source.json';write(source,{'rows':[]})
        patch.object(executor,'FACT_SOURCE',source).start()
        self.plan=executor.prepare(self.run,self.auth,self.materials,mode='benchmark')

    def test_prepare_never_reads_or_requires_local_model_files(self):
        self.assertEqual(self.plan['model_files'],{})
        self.assertEqual(self.plan['resource_policy']['minimum_available_mb'],256)
        self.assertEqual(self.plan['classifier']['kind'],'remote_llm')
        self.e.validate(self.run,self.plan)
        changed=deepcopy(self.plan);changed['verification_deployment']=self.gen
        with self.assertRaises(ValueError):self.e.guard(changed)
        changed=deepcopy(self.plan);changed['maximum_cost_usd']='9'
        with self.assertRaises(ValueError):self.e.guard(changed)

    def test_routed_generation_verification_runtime_and_embedding_share_original_money(self):
        request={'system':'s','data':{},'schema':{'type':'object','properties':{'result':{'type':'string'}},
            'required':['result'],'additionalProperties':False},'max_tokens':100}
        seen=[];base=Mock()
        def respond(req,plan_sha,*,provider,**kwargs):
            model=provider.__self__.deployment['model'];seen.append(model)
            if model==remote.EMBEDDING['model']:return embedding(len(req['data']['input']))
            return {'provider':'OpenAI','model':model,'choices':[{'message':{'content':'{"result":"ok"}'},'finish_reason':'stop'}],
                    'usage':{'cost':0.0001,'prompt_tokens':10,'completion_tokens':5}}
        base.call.side_effect=respond
        with patch.object(self.e,'InferenceBudget',return_value=base),patch.object(self.e,'key_metadata',return_value={'limit_remaining':50}),patch.object(self.e,'check_quota'):
            s=self.e.RemoteSession(self.run,self.plan,self.e.host_resources.RemoteCallGuard())
            for stage in ('extract','source-world','runtime'):s.call(stage,request)
            self.assertEqual(s.embed('synthetic',{'A':'hello'})['A'][0],1)
            self.assertEqual(seen,[self.gen['model'],remote.SOL['model'],self.gen['model'],remote.EMBEDDING['model']])
            scope=s.money.summary(plan_sha256=self.plan['spend_scope_sha256'])
            self.assertEqual(scope['calls'],4);self.assertEqual(scope['conservative_calls'],1)
            before=len(seen);s.call('source-world',request);self.assertEqual(len(seen),before)
            with self.assertRaises(ValueError):s.call('unknown',request)

    def test_subcap_counts_existing_money_and_refuses_before_dispatch(self):
        money=self.e.ledger(self.plan['spend_policy']);scope=self.plan['spend_scope_sha256']
        call=money.reserve(scope,'d'*64,'0.4',run_limit_usd='8',key_remaining_usd='50');money.finish(call,'0.4')
        sub=self.e.SubcapLedger(money,self.plan)
        with self.assertRaises(BudgetExhausted):sub.reserve(scope,'e'*64,Decimal('0.11'),run_limit_usd='8',key_remaining_usd='50')
        self.assertEqual(money.summary()['calls'],1)

    def test_storage_exhaustion_refuses_before_paid_intent_or_model_dispatch(self):
        base=Mock()
        req={'system':'s','data':{},'schema':{'type':'object','properties':{},'required':[],'additionalProperties':False},'max_tokens':10}
        with patch.object(self.e,'InferenceBudget',return_value=base),patch.object(self.e,'check_quota'):
            session=self.e.RemoteSession(self.run,self.plan,self.e.host_resources.RemoteCallGuard())
            session.storage.check=Mock(side_effect=self.e.host_resources.ResourceStopRequested('full'))
            with self.assertRaises(self.e.host_resources.ResourceStopRequested):session.call('extract',req)
            with self.assertRaises(self.e.host_resources.ResourceStopRequested):session.embed('source',{'A':'hello'})
        base.call.assert_not_called()
        self.assertEqual(list((self.run/'checkpoints').glob('*.intent.json')),[])
        self.assertEqual(session.money.summary()['calls'],0)


if __name__=='__main__':unittest.main()
