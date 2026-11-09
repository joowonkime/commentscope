"""Completion grants cannot erase old money or silently change model/source rules."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import json,tempfile,unittest
from unittest.mock import patch

from tools import complete_factory as completion
from commentscope.providers import scoped_authorization,openrouter_decisions
from commentscope.providers.host_resources import ResourceStopRequested
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from experiments import minimal_factory_review


class CompletionPolicyTests(unittest.TestCase):
    def setUp(self):
        Path('runs').mkdir(exist_ok=True)
        temporary=tempfile.TemporaryDirectory(dir='runs',prefix='test-completion-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.policy=self.root/'policy.json'
        write(self.policy,{'account_id':'completion-tests','ledger':str(self.root/'spend.sqlite'),
            'maximum_usd':'50','opening_charge_usd':'13'})
        now=datetime.now(timezone.utc);self.parent=self.root/'parent.json'
        generation=deepcopy(completion.remote.SOL);generation.update(model='openai/gpt-5.2',context=400000)
        write(self.parent,{'version':scoped_authorization.VERSION,'tasks':['TASK-005','TASK-006'],
            'gates':['G1','G2','G3'],'started_at':(now-timedelta(hours=2)).isoformat(),
            'deadline':(now-timedelta(hours=1)).isoformat(),'maximum_additional_usd':'8',
            'shared_policy_file':str(self.policy),'chat_deployment':generation,
            'decisions_deployment':openrouter_decisions.DEPLOYMENT})
        self.cohort=self.root/'cohort.json';write(self.cohort,{'synthetic_fixture_only':True})
        self.bound={'file':str(self.cohort),'sha256':sha(self.cohort)}
        self.addCleanup(patch.stopall)
        patch.object(completion.cohort_refresh,'bind',return_value=(None,None,{},self.bound)).start()

    def authorize(self,maximum='10',name='authorization.json'):
        return completion.authorize(self.root/name,self.parent,self.cohort,maximum_usd=maximum,user_request='Proceed with remaining MVP.')

    def test_phase_keeps_shared_account_opening_charge_and_original_owner(self):
        auth=self.authorize();ledger=completion.executor.ledger(json.loads(self.policy.read_text()))
        self.assertEqual(ledger.summary()['charged_usd'],'13')
        self.assertEqual(auth['parent_money_owner']['sha256'],sha(self.parent))
        self.assertEqual(auth['maximum_additional_usd'],'10')
        self.assertTrue(auth['historical_charges_preserved'])
        completion.authorization(auth)

    def test_grant_cannot_exceed_remaining_global_money_or_overwrite_existing_grant(self):
        with self.assertRaises(ValueError):self.authorize('38')
        self.authorize()
        with self.assertRaises(ValueError):self.authorize()

    def test_tasks_model_time_and_original_policy_are_immutable(self):
        auth=self.authorize()
        for field,value in (('tasks',['TASK-005']),('gates',['G1']),('user_request',''),
                ('generation_deployment',{}),('maximum_additional_usd','38'),('historical_charges_preserved',False)):
            changed=deepcopy(auth);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):completion.authorization(changed)
        expired=deepcopy(auth);expired['started_at']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        expired['deadline']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        with self.assertRaises(TimeoutError):completion.authorization(expired)
        completion.authorization(expired,allow_expired=True)

    def test_new_scope_does_not_refund_an_old_scope(self):
        policy=json.loads(self.policy.read_text());ledger=completion.executor.ledger(policy)
        old='a'*64;request='b'*64
        call=ledger.reserve(old,request,'0.5',run_limit_usd='8',key_remaining_usd='40');ledger.finish(call,'0.1')
        self.authorize();new=sha(self.root/'authorization.json')
        call=ledger.reserve(new,'c'*64,'0.5',run_limit_usd='10',key_remaining_usd='40');ledger.finish(call,'0.2')
        self.assertEqual(ledger.summary()['charged_usd'],'13.3')
        self.assertEqual(ledger.summary(plan_sha256=old)['charged_usd'],'0.1')
        self.assertEqual(ledger.summary(plan_sha256=new)['charged_usd'],'0.2')

    def test_explicit_larger_record_cap_preserves_original_policy_and_disk_floor(self):
        usage=lambda path:SimpleNamespace(free=10*1024**3)
        space=completion.CompletionStorage(self.root,completion.STORAGE_POLICY,disk_usage=usage)
        self.assertEqual(space.policy['maximum_run_bytes'],4*1024**3)
        self.assertEqual(completion.api_resources.STORAGE_POLICY['maximum_run_bytes'],1024**3)
        space.disk_usage=lambda path:SimpleNamespace(free=1024**3)
        with self.assertRaises(ResourceStopRequested):space.check()
        invalid={**completion.STORAGE_POLICY,'maximum_run_bytes':8*1024**3}
        with self.assertRaises(ValueError):completion.CompletionStorage(self.root,invalid)

    def test_pinned_adapter_can_read_g4_but_cannot_replace_g2_reference(self):
        files={p:sha(p) for p in completion.TOOL_FILES}
        plan={'gate':'G4','inputs':files,'completion_execution':{'version':completion.TOOLS_VERSION,'tool_files':files}}
        with patch.object(completion,'review_reference',return_value={'fixture':'new-reference'}):
            self.assertEqual(minimal_factory_review.completion_reference(plan),{'fixture':'new-reference'})
            plan['gate']='G2'
            with self.assertRaises(ValueError):minimal_factory_review.completion_reference(plan)
        changed=deepcopy(plan);changed['completion_execution']['tool_files'][completion.TOOL_FILES[0]]='0'*64
        with self.assertRaises(ValueError):minimal_factory_review.completion_reference(changed)

    def test_phase_dispatch_rejects_another_gate_owner_role_or_source_contract(self):
        auth=self.authorize();auth_file=self.root/'authorization.json'
        plan={'gate':'G4','mode':'factory',
            'authorization':{'file':str(auth_file),'sha256':sha(auth_file),'authorization':auth},
            'spend_policy':json.loads(self.policy.read_text()),'spend_scope_sha256':sha(auth_file),
            'maximum_cost_usd':'10','subcap_usd':'10','cohort_refresh':self.bound,
            'deployment':auth['generation_deployment'],'verification_deployment':completion.remote.SOL,
            'embedding_deployment':completion.remote.EMBEDDING,'role_registry':completion.remote.ROLES,
            'classifier':completion.executor.model_identity(),
            'membership_retrieval_policy':completion.candidate_hierarchy.VERSION,
            'argument_audit_protocol':completion.argument_observations.TYPED_CHAT,
            'verification_contract':completion.raw_membership_verification.FULL_SCOPE,
            'agent_source_policy':'verified_subset','extraction_protocol':completion.compact_claims.PROPOSALS}
        completion.guard(plan)
        for key,value in (('gate','G1'),('spend_scope_sha256',sha(self.parent)),('subcap_usd','10.01'),
                ('cohort_refresh',{}),('verification_deployment',{}),('agent_source_policy','all_members'),
                ('argument_audit_protocol',completion.argument_observations.JEV_SPLIT)):
            changed=deepcopy(plan);changed[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):completion.guard(changed)

    def test_invalid_predecessor_admission_stops_before_any_generation(self):
        path=self.root/'admission.json'
        write(path,{'gates':{}})
        with patch.object(completion.executor.RemoteSession,'call') as provider:
            with self.assertRaises((ValueError,KeyError)):
                completion.admissions(path,{'deployment':json.loads(self.parent.read_text())['chat_deployment']})
            provider.assert_not_called()


if __name__=='__main__':unittest.main()
