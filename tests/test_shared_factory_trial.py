"""Shared development phases inherit money/history and cannot qualify gates."""
from copy import deepcopy
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import shared_factory_trial as trial
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from experiments import minimal_factory_review
import test_actual24_development as development_fixture


class SharedTrialTests(unittest.TestCase):
    def setUp(self):
        self.f=development_fixture.Actual24DevelopmentTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.file=self.f.root/'trial.json'
        self.authorization=trial.authorize(self.file,self.f.auth,user_request='ㄱㄱㄱ')
        self.plan=deepcopy(self.f.plan)
        self.plan.update(artifact_kind=trial.VERSION,discovery_mode='shared',membership_mode='raw',
            extraction_protocol=None,argument_audit_protocol=trial.obs.SHARED_TYPED_CHAT,
            agent_source_policy='candidate_verified_subset',membership_retrieval_policy=trial.cc.ALIAS_RETRIEVAL,
            stage_aliases=deepcopy(trial.ALIASES),opening_scope_charge_usd=self.authorization['opening_scope_charge_usd'],
            trial={'file':str(self.file),'sha256':sha(self.file),'authorization':self.authorization})

    def test_two_runs_share_one_cumulative_trial_ceiling_and_the_original_owner(self):
        trial.guard(self.plan)
        money=trial.executor.ledger(self.plan['spend_policy']);scope=self.plan['spend_scope_sha256']
        first=trial.executor.SubcapLedger(money,self.plan)
        call=first.reserve(scope,'a'*64,'1',run_limit_usd='8',key_remaining_usd='37');money.finish(call,'1')
        second=trial.executor.SubcapLedger(money,deepcopy(self.plan))
        with self.assertRaises(trial.executor.BudgetExhausted):
            second.reserve(scope,'b'*64,'0.500000001',run_limit_usd='8',key_remaining_usd='36')
        self.assertEqual(money.summary()['charged_usd'],'14')
        self.assertEqual(scope,sha(self.f.parent))

    def test_cap_reset_or_role_contract_tampering_is_rejected(self):
        for key,value in [('opening_scope_charge_usd','1'),('subcap_usd','2'),
                ('discovery_mode','free'),('argument_audit_protocol',trial.obs.TYPED_CHAT),
                ('agent_source_policy','all_members'),('stage_aliases',{}),('formal_admission_eligible',True)]:
            plan=deepcopy(self.plan);plan[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):trial.guard(plan)
        changed=deepcopy(self.plan);changed['membership_evidence_protocol']='unregistered'
        with self.assertRaises(ValueError):trial.guard(changed)

    def test_same_payload_raw_membership_stage_is_shared_but_independent_reviews_are_not(self):
        suffix='-'+'a'*20
        self.assertEqual(trial.mapped_stage('nomination-raw'+suffix),trial.mapped_stage('membership-initial-raw'+suffix))
        self.assertEqual(trial.mapped_stage('shared-discovery'+suffix),'core'+suffix)
        self.assertEqual(trial.mapped_stage('argument-owner'+suffix),'argument-owner'+suffix)
        self.assertEqual(trial.mapped_stage('raw-own-evidence'+suffix),'raw-own-evidence'+suffix)
        self.assertNotEqual(trial.mapped_stage('membership-initial-raw-'+ 'b'*20),trial.mapped_stage('nomination-raw'+suffix))

    def test_formal_review_refuses_a_completed_shared_development_artifact(self):
        run=self.f.root/'run';write(run/'plan.json',self.plan);write(run/'completed.json',{'execution_complete':True})
        with self.assertRaisesRegex(ValueError,'Completed and immutable run required'):minimal_factory_review.load_run(run)

    def test_authorization_cannot_overwrite_trial_or_reset_history(self):
        with self.assertRaises(ValueError):trial.authorize(self.file,self.f.auth,user_request='ㄱㄱㄱ')
        self.assertEqual(trial.executor.ledger(self.plan['spend_policy']).summary()['charged_usd'],'13')
        self.assertEqual(self.authorization['maximum_usd'],'1.50')

    def test_larger_registered_sample_remains_nonformal_and_uses_the_same_trial(self):
        plan=deepcopy(self.plan);plan['gate']='G3';trial.guard(plan)
        self.assertFalse(plan['formal_admission_eligible'])
        self.assertEqual(plan['trial']['sha256'],self.plan['trial']['sha256'])

    def test_proposal_pause_read_and_full_continuation_keep_one_plan_and_all_sources(self):
        self.proposal_pause_and_full_continuation()

    def test_batched_development_flows_through_proposal_cost_gate_and_runtime(self):
        self.proposal_pause_and_full_continuation(batch_membership=True)

    def test_jev_role_binding_rejects_mixed_transports_or_foreign_deployment(self):
        from commentscope.factory import jev_membership
        from commentscope.providers import openrouter_decisions
        plan=deepcopy(self.plan);plan.update(membership_judge_protocol=jev_membership.VERSION,
            membership_deployment=deepcopy(openrouter_decisions.DEPLOYMENT))
        trial.guard(plan)
        changed=deepcopy(plan);changed['membership_deployment']['model']='different'
        with self.assertRaises(ValueError):trial.guard(changed)
        changed=deepcopy(plan);changed['membership_batch_protocol']=trial.source_membership_batch.VERSION
        with self.assertRaises(ValueError):trial.guard(changed)

    def test_jev_development_keeps_proposal_cost_gate_and_runtime(self):
        self.proposal_pause_and_full_continuation(jev_judging=True)

    def proposal_pause_and_full_continuation(self,*,batch_membership=False,jev_judging=False):
        import test_minimal_pipeline as pipeline_fixture
        from test_shared_typed_pipeline import SharedRunner
        from experiments.grounding_contract_demo import MODEL
        helper=pipeline_fixture.MinimalPipelineTests();helper.setUp()
        directory=self.f.root/'run';plan=deepcopy(self.plan)
        plan.update(classifier=MODEL,documents=[],selections=[],scope_ids=[str(i) for i in range(6)],
            resource_policy=trial.host_resources.HTTP_API_POLICY,snapshot='scripted-unused',
            verification_contract=trial.executor.raw_membership_verification.FULL_SCOPE,questions=trial.executor.QUESTIONS)
        plan['membership_evidence_protocol']=trial.executor.raw_membership_verification.QUALIFIED_CONTEXT
        write(directory/'plan.json',plan)
        if batch_membership:
            # Write a distinct immutable plan; scalar fixtures are not retagged.
            from test_source_membership_batch import BatchRunner
            directory=self.f.root/'batch-run'
            plan.update(membership_batch_protocol=trial.source_membership_batch.VERSION,
                        stage_aliases=deepcopy(trial.BATCH_ALIASES),run_directory=str(directory.resolve()))
            write(directory/'plan.json',plan)
            runner=BatchRunner()
        elif jev_judging:
            from test_jev_membership import JevRunner
            directory=self.f.root/'jev-run'
            plan.update(membership_judge_protocol=trial.jev_membership.VERSION,
                        membership_deployment=deepcopy(trial.decisions.DEPLOYMENT),run_directory=str(directory.resolve()))
            write(directory/'plan.json',plan);runner=JevRunner()
        else:runner=SharedRunner()
        runner.embed=helper.embed;runner.inspect=helper.inspect
        runner.storage=SimpleNamespace(before_write=lambda value:None)
        runner.money=trial.executor.ledger(self.plan['spend_policy'])
        with patch.object(trial,'validate',return_value=plan),\
                patch.object(trial.cost_review,'verify_profile'),\
                patch.object(trial,'Session',return_value=runner) as sessions,\
                patch.object(trial.executor,'quota_watch',return_value=nullcontext()),\
                patch.object(trial.host_resources,'watch',side_effect=lambda *a,**k:nullcontext()),\
                patch.object(trial.executor,'provider_preflight'),patch.object(trial.executor,'embedding_preflight'),\
                patch.object(trial,'load_snapshot',return_value=SimpleNamespace(snapshot=helper.snapshot)):
            first=trial.run(directory,proposals_only=True);calls=len(runner.calls)
            self.assertEqual(first['candidate_count'],2);self.assertFalse(first['execution_complete'])
            self.assertFalse(list((directory/'attempts').glob('*.failed.json')))
            self.assertEqual(trial.run(directory,proposals_only=True),first)
            self.assertEqual(len(runner.calls),calls)
            from test_factory_cost_plan import cost_workload,cost_profile
            workload=self.f.root/'cost-work.json';profile=self.f.root/'cost-profile.json'
            write(workload,cost_workload());profile_value=cost_profile(plan)
            profile_value['stages']['membership-source-batch']['maximum_batch_targets']=6
            write(profile,profile_value)
            trial.cost_review.prepare_review(directory,workload,[profile])
            done=trial.run(directory)
            self.assertEqual(done['compiled_agents'],2);self.assertEqual(done['runtime_turns'],6)
            output=read_json(directory/'artifacts/output.json')
            self.assertEqual(output['membership_evidence_protocol'],trial.executor.raw_membership_verification.QUALIFIED_CONTEXT)
            if batch_membership:self.assertEqual(output['membership_batch_protocol'],trial.source_membership_batch.VERSION)
            if jev_judging:self.assertEqual(output['membership_judge_protocol'],trial.jev_membership.VERSION)
            self.assertTrue(done['same_plan_resume']);self.assertFalse(done['formal_admission_eligible'])
            self.assertEqual(trial.run(directory),done)
            self.assertEqual(sessions.call_count,2)
            self.assertEqual(runner.money.summary()['charged_usd'],'13')

    def test_full_execution_without_cost_plan_stops_before_session_or_provider(self):
        directory=self.f.root/'no-cost-review';write(directory/'plan.json',self.plan)
        with patch.object(trial,'validate',return_value=self.plan),\
                patch.object(trial.executor,'quota_watch',return_value=nullcontext()),\
                patch.object(trial,'Session') as session,patch.object(trial.executor,'provider_preflight') as preflight:
            with self.assertRaisesRegex(ValueError,'cost-preflight'):trial.run(directory)
        session.assert_not_called();preflight.assert_not_called()


if __name__=='__main__':unittest.main()
