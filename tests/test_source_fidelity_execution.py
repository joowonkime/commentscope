"""Fixed-scope cumulative execution controls without keys or provider calls."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json
import tempfile
from unittest import TestCase
from unittest.mock import patch,MagicMock

from tools import source_fidelity_validation as live,prepare_source_fidelity_validation as prep
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha,read_json
from commentscope.providers import remote_verification as remote
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.providers.budget import BudgetExhausted
from commentscope.file_integrity import source_code_hashes
from test_source_evidence_graph import example


class CumulativeExecutionTests(TestCase):
    def save(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path

    def make(self,root):
        policy={'account_id':'synthetic','ledger':str(root/'money.sqlite'),'maximum_usd':'150','opening_charge_usd':'1'}
        policy_file=self.save(root/'current-policy.json',policy);now=datetime.now(timezone.utc)
        auth=dict(version=live.VERSION,user_request='Continue using extended cumulative150',started_at=now.isoformat(),
            deadline=(now+timedelta(hours=1)).isoformat(),maximum_usd='150',shared_policy_file=str(policy_file),
            shared_policy_sha256=sha(policy_file),generation_deployment=remote.SOL,opening_account_charge_usd='25',historical_charges_preserved=True)
        auth_file=self.save(root/'authorization.json',auth)
        p=dict(run_directory=str(root),authorization={'file':str(auth_file),'sha256':sha(auth_file),'authorization':auth},
            maximum_cost_usd='150',subcap_usd='150',opening_scope_charge_usd='0',spend_policy=policy,
            spend_scope_sha256=sha(auth_file),source_evidence_protocol=live.g.VERSION,
            verification_deployment=deepcopy(remote.SOL),deployment=deepcopy(remote.SOL),cross_run_response_reuse=False,
            maximum_physical_requests=800,expires_at='2099-01-01T00:00:00Z',inputs={},code_sha256=source_code_hashes(),
            allowed_stage_families=list(live.ALLOWED))
        self.save(root/'plan.json',p);self.save(root/'frozen.json',{'plan_sha256':sha(root/'plan.json')});return p

    def test_cumulative_guard_does_not_reopen_old_small_caps_or_refund_prior_charges(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=self.make(root);money=MagicMock();money.summary.return_value={'charged_usd':'25'}
            with patch.object(live.executor,'ledger',return_value=money):
                live.guard(p)
                for field,value in [('maximum_cost_usd','6'),('subcap_usd','6'),('spend_scope_sha256','a'*64),('cross_run_response_reuse',True)]:
                    wrong=deepcopy(p);wrong[field]=value
                    with self.assertRaises(ValueError):live.guard(wrong)
                money.summary.return_value={'charged_usd':'24.99'}
                with self.assertRaises(ValueError):live.guard(p)
                money.summary.return_value={'charged_usd':'25'}
                with self.assertRaises(TimeoutError):live.guard(p,call_seconds=3600)

    def test_changed_on_disk_plan_is_rejected_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=self.make(root);money=MagicMock();money.summary.return_value={'charged_usd':'25'}
            self.save(root/'plan.json',{**p,'maximum_physical_requests':900})
            with patch.object(live.executor,'ledger',return_value=money),self.assertRaises(ValueError):live.guard(p)

    def session(self,request):
        s=object.__new__(live.Session);s.seen=set();s.phase='controls';s.control_requests={digest(request)}
        s.pilot_ids={'s'};s.plan={'eligible_source_ids':['s'],'maximum_physical_requests':800};return s

    def test_scopes_are_closed_and_pilot_factory_calls_keep_same_checkpoint_identity(self):
        _,env,_,p,_=example();audit=live.g.observation_request(p);s=self.session(audit)
        with patch.object(live.executor.RemoteSession,'call',return_value={'synthetic':True}) as parent:
            s.call('source-evidence-observation',audit)
            with self.assertRaises(ValueError):s.call('core',{})
            s.phase='profiling';request=live.g.proposal_request(env)
            s.call('source-evidence-proposal',request)
            s.phase='factory';s.call('source-evidence-proposal-'+digest(request)[:20],request)
            self.assertEqual(parent.call_args_list[-2],parent.call_args_list[-1])
            self.assertEqual(len(s.seen),2)
            wrong=deepcopy(request);wrong['data']['ORIGINAL']['source_id']='foreign'
            with self.assertRaises(ValueError):s.call('source-evidence-proposal',wrong)
            s.phase='unregistered'
            with self.assertRaises(ValueError):s.call('source-evidence-proposal',request)

    def test_credit_reconciliation_preserves_same_database_opening_and_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'money.sqlite';old={'account_id':'synthetic','ledger':str(path),'maximum_usd':'50','opening_charge_usd':'1'}
            ledger=SpendLedger(path,'synthetic',maximum_usd='50',opening_charge_usd='1')
            cid=ledger.reserve('a'*64,'b'*64,'0.3',run_limit_usd='5',key_remaining_usd='140');ledger.finish(cid,'0.2')
            old_file=self.save(root/'old-plan.json',{'spend_policy':old});dest=root/'current-policy.json'
            with patch.object(live.executor,'private'),patch.object(live.executor,'key_metadata',return_value={'limit':150,'limit_remaining':130,'usage':20}):
                result=live.reconcile(old_file,dest,user_request='Use extended team credit cumulatively')
                repeated=live.reconcile(old_file,dest,user_request='Use extended team credit cumulatively')
            self.assertEqual(result,repeated);self.assertEqual(read_json(old_file)['spend_policy']['maximum_usd'],'50')
            self.assertEqual(read_json(dest),{**old,'maximum_usd':'150'})
            self.assertEqual(result['account']['charged_usd'],'1.2')
            self.assertEqual(result['account']['remaining_usd'],'148.8');self.assertEqual(result['new_model_calls'],0)

    def test_whole_controls_must_fit_current_balance_before_new_authorization_is_written(self):
        fixture=read_json(Path(__file__).parent/'fixtures/source-fidelity-controls-v1.json')
        pack=prep.controls(fixture,remote.SOL)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old_policy={'account_id':'synthetic','ledger':str(root/'money.sqlite'),'maximum_usd':'50','opening_charge_usd':'1'}
            old=self.save(root/'old-plan.json',{'spend_policy':old_policy,'deployment':remote.SOL})
            packet=self.save(root/'packet.json',{'controls':pack,'inputs':{}});policy=self.save(root/'policy.json',{**old_policy,'maximum_usd':'150'})
            ledger=MagicMock();ledger.summary.return_value={'remaining_usd':'124','charged_usd':'26','reserved_calls':0,'uncertain_calls':0}
            with patch.object(live.executor,'private'),patch.object(live.executor,'ledger',return_value=ledger),patch.object(live.executor,'key_metadata',return_value={'limit':150,'limit_remaining':1}),patch.object(live.executor,'provider_preflight') as provider:
                with self.assertRaises(BudgetExhausted):live.prepare(root/'new',old,packet,policy,user_request='Continue')
                provider.assert_not_called()
            self.assertFalse((root/'new/authorization.json').exists())

    def test_completed_validation_is_read_only_and_tampering_never_authorizes_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=self.save(root/'plan.json',{'synthetic':True})
            report={'controls':{'planned_cases':16},'semantic_adoption':False}
            artifact=self.save(root/'artifacts/validation-report.json',report)
            self.save(root/'completed.json',dict(plan_sha256=sha(p),report=report,artifacts={'artifacts/validation-report.json':sha(artifact)}))
            with patch.object(live,'guard',side_effect=AssertionError('No new execution')):
                self.assertEqual(live.run(root),report)
                artifact.write_text('changed')
                with self.assertRaises(ValueError):live.run(root)
