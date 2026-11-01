from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from experiments import compare_local_codex as compare
from test_portable_runtime import deployment


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.directory=self.root/'comparison'
        self.addCleanup(patch.stopall)
        patch.object(compare,'private',lambda p:None).start()
        patch.object(compare,'code_hashes',lambda:{}).start()
        patch.object(compare,'check_quota',lambda **kwargs:None).start()
        patch.object(compare,'quota_watch',lambda:nullcontext()).start()
        patch.object(compare,'experiment_lock',lambda p:nullcontext()).start()
        qwen=self.root/'deployment.json';write(qwen,deployment(self.root))
        with patch.object(compare.shutil,'which',return_value=str(self.root/'test-server')), \
             patch.object(compare.subprocess,'check_output',return_value='codex-cli synthetic'):
            compare.prepare(self.directory,qwen,'test-model','low',self.root/'ledger.sqlite','test')

    def backend(self,name):
        plan=json.loads((self.directory/'plan.json').read_text(encoding='utf-8'));root=self.directory/name
        write(root/'plan.json',{**deepcopy(plan),'deployment':plan['backends'][name],
                               'comparison_plan_sha256':sha(self.directory/'plan.json')})
        cases=json.loads((self.directory/'requests.json').read_text(encoding='utf-8'))['cases']
        write(root/'outputs.json',[{'id':c['id'],'request_sha256':digest(c['request']),
                                   'result':{'output':{'baseline':name}}} for c in cases])
        write(root/'completed.json',{'plan_sha256':sha(root/'plan.json'),'outputs_sha256':sha(root/'outputs.json')})
        return root

    def test_same_request_comparison_is_not_a_quality_gate(self):
        self.backend('codex');self.backend('qwen')
        result=compare.report(self.directory)
        self.assertEqual(len(result['cases']),8)
        self.assertFalse(result['quality_gate_passed'])
        self.assertTrue(result['semantic_review_required'])
        self.assertTrue(all(r['same_json'] is False for r in result['cases']))

    def test_resource_hold_does_not_dispatch_or_create_backend(self):
        patch.object(compare,'portable_host_observation',return_value={
            'available_mb':8192,'committed_bytes':1,'commit_limit':16*1024**3,
            'disk_free_bytes':0,'gpu_free_mb':7000}).start()
        with patch.object(compare.codex_runner,'CodexRunner') as runner:
            result=compare.run(self.directory,'codex')
        self.assertEqual(result['status'],'resource_hold')
        self.assertEqual(result['inference_calls'],0)
        runner.assert_not_called()
        self.assertFalse((self.directory/'codex').exists())

    def test_modified_request_pack_is_not_accepted(self):
        p=self.directory/'requests.json';v=json.loads(p.read_text(encoding='utf-8'))
        v['cases'][0]['request']['data']={'review_answer':'injected'};p.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'Frozen'):compare.report(self.directory)

    def test_frozen_plan_cannot_be_copied_as_a_new_run_identity(self):
        other=self.root/'copied-comparison'
        compare.shutil.copytree(self.directory,other)
        with self.assertRaisesRegex(ValueError,'Frozen'):compare.validate(other)

    def test_rebound_backend_deployment_is_rejected_even_with_new_output_hashes(self):
        root=self.backend('codex');p=root/'plan.json';v=json.loads(p.read_text(encoding='utf-8'))
        v['deployment']['model']='other-model';p.write_text(json.dumps(v))
        done=root/'completed.json';v=json.loads(done.read_text(encoding='utf-8'));v['plan_sha256']=sha(p);done.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'Stored output changed'):compare.report(self.directory)
