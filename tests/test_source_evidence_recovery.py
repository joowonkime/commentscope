"""Synthetic interrupted requests only; no provider or key access."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest import TestCase
from unittest.mock import patch

from tools import source_evidence_recovery as recovery
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha,read_json
from commentscope.storage import write_json_exclusive as write


class HostRebootRecoveryTests(TestCase):
    def make(self,root):
        trial=recovery.trial;directory=root/'B';directory.mkdir()
        policy=dict(account_id='synthetic',ledger=str(root/'spend.sqlite'),maximum_usd='50',opening_charge_usd='0')
        plan=dict(spend_policy=policy,spend_scope_sha256=digest('synthetic owner'),arm='B',maximum_physical_requests=140,
                  deployment=deepcopy(trial.remote.SOL),verification_deployment=deepcopy(trial.remote.SOL))
        write(directory/'plan.json',plan)
        request=dict(system='synthetic',data={},schema={},max_tokens=1)
        stage,_=recovery.wire_identity(plan,'source-evidence-proposal',request)
        actual=recovery.allocate(request,trial.executor.openrouter.generation_allocation(plan['deployment'],require_explicit=True))
        request_file=directory/'calls'/('0001-'+stage+'.request.json')
        write(request_file,dict(request=actual,request_sha256=digest(actual),plan_sha256=sha(directory/'plan.json'),timeout_seconds=180))
        identity=dict(artifact_kind=recovery.CHECKPOINT_VERSION,plan_sha256=sha(directory/'plan.json'),stage=stage,
                      request_sha256=digest(actual),provider=trial.executor.openrouter.Runner.provider_identity)
        write(directory/'checkpoints'/(digest(identity)+'.intent.json'),identity)
        time=trial.executor.InferenceBudget(directory/'inference.sqlite',trial.executor.VERSION,limit_seconds=None)
        time_id=time.reserve(actual,sha(directory/'plan.json'),180)
        start=datetime.now(timezone.utc)-timedelta(minutes=30)
        db=sqlite3.connect(directory/'inference.sqlite')
        try:db.execute('UPDATE calls SET started_at=? WHERE id=?',(start.isoformat(),time_id));db.commit()
        finally:db.close()
        money=trial.executor.ledger(policy)
        money.reserve(plan['spend_scope_sha256'],digest(actual),'0.25',run_limit_usd='5',key_remaining_usd='150')
        boot=dict(boot_id='synthetic-new-kernel',boot_at=(start+timedelta(minutes=20)).isoformat())
        return directory,plan,request_file,boot,request

    def test_current_boot_and_saved_response_cannot_be_declared_lost(self):
        with tempfile.TemporaryDirectory() as temp:
            directory,plan,file,boot,_=self.make(Path(temp))
            self.assertEqual(recovery.evidence(directory,plan,file,boot)['retained_units'],250000000000)
            wrong=dict(boot,boot_at=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
            with self.assertRaises(ValueError):recovery.evidence(directory,plan,file,wrong)
            write(file.with_name(file.name.replace('.request.json','.result.json')),{'saved':'response'})
            with self.assertRaises(ValueError):recovery.evidence(directory,plan,file,boot)

    def test_full_reservation_is_retained_without_result_or_checkpoint_fabrication(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory,plan,file,boot,_=self.make(root)
            row=recovery.evidence(directory,plan,file,boot);proof=root/'recoveries/proof.json'
            write(proof,dict(version=recovery.VERSION+'-proof',request_file=str(file.relative_to(directory)),evidence=row))
            recovery.settle(directory,plan,proof);recovery.settle(directory,plan,proof)
            summary=recovery.trial.executor.ledger(plan['spend_policy']).summary(plan_sha256=plan['spend_scope_sha256'])
            self.assertEqual(summary['charged_usd'],'0.25');self.assertEqual(summary['conservative_usd'],'0.25')
            self.assertEqual(summary['reserved_calls'],0);self.assertEqual(summary['uncertain_calls'],0)
            self.assertFalse(file.with_name(file.name.replace('.request.json','.result.json')).exists())
            self.assertFalse(list((directory/'checkpoints').glob('*.result.json')))
            changed=read_json(proof);changed['evidence']['retained_units']=0;proof.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):recovery.settled(directory,plan,proof)

    def test_only_exact_original_arm_and_request_are_skipped_without_paid_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory,plan,file,boot,request=self.make(root)
            row=recovery.evidence(directory,plan,file,boot);proof=root/'recoveries/proof.json'
            write(proof,dict(version=recovery.VERSION+'-proof',request_file=str(file.relative_to(directory)),evidence=row))
            manifest_file=root/'recoveries/manifest.json';write(manifest_file,{'synthetic':True})
            manifest={'entries':[dict(arm='B',proof_file=str(proof))]}
            original=recovery.trial.Session
            for arm in ('B','A','C'):write(root/arm/'completed.json',{'synthetic':arm})
            def run_arm(directory):
                session=object.__new__(recovery.trial.Session);session.plan=dict(plan,arm=directory.name);session.seen=set()
                if directory.name=='B':
                    with self.assertRaises(recovery.PriorRequestUnavailable):session.call('source-evidence-proposal',request)
                    # A distinct request must still use the original guarded path.
                    session.call('source-evidence-proposal',dict(request,data={'different':True}))
                elif directory.name=='A':session.call('source-evidence-proposal',request)
                return {'profiles':0,'errors':0,'shared_comparison_charge':{}}
            with patch.object(recovery,'validate',return_value=manifest),patch.object(recovery.trial,'run_arm',side_effect=run_arm),\
                    patch.object(original,'call',return_value={'synthetic':True}) as provider_path:
                recovery.run(root,manifest_file)
            self.assertEqual(provider_path.call_count,2)
            self.assertIs(recovery.trial.Session,original)
