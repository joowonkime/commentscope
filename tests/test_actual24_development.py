"""Development execution cannot become formal admission or reset paid history."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import actual24_development as dev
from commentscope.providers import scoped_authorization, openrouter_decisions
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from experiments import minimal_factory_review


class Actual24DevelopmentTests(unittest.TestCase):
    def setUp(self):
        Path('runs').mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir='runs', prefix='test-actual24-')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.policy=self.root/'policy.json'
        write(self.policy, {'account_id':'development-test', 'ledger':str(self.root/'money.sqlite'),
            'maximum_usd':'50','opening_charge_usd':'13'})
        now=datetime.now(timezone.utc)
        generation=deepcopy(dev.executor.remote.SOL)
        generation.update(model='openai/gpt-5.2', context=400000)
        self.parent=self.root/'parent.json'
        write(self.parent, {'version':scoped_authorization.VERSION,'tasks':['TASK-005','TASK-006'],
            'gates':['G1','G2','G3'], 'started_at':now.isoformat(),
            'deadline':(now+timedelta(hours=7)).isoformat(), 'maximum_additional_usd':'8',
            'shared_policy_file':str(self.policy),'chat_deployment':generation,
            'decisions_deployment':openrouter_decisions.DEPLOYMENT})
        self.auth=self.root/'auth.json'
        dev.executor.authorize(self.auth,self.parent)
        auth=json.loads(self.auth.read_text())
        self.plan={'artifact_kind':dev.VERSION,'mode':'development','gate':'G2',
            'formal_admission_eligible':False,'quality_gate_passed':False,'admission_file':None,
            'development_user_request':'rr after actual24 development clarification',
            'subcap_usd':'1.50','maximum_cost_usd':'8',
            'authorization':{'file':str(self.auth),'sha256':sha(self.auth),'authorization':auth},
            'deployment':generation,'verification_deployment':dev.executor.remote.SOL,
            'embedding_deployment':dev.executor.remote.EMBEDDING,'role_registry':dev.executor.remote.ROLES,
            'spend_scope_sha256':sha(self.parent),'spend_policy':json.loads(self.policy.read_text()),
            'run_directory':str((self.root/'run').resolve()), 'cross_run_response_reuse':False}

    def test_actual24_uses_original_financial_authority_without_formal_admission(self):
        dev.guard(self.plan)
        self.assertEqual(self.plan['spend_scope_sha256'],sha(self.parent))
        self.assertEqual(dev.executor.ledger(self.plan['spend_policy']).summary()['charged_usd'],'13')

    def test_development_gate_promotion_and_subcap_tampering_are_rejected(self):
        for key,value in [('gate','G3'),('mode','factory'),('formal_admission_eligible',True),
                ('quality_gate_passed',True),('admission_file','fake-admission.json'),
                ('development_user_request',''),('subcap_usd','1.500000001'),('subcap_usd','0')]:
            plan=deepcopy(self.plan);plan[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                dev.guard(plan)

    def test_formal_review_rejects_a_completed_development_run(self):
        directory=self.root/'run'
        write(directory/'plan.json',self.plan)
        write(directory/'completed.json',{'execution_complete':True})
        with self.assertRaisesRegex(ValueError,'Completed and immutable run required'):
            minimal_factory_review.load_run(directory)

    def test_request_reservation_preserves_old_scope_spend_and_subcap(self):
        money=dev.executor.ledger(self.plan['spend_policy']);scope=self.plan['spend_scope_sha256']
        first=money.reserve(scope,'a'*64,'0.5',run_limit_usd='8',key_remaining_usd='37')
        money.finish(first,'0.3')
        plan={**self.plan,'opening_scope_charge_usd':'0.3'}
        bounded=dev.executor.SubcapLedger(money,plan)
        call=bounded.reserve(scope,'b'*64,'1.4',run_limit_usd='8',key_remaining_usd='36.7')
        money.finish(call,'1.4')
        with self.assertRaises(dev.executor.BudgetExhausted):
            bounded.reserve(scope,'c'*64,'0.100000001',run_limit_usd='8',key_remaining_usd='35.3')
        self.assertEqual(money.summary()['charged_usd'],'14.7')

    def test_completed_failed_generation_is_read_without_another_model_call(self):
        directory=self.root/'run';write(directory/'plan.json',self.plan)
        money=dev.executor.ledger(self.plan['spend_policy'])
        storage=SimpleNamespace(before_write=lambda value:None)
        session=SimpleNamespace(storage=storage,money=money,embed=None,inspect=None,call=None)
        output={'agent_inputs':{'bundle':{},'compiled':{'profiles':[]}},
            'errors':[],'capacity_holds':[],'unextracted_source_ids':[]}
        runtime={'turns':[]}
        with patch.object(dev,'validate',return_value=self.plan),\
                patch.object(dev.executor,'quota_watch',return_value=nullcontext()),\
                patch.object(dev.executor,'provider_preflight'),patch.object(dev.executor,'embedding_preflight'),\
                patch.object(dev.executor,'RemoteSession',return_value=session) as transport,\
                patch.object(dev.host_resources,'watch',return_value=nullcontext()),\
                patch.object(dev,'load_snapshot',return_value=SimpleNamespace(snapshot={})),\
                patch.object(dev.minimal_pipeline,'process',return_value=output) as process,\
                patch.object(dev,'runtime_probe',return_value=runtime),patch.object(dev,'runtime_check'):
            plan=self.plan;plan['resource_policy']={};plan['snapshot']='unused'
            for field in ('classifier','documents','selections','scope_ids','verification_contract',
                    'extraction_protocol','argument_audit_protocol','agent_source_policy',
                    'membership_retrieval_policy','questions'):plan[field]=None
            first=dev.run(directory)
            second=dev.run(directory)
            self.assertEqual(first,second)
            self.assertEqual(first['compiled_agents'],0)
            self.assertFalse(first['quality_gate_passed'])
            self.assertFalse(first['formal_admission_eligible'])
            self.assertEqual(transport.call_count,1)
            self.assertEqual(process.call_count,1)
            self.assertEqual(money.summary()['charged_usd'],'13')
        write(directory/'artifacts'/'tampered.json',{})
        (directory/'artifacts'/'output.json').write_text('{}')
        with patch.object(dev,'validate',return_value=self.plan),\
                patch.object(dev.executor,'quota_watch',return_value=nullcontext()),\
                self.assertRaisesRegex(ValueError,'Completed development artifacts changed'):
            dev.run(directory)


if __name__=='__main__':
    unittest.main()
