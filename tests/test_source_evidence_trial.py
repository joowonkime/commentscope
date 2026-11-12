"""No provider calls: shared-cap, expiry, changed input and physical limits."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch,MagicMock

from tools import source_evidence_trial as trial
from commentscope.storage import write_json_exclusive as write
from commentscope.factory.claim_clusters import sha


class SourceEvidenceTrialTests(TestCase):
    def test_resume_uses_fresh_resource_attempt_without_deleting_legacy_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'resources/started.json';write(old,{'original':True});original_sha=sha(old)
            first=trial.resource_attempt(root);write(first/'started.json',{'attempt':1})
            second=trial.resource_attempt(root)
            self.assertNotEqual(first,second);self.assertTrue(second.is_dir())
            self.assertEqual(sha(old),original_sha)
            self.assertTrue((first/'started.json').exists());self.assertFalse((second/'started.json').exists())

    def make(self,root):
        policy={'account_id':'synthetic','ledger':'synthetic.sqlite','maximum_usd':'50','opening_charge_usd':'0'}
        write(root/'policy.json',policy)
        now=datetime.now(timezone.utc)
        auth=dict(version=trial.VERSION,user_request='Run bounded comparison',started_at=now.isoformat(),deadline=(now+timedelta(hours=1)).isoformat(),
            maximum_usd='5.00',historical_charges_preserved=True,shared_policy_file=str(root/'policy.json'),shared_policy_sha256=sha(root/'policy.json'),
            generation_deployment=deepcopy(trial.remote.SOL),opening_account_charge_usd='20.00')
        write(root/'auth.json',auth)
        binding=dict(file=str(root/'auth.json'),sha256=sha(root/'auth.json'),authorization=auth)
        return dict(authorization=binding,spend_scope_sha256=binding['sha256'],maximum_cost_usd='5.00',subcap_usd='5.00',
            spend_policy=policy,cross_run_response_reuse=False,arm='B',expires_at='2099-01-01T00:00:00Z',inputs={},
            source_evidence_protocol=trial.graph.VERSION,
            verification_deployment=deepcopy(trial.remote.SOL),deployment=deepcopy(trial.remote.SOL))

    def test_scope_cannot_refund_previous_charges_or_change_caps(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.make(Path(temp))
            money=MagicMock();money.summary.return_value={'charged_usd':'20.00'}
            with patch.object(trial.executor,'ledger',return_value=money):
                trial.guard(p)
                for field,value in [('maximum_cost_usd','6'),('subcap_usd','6'),('spend_scope_sha256','0'*64),('cross_run_response_reuse',True)]:
                    wrong=deepcopy(p);wrong[field]=value
                    with self.assertRaises(ValueError):trial.guard(wrong)
                money.summary.return_value={'charged_usd':'19.99'}
                with self.assertRaises(ValueError):trial.guard(p)

    def test_expired_window_cannot_cover_another_call(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.make(Path(temp));money=MagicMock();money.summary.return_value={'charged_usd':'20.00'}
            with patch.object(trial.executor,'ledger',return_value=money):
                with self.assertRaises(TimeoutError):trial.guard(p,call_seconds=3600)
                p['inputs'][str(Path(temp)/'policy.json')]='0'*64
                with self.assertRaises(ValueError):trial.guard(p)

    def test_physical_limit_reuses_only_exact_request_identity(self):
        session=object.__new__(trial.Session);session.seen=set();session.plan={'maximum_physical_requests':1}
        with patch.object(trial.executor.RemoteSession,'call',return_value={'synthetic':True}):
            session.call('core',{});session.call('core',{})
            with self.assertRaises(trial.BudgetExhausted):session.call('core',{'new':True})

    def test_archived_relative_input_keeps_exact_hash_after_worktree_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'data').mkdir();snapshot=root/'data/input.json';snapshot.write_text('original')
            plan=root/'runs/cohort/plan.json';plan.parent.mkdir(parents=True);plan.write_text('{}')
            self.assertEqual(trial.archived_input(plan,'data/input.json',sha(snapshot)),snapshot.resolve())
            with self.assertRaises(ValueError):trial.archived_input(plan,'data/input.json','0'*64)

    def completed(self,root):
        write(root/'plan.json',{'synthetic':True})
        report={'profiles':0,'formal_admission':False,'quality_gate_passed':False}
        write(root/'artifacts/report.json',report)
        write(root/'artifacts/runtime.json',{'turns':[]})
        write(root/'completed.json',dict(plan_sha256=sha(root/'plan.json'),report=report,
            artifacts={str(p.relative_to(root)):sha(p) for p in (root/'artifacts').glob('*.json')}))
        return report

    def test_completed_same_plan_is_read_only_without_provider_or_money_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);report=self.completed(root)
            with patch.object(trial,'validate',side_effect=AssertionError('No new execution')):
                self.assertEqual(trial.run_arm(root),report)

    def test_completed_report_rejects_changed_plan_or_downstream_artifacts(self):
        for target in ('plan.json','artifacts/report.json','artifacts/runtime.json'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);self.completed(root)
                (root/target).write_text('{"changed":true}')
                with self.assertRaises(ValueError):trial.run_arm(root)
