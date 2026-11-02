"""Fixed-scope qualification boundaries using authored offline artifacts."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch
from commentscope.factory.claim_clusters import sha
from commentscope.factory.framed_corpus import sources
from commentscope.storage import write_json_exclusive as write
from commentscope.factory.automatic_contract import digest
from experiments import openrouter_factory_pipeline as executor
from experiments import minimal_factory_pipeline as prior, minimal_factory_review as review
import test_openrouter_factory_pipeline as fixture


class RemoteGateTests(unittest.TestCase):
    setUp = fixture.OpenRouterExecutorTests.setUp

    def samples(self):
        comments=tuple(replace(self.snapshot.comments[0],comment_id='s'+str(i),text_original=f'Consider separate action {i}.',parent_id=None) for i in range(999))
        snapshot=replace(self.snapshot,comments=comments)
        path=self.root/'real-snapshot.json';write(path,snapshot.to_dict())
        ids=sorted(sources(snapshot));self.assertEqual(len(ids),999)
        manifest=self.root/'samples.json'
        write(manifest,{'snapshot':str(path),'snapshot_sha256':sha(path),'canonical_population':999,
                        'development':{'source_ids':ids[:24]},'holdout':{'source_ids':ids[24:120]}})
        patch.object(executor,'SAMPLES',manifest,create=True).start()
        return snapshot,ids,manifest

    def prepare_gate(self,gate,admission=None):
        return executor.prepare(self.run_dir,self.deployment,self.materials,self.policy,0.5,
                                gate=gate,admission_file=admission)

    def test_cannot_start_larger_gate_without_prior_full_review(self):
        for gate in ('G2','G3','G4'):
            with self.subTest(gate=gate),self.assertRaises(ValueError):self.prepare_gate(gate)
        self.time_budget.call.assert_not_called()

    def test_fixed_real_scopes_are_24_96_and_999_without_runtime_labels(self):
        snapshot,ids,manifest=self.samples()
        with patch.object(executor,'check_admission') as admit:
            for gate,count,expected in [('G2',24,ids[:24]),('G3',96,ids[24:120]),('G4',999,ids)]:
                self.run_dir=self.root/gate
                plan=self.prepare_gate(gate,manifest)
                self.assertEqual(plan['scope_ids'],expected)
                self.assertEqual(plan['processing_count'],count)
                self.assertEqual(plan['canonical_population'],999)
                self.assertFalse(plan['reference_runtime_input'])
                self.assertNotIn('meaning_reference',plan)
                self.assertEqual(executor.validate(self.run_dir,plan).to_dict(),snapshot.to_dict())
            self.assertEqual(admit.call_count,6)
        self.time_budget.call.assert_not_called()

    def test_changed_snapshot_is_rejected_before_plan_or_dispatch(self):
        snapshot,ids,manifest=self.samples()
        import json
        samples=executor.read_json(manifest);samples['snapshot_sha256']='0'*64
        manifest.write_text(json.dumps(samples))
        with patch.object(executor,'check_admission'),self.assertRaises(ValueError):self.prepare_gate('G2',manifest)
        self.assertFalse((self.run_dir/'plan.json').exists());self.time_budget.call.assert_not_called()

    def test_duplicate_or_wrong_sample_scope_is_not_a_smaller_run(self):
        snapshot,ids,manifest=self.samples();original=executor.read_json(manifest)
        import json
        for bad in (ids[:23],ids[:23]+ids[:1],ids[:23]+['unknown']):
            changed=deepcopy(original);changed['development']['source_ids']=bad;manifest.write_text(json.dumps(changed))
            with patch.object(executor,'check_admission'),self.assertRaises(ValueError):self.prepare_gate('G2',manifest)
        self.time_budget.call.assert_not_called()

    def test_frozen_sample_manifest_and_admission_cannot_change_on_resume(self):
        snapshot,ids,manifest=self.samples()
        admission=self.root/'admission.json';write(admission,{'gates':{}})
        with patch.object(executor,'check_admission'):
            plan=self.prepare_gate('G2',admission)
            original=manifest.read_text()
            manifest.write_text('{}')
            with self.assertRaises(ValueError):executor.validate(self.run_dir,plan)
            manifest.write_text(original)
            admission.write_text('{"gates":{"changed":true}}')
            with self.assertRaises(ValueError):executor.validate(self.run_dir,plan)
        self.time_budget.call.assert_not_called()

    def qualification(self):
        plan=executor.prepare(self.run_dir,self.deployment,self.materials,self.policy,0.25)
        write(self.run_dir/'artifacts/output.json',{'authored':'output'})
        write(self.run_dir/'artifacts/runtime.json',{'authored':'runtime'})
        completed={'execution_complete':True,'plan_sha256':sha(self.run_dir/'plan.json'),
                   'output_sha256':sha(self.run_dir/'artifacts/output.json'),
                   'runtime_sha256':sha(self.run_dir/'artifacts/runtime.json')}
        write(self.run_dir/'completed.json',completed)
        folder=self.root/'review';packet={**completed,'run':str(self.run_dir)}
        write(folder/'packet.json',packet)
        write(folder/'review.json',{'packet_sha256':digest(packet)})
        result={'gate':'G1','gate_passed':True,'requirements':{'authored':True},
                'review_sha256':sha(folder/'review.json'),'packet_sha256':digest(packet)}
        write(folder/'result.json',result)
        admission=self.root/'admission.json'
        row={'run':str(self.run_dir),
             **{k:str(folder/(k+'.json')) for k in ('packet','review','result')}}
        write(admission,{'gates':{'G1':row}})
        return plan,admission,result

    def test_admission_replays_review_and_binds_auxiliary_evidence_and_shared_budget(self):
        plan,admission,result=self.qualification();materials=executor.read_json(self.materials)
        with patch.object(prior,'code_hashes',return_value=plan['code_sha256']), \
             patch.object(review,'evaluate',return_value=result) as replay:
            executor.check_admission('G2',self.deployment,admission,materials,self.policy)
            replay.assert_called_once()
            changed=deepcopy(materials);changed['documents']=[{'authored':'different evidence'}]
            with self.assertRaises(ValueError):executor.check_admission('G2',self.deployment,admission,changed,self.policy)
            changed_policy={**self.policy,'account_id':'another-account'}
            with self.assertRaises(ValueError):executor.check_admission('G2',self.deployment,admission,materials,changed_policy)
        self.time_budget.call.assert_not_called()

    def test_forged_pass_changed_model_and_changed_code_cannot_authorize_larger_run(self):
        plan,admission,result=self.qualification();materials=executor.read_json(self.materials)
        with patch.object(prior,'code_hashes',return_value=plan['code_sha256']), \
             patch.object(review,'evaluate',return_value={**result,'gate_passed':False}):
            with self.assertRaises(ValueError):executor.check_admission('G2',self.deployment,admission,materials,self.policy)
        changed=deepcopy(self.deployment);changed['model']='different/model'
        with patch.object(prior,'code_hashes',return_value=plan['code_sha256']):
            with self.assertRaises(ValueError):executor.check_admission('G2',changed,admission,materials,self.policy)
            with self.assertRaises(ValueError):
                executor.check_admission('G2',self.deployment,admission,materials,self.policy,discovery_mode='free')
        with patch.object(prior,'code_hashes',return_value={'changed':'code'}):
            with self.assertRaises(ValueError):executor.check_admission('G2',self.deployment,admission,materials,self.policy)
        self.time_budget.call.assert_not_called()

    def test_plan_cannot_extend_original_snapshot_expiry(self):
        import json
        plan=executor.prepare(self.run_dir,self.deployment,self.materials,self.policy,0.25)
        plan['expires_at']='2099-12-31T00:00:00Z'
        path=self.run_dir/'plan.json';path.write_text(json.dumps(plan))
        (self.run_dir/'frozen.json').write_text(json.dumps({'plan_sha256':sha(path)}))
        with self.assertRaisesRegex(ValueError,'scope changed'):executor.validate(self.run_dir,plan)
        self.time_budget.call.assert_not_called()

if __name__=='__main__':unittest.main()
