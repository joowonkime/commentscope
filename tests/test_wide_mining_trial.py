"""Whole-input scope and a new explicit phase cannot erase old money or qualify gates."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock,patch

from tools import wide_mining_trial as wide
from commentscope.factory.claim_clusters import sha,read_json
from commentscope.storage import write_json_exclusive as write
import test_factory_completion as fixtures


class WideMiningTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.CompletionPolicyTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root;self.auth_file=self.root/'wide-auth.json';self.observation=self.root/'key.json'
        write(self.observation,{'key_metadata':{'limit':150,'limit_remaining':137},'new_model_calls':0})
        self.ids=['C'+str(i).zfill(4) for i in range(999)]
        self.source_map={sid:{'id':sid,'text':'Fictional source '+sid,'parent':None} for sid in self.ids}
        self.snapshot_file=self.root/'snapshot.json';write(self.snapshot_file,{'synthetic_fixture':True})
        self.snapshot=SimpleNamespace(usage=SimpleNamespace(expires_at='2099-01-01T00:00:00Z'))
        self.bound={**self.f.bound,'base_scope_refresh':{'synthetic_fixture':True}}
        self.addCleanup(patch.stopall)
        patch.object(wide.cohort_refresh,'bind',return_value=(self.snapshot,self.snapshot_file,{},self.bound)).start()
        patch.object(wide,'sources',return_value=self.source_map).start()

    def authorize(self,**kwargs):
        return wide.authorize(self.auth_file,self.f.parent,self.f.cohort,self.observation,
            user_request='Broaden the actual comment input pool; budget increased.',**kwargs)

    def plan(self):
        auth=self.authorize()
        return {'artifact_kind':wide.VERSION,'mode':'development','gate':wide.GATE,
            'authorization':{'file':str(self.auth_file),'sha256':sha(self.auth_file),'authorization':auth},
            'formal_admission_eligible':False,'quality_gate_passed':False,'admission_file':None,
            'spend_scope_sha256':sha(self.auth_file),'spend_policy':read_json(self.f.policy),
            'maximum_cost_usd':'15','subcap_usd':'15','opening_scope_charge_usd':'0',
            'deployment':auth['generation_deployment'],'verification_deployment':wide.executor.remote.SOL,
            'embedding_deployment':wide.executor.remote.EMBEDDING,'role_registry':wide.executor.remote.ROLES,
            'membership_deployment':wide.trial.decisions.DEPLOYMENT,'membership_judge_protocol':wide.trial.jev_membership.VERSION,
            'membership_search_policy':deepcopy(wide.POLICY),'argument_audit_protocol':wide.trial.obs.SHARED_TYPED_CHAT,
            'agent_source_policy':'candidate_verified_subset','extraction_protocol':None,
            'membership_retrieval_policy':wide.trial.cc.ALIAS_RETRIEVAL,'discovery_mode':'shared','membership_mode':'raw',
            'membership_evidence_protocol':wide.executor.raw_membership_verification.QUALIFIED_CONTEXT,
            'stage_aliases':deepcopy(wide.trial.ALIASES),'cohort_refresh':self.bound,
            'processing_count':999,'canonical_population':999,'scope_ids':self.ids,
            'classifier':{},'inputs':{},'documents':[],'fact_benchmark':str(self.root/'fact40/plan.json')}

    def test_new_grant_retains_old_scope_charge_and_the_shared_account(self):
        money=wide.executor.ledger(read_json(self.f.policy));old=sha(self.f.parent)
        call=money.reserve(old,'a'*64,'0.5',run_limit_usd='8',key_remaining_usd='137');money.finish(call,'0.1')
        auth=self.authorize();wide.authorization(auth)
        call=money.reserve(sha(self.auth_file),'b'*64,'0.5',run_limit_usd='15',key_remaining_usd='137');money.finish(call,'0.2')
        self.assertEqual(auth['opening_account_charge_usd'],'13.1')
        self.assertEqual(auth['opening_parent_scope_charge_usd'],'0.1')
        self.assertEqual(money.summary()['charged_usd'],'13.3')
        self.assertEqual(money.summary(plan_sha256=old)['charged_usd'],'0.1')

    def test_grant_rejects_more_than_fifteen_stale_funding_or_overwrite(self):
        with self.assertRaises(ValueError):self.authorize(maximum_usd='15.01')
        self.authorize()
        with self.assertRaises(ValueError):self.authorize()
        self.observation.write_text(json.dumps({'key_metadata':{'limit':50,'limit_remaining':37}}))
        with self.assertRaises(ValueError):wide.authorization(read_json(self.auth_file))

    def test_wrong_whole_pool_size_stops_before_authorization(self):
        with patch.object(wide,'sources',return_value={sid:self.source_map[sid] for sid in self.ids[:24]}):
            with self.assertRaises(ValueError):self.authorize()
        self.assertFalse(self.auth_file.exists())

    def test_sample_substitution_model_switch_and_formal_promotion_are_rejected(self):
        plan=self.plan();wide.guard(plan)
        for key,value in [('scope_ids',self.ids[:24]),('processing_count',24),('formal_admission_eligible',True),
                ('gate','G4'),('subcap_usd','16'),('membership_search_policy',{}),('verification_deployment',{})]:
            with self.subTest(key=key),self.assertRaises(ValueError):wide.guard({**plan,key:value})

    def test_preparation_uses_all_registered_ids_instead_of_template_g1(self):
        plan=self.plan();template={**plan,'artifact_kind':wide.executor.VERSION,'mode':'factory','gate':'G1',
            'scope_ids':self.ids[:12],'code_sha256':{}}
        template_file=self.root/'old/plan.json';write(template_file,template)
        write(template_file.parent/'artifacts/output.json',{'synthetic_fixture':True})
        write(template_file.parent/'completed.json',{'plan_sha256':sha(template_file),
            'output_sha256':sha(template_file.parent/'artifacts/output.json')})
        with patch.object(wide.executor,'model_identity',return_value={}),patch.object(wide.executor,'replay_benchmark'),\
                patch.object(wide.executor,'provider_preflight',return_value={}),patch.object(wide.executor,'embedding_preflight',return_value={}),\
                patch.object(wide.trial.decisions,'preflight',return_value={}),patch.object(wide,'source_code_hashes',return_value={}),\
                patch.object(wide.executor,'archive_sources'),patch.object(wide,'validate',side_effect=lambda p:read_json(p/'plan.json')):
            prepared=wide.prepare(self.root/'wide',template_file,self.auth_file)
        self.assertEqual(prepared['scope_ids'],self.ids)
        self.assertIn('C0998',prepared['scope_ids'])
        self.assertEqual(prepared['processing_count'],999)
        self.assertEqual(prepared['membership_search_policy']['maximum_sources'],120)
        self.assertFalse(prepared['formal_admission_eligible'])

    def test_typed_dispatch_calls_the_registered_phase_guard_before_provider(self):
        session=wide.trial.Session.__new__(wide.trial.Session)
        session.plan={'membership_judge_protocol':wide.trial.jev_membership.VERSION};session.dispatch=Mock()
        session.authorization_guard=Mock(side_effect=TimeoutError('phase ended'))
        with patch.object(wide.trial.decisions,'wire_sha256',return_value='a'*64),\
                patch.object(wide.executor,'check_quota'),patch.object(wide.trial,'guard') as old_guard:
            with self.assertRaises(TimeoutError):session.decide('membership-jev-'+'a'*20,{})
        session.authorization_guard.assert_called_once();old_guard.assert_not_called()

    def test_original_fixed_trial_guard_does_not_accept_the_new_phase(self):
        plan=self.plan()
        with self.assertRaises((ValueError,KeyError)):wide.trial.guard(plan)

    def test_completed_proposal_replay_preserves_kind_and_never_opens_provider(self):
        run=self.root/'proposal';plan=self.plan();plan.update(run_directory=str(run.resolve()),cross_run_response_reuse=False)
        write(run/'plan.json',plan);write(run/'artifacts/initial-candidates.json',[])
        ready={'artifact_kind':wide.VERSION+'-proposal-ready','formal_admission_eligible':False,
            'plan_sha256':sha(run/'plan.json'),'candidates_sha256':sha(run/'artifacts/initial-candidates.json'),'candidate_count':0}
        write(run/'proposal-ready.json',ready)
        with patch.object(wide,'validate',return_value=plan),patch.object(wide.trial.executor,'quota_watch',return_value=nullcontext()),\
                patch.object(wide,'Session') as provider:
            self.assertEqual(wide.run(run,proposals_only=True),ready);provider.assert_not_called()
            changed={**ready,'artifact_kind':wide.trial.VERSION+'-proposal-ready'}
            (run/'proposal-ready.json').write_text(json.dumps(changed))
            with self.assertRaises(ValueError):wide.run(run,proposals_only=True)


if __name__=='__main__':unittest.main()
