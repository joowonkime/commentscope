from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch
from experiments.minimal_comparison_probe import checked_call, reused_content_memberships
from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from test_minimal_factory import extraction, membership
import json


class CapacityArtifactTests(unittest.TestCase):
    def test_same_runtime_stage_and_request_keep_separate_completed_measurements(self):
        class Runner:
            seq=0
            def call(self,stage,request):self.seq+=1;return self.seq
        runner=Runner()
        with tempfile.TemporaryDirectory() as root, patch('experiments.minimal_comparison_probe.measure',return_value={'fits':True}):
            directory=Path(root)
            for question in ('position','reasons','position'):
                checked_call(directory,runner,'runtime',{'question':question})
            self.assertEqual(runner.seq,3)
            self.assertEqual(len(list((directory/'capacity').glob('*.json'))),3)

    def reuse_fixture(self,root):
        source={'id':'s','text':'Adopt P.','parent':None}
        candidates=mc.candidates(extraction([source],{'s':['Adopt P.']}))
        pairs=[{'source_id':'s','candidate_id':candidates[0]['id']}]
        batch=membership([source],candidates,pairs)
        deployment={'model':'fixed'};root=Path(root)
        write(root/'plan.json',{'deployment':deployment})
        plan_hash=sha(root/'plan.json');write(root/'completed.json',{'plan_sha256':plan_hash})
        path=root/'content/memberships.json';write(path,[batch])
        req=mm.membership_request([source],candidates,pairs)
        request_path=root/'calls/0001-content-member-s.request.json'
        result_path=request_path.with_name(request_path.name.replace('.request.json','.result.json'))
        write(request_path,{'plan_sha256':plan_hash,'request':req,'request_sha256':digest(req)})
        write(result_path,{'output':batch['output'],'errors':[]})
        return path,[source],candidates,deployment,request_path,result_path

    def test_reuse_requires_same_model_exact_request_response_and_source_coverage(self):
        with tempfile.TemporaryDirectory() as root:
            path,sources,candidates,deployment,request_path,result_path=self.reuse_fixture(root)
            batches,proof=reused_content_memberships(path,sources,candidates,deployment)
            self.assertEqual(len(batches),1);self.assertEqual(proof['fresh_membership_calls'],0)
            with self.assertRaises(ValueError):reused_content_memberships(path,sources,candidates,{'model':'changed'})
            changed=deepcopy(sources);changed[0]['text']='Reject P.'
            with self.assertRaises(ValueError):reused_content_memberships(path,changed,candidates,deployment)
            req=json.loads(request_path.read_text());req['request']['max_tokens']+=1
            request_path.write_text(json.dumps(req))
            with self.assertRaises(ValueError):reused_content_memberships(path,sources,candidates,deployment)

    def test_changed_completed_response_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as root:
            path,sources,candidates,deployment,request_path,result_path=self.reuse_fixture(root)
            result=json.loads(result_path.read_text());result['output']['decisions'][0]['relation']='opposed'
            result_path.write_text(json.dumps(result))
            with self.assertRaises(ValueError):reused_content_memberships(path,sources,candidates,deployment)


if __name__=='__main__':unittest.main()
