"""A paid truncated receipt can become a source hold, never an approval/retry."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
from unittest import TestCase
from unittest.mock import patch

from tools import source_fidelity_continuation as c
from test_source_evidence_graph import example
from commentscope.providers.openrouter_budget import SpendLedger


class SettledLengthTests(TestCase):
    def save(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path

    def make(self,root):
        policy=dict(account_id='synthetic',ledger=str(root/'money.sqlite'),maximum_usd='150',opening_charge_usd='1')
        plan=dict(spend_policy=policy,spend_scope_sha256='a'*64,deployment=c.live.remote.SOL,verification_deployment=c.live.remote.SOL,
            inputs={str(Path(c.live.__file__).resolve()):c.sha(Path(c.live.__file__))})
        self.save(root/'plan.json',plan);request=c.live.g.proposal_request(example()[1])
        actual=c.allocate(request,c.live.executor.openrouter.generation_allocation(plan['deployment'],require_explicit=True))
        stage='generation-source-evidence-proposal-'+c.digest(request)[:20]
        identity=dict(artifact_kind=c.CHECKPOINT,plan_sha256=c.sha(root/'plan.json'),stage=stage,
            request_sha256=c.digest(actual),provider=c.live.executor.openrouter.Runner.provider_identity)
        raw=dict(id='synthetic-only',model=plan['deployment']['model'],provider='OpenAI',
            choices=[dict(finish_reason='length',message=dict(content='{"units":['))],usage={'cost':0.02})
        result=dict(raw=raw['choices'][0]['message']['content'],output=None,errors=['incomplete_generation'],usage=raw['usage'],
            transport=c.live.executor.openrouter.Client(plan['deployment']).transport_record(actual,raw))
        intent=self.save(root/'checkpoints'/(c.digest(identity)+'.intent.json'),identity)
        done=self.save(intent.with_name(intent.name.replace('.intent.json','.result.json')),
            dict(identity=identity,result=result,result_sha256=c.digest(result)))
        call=self.save(root/'calls'/('0001-'+stage+'.request.json'),
            dict(request=actual,request_sha256=c.digest(actual),plan_sha256=identity['plan_sha256']))
        self.save(call.with_name(call.name.replace('.request.json','.result.json')),result)
        money=SpendLedger(**dict(path=policy['ledger'],account_id=policy['account_id'],maximum_usd='150',opening_charge_usd='1'))
        cid=money.reserve('a'*64,c.digest(actual),'0.2',run_limit_usd='150',key_remaining_usd='149');money.finish(cid,'0.02')
        session=type('SavedSession',(),dict(directory=root,plan=plan))()
        return session,request,result,done,money

    def test_exact_paid_failure_is_returned_unchanged_and_still_rejected_by_binder(self):
        with tempfile.TemporaryDirectory() as temp:
            s,req,result,done,money=self.make(Path(temp));before=money.summary()
            for _ in range(2):self.assertEqual(c.saved_length(s,'source-evidence-proposal',req),result)
            self.assertEqual(money.summary(),before)
            with self.assertRaises(ValueError):c.live.g.bind_proposal(example()[1],result)

    def test_changed_checkpoint_or_provider_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            s,req,result,done,_=self.make(Path(temp));bound=c.read_json(done)
            changed=deepcopy(bound);changed['result']['raw']='repaired';self.save(done,changed)
            with self.assertRaises(ValueError):c.saved_length(s,'source-evidence-proposal',req)
            changed=deepcopy(bound);raw=changed['result']['transport']['provider_response'];raw['provider']='Different'
            changed['result']['transport']['provider_response_sha256']=c.digest(raw);changed['result_sha256']=c.digest(changed['result']);self.save(done,changed)
            with self.assertRaises(ValueError):c.saved_length(s,'source-evidence-proposal',req)

    def test_unknown_charge_and_other_stage_never_authorize_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            s,req,_,_,money=self.make(Path(temp));cid=money.reserve('a'*64,'b'*64,'0.1',run_limit_usd='150',key_remaining_usd='149');money.finish(cid,None)
            with self.assertRaises(c.live.BudgetExhausted):c.saved_length(s,'source-evidence-proposal',req)
            with self.assertRaises(ValueError):c.saved_length(s,'runtime',req)

    def test_registered_continuation_preserves_plan_calls_money_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);s,_,_,_,money=self.make(root);before=money.summary();plan=c.sha(root/'plan.json');manifest=root/'recoveries/length/manifest.json'
            with patch.object(c.live,'guard'),patch.object(c.live.executor,'private'):
                result=c.prepare(root,manifest,user_request='Continue remaining original inventory without retry')
            self.assertEqual(result,dict(saved_failures=1,new_model_calls=0,provider_retries=0));c.validate(root,manifest)
            self.assertEqual(c.sha(root/'plan.json'),plan);self.assertEqual(money.summary(),before)
            value=c.read_json(manifest);value['provider_retries']=1;self.save(manifest,value)
            with self.assertRaises(ValueError):c.validate(root,manifest)
