"""Offline rebinding must prove identical original model requests and outputs."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import json

from commentscope.factory import source_evidence_graph as g,source_evidence_requests as reqs,minimal_claims as mc
from test_source_evidence_graph import example,observation_example
from test_source_evidence_pipeline import candidate_output
from test_minimal_factory import extraction,membership
from tools import replay_source_role_policy as replay


class SourceRoleReplayTests(TestCase):
    def batch(self):
        source,_,_,p,o=example();v=g.verify(p,g.bind_observation(p,{'output':o}))
        cs=mc.candidates(extraction([source],{'s':['Adopt P.']}))
        members=[membership([source],cs,[dict(source_id='s',candidate_id=cs[0]['id'])])]
        b=reqs.bind_candidates(v,cs,members,{'output':candidate_output(cs)})
        old=deepcopy(v);old.pop('verification_policy');old.pop('unit_applicability')
        b['verified']=old
        for c in b['certificates']:c['verified_sha256']=replay.digest(old)
        return b,old

    def test_same_wire_rebinding_preserves_response_and_old_record(self):
        b,old=self.batch();before=deepcopy(b);new=replay.compare_graph(old)
        rebound=replay.rebind_batch(b,{'s':old},{'s':new})
        self.assertEqual(b,before)
        self.assertEqual(rebound['request_sha256'],b['request_sha256'])
        self.assertEqual(rebound['response'],b['response'])
        self.assertEqual(rebound['verified']['verification_policy'],g.VERIFICATION_POLICY)
        self.assertNotEqual(rebound['certificates'][0]['verified_sha256'],b['certificates'][0]['verified_sha256'])

    def test_changed_model_request_or_original_certificate_is_not_reused(self):
        b,old=self.batch();new=replay.compare_graph(old)
        for mutate in (lambda x:x.update(request_sha256='f'*64),
                       lambda x:x['certificates'][0].update(verified_sha256='f'*64),
                       lambda x:x['verified']['proposal']['source'].update(text='other')):
            bad=deepcopy(b);mutate(bad)
            with self.assertRaises(ValueError):replay.rebind_batch(bad,{'s':old},{'s':new})
        changed=deepcopy(old);changed['observation']['request_sha256']='f'*64
        with self.assertRaises(ValueError):replay.compare_graph(changed)

    def original(self,root):
        source,env,_,p,_=example();request=g.proposal_request(env);plan=dict(deployment=replay.remote.SOL,verification_deployment=replay.remote.SOL)
        def save(path,value):path.parent.mkdir(exist_ok=True,parents=True);path.write_text(json.dumps(value),encoding='utf-8')
        save(root/'plan.json',plan);actual=replay.allocate(request,replay.openrouter.generation_allocation(plan['deployment'],require_explicit=True))
        call=root/'calls'/('0001-generation-source-evidence-proposal-'+replay.digest(request)[:20]+'.request.json')
        save(call,dict(request=actual,request_sha256=replay.digest(actual),plan_sha256=replay.sha(root/'plan.json')))
        output=p['wire_output'];raw=dict(id='synthetic-only',model=plan['deployment']['model'],provider='OpenAI',
            choices=[dict(finish_reason='stop',message=dict(content=json.dumps(output)))],usage=dict(prompt_tokens=100,completion_tokens=20,cost=0.001))
        result=dict(output=output,raw=json.dumps(output),errors=[],usage=raw['usage'],transport=replay.openrouter.Client(plan['deployment']).transport_record(actual,raw))
        result_file=call.with_name(call.name.replace('.request.json','.result.json'));save(result_file,result)
        return plan,request,output,call,result_file

    def test_original_provider_request_and_output_are_checked_without_network(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);plan,request,output,call,result_file=self.original(root)
            replay.original_call(root,plan,'source-evidence-proposal',request,output)
            value=replay.read_json(call);value['plan_sha256']='f'*64;call.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(ValueError):replay.original_call(root,plan,'source-evidence-proposal',request,output)

    def test_duplicate_saved_calls_or_different_provider_are_rejected(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);plan,request,output,call,result_file=self.original(root)
            duplicate=call.with_name(call.name.replace('0001','0002'));duplicate.write_bytes(call.read_bytes())
            with self.assertRaises(ValueError):replay.original_call(root,plan,'source-evidence-proposal',request,output)
            duplicate.unlink();result=replay.read_json(result_file)
            result['transport']['provider_response']['provider']='Different'
            result['transport']['provider_response_sha256']=replay.digest(result['transport']['provider_response'])
            result_file.write_text(json.dumps(result),encoding='utf-8')
            with self.assertRaises(ValueError):replay.original_call(root,plan,'source-evidence-proposal',request,output)
