"""Executor boundaries use authored artifacts; no network or model inference."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import minimal_factory_review as review
from experiments import openrouter_factory_pipeline as executor
import test_minimal_pipeline as fixture
from test_openrouter import deployment


class OpenRouterExecutorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='runs', prefix='test-api-factory-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name); self.run_dir = self.root/'run'
        factory = fixture.MinimalPipelineTests(); factory.setUp()
        texts = {sid: (f'Adopt P because Reason {sid} matters.' if sid in 'ABCIJ' else
                       f'Reject P because Other reason {sid} matters.' if sid in 'EGL' else
                       f'Consider separate proposal {sid}.') for sid in 'ABCDEFGHIJKL'}
        factory.snapshot = replace(factory.snapshot, comments=tuple(
            replace(factory.snapshot.comments[0], comment_id=sid, text_original=text)
            for sid, text in texts.items()))
        self.snapshot = factory.snapshot
        # Focus this suite on execution/binding; raw semantic components have separate tests.
        self.output = factory.process(fixture.ScriptedRunner(), discovery_mode='literal')
        self.artifacts = factory.saved
        self.assertEqual(len(self.output['agent_inputs']['compiled']['profiles']), 2)
        model = self.root/'authored-model'; model.write_bytes(b'authored classifier identity')
        self.materials = self.root/'materials.json'
        write(self.materials, {'classifier': fixture.MODEL, 'model_files': {str(model): sha(model)},
                               'documents': [], 'selections': []})
        self.deployment = deployment(); self.deployment['context'] = 65536
        self.policy = {'account_id': 'test', 'ledger': str(self.root/'spend.sqlite'),
                       'maximum_usd': '1', 'opening_charge_usd': '0'}
        self.addCleanup(patch.stopall)
        patch.object(executor, 'synthetic12', return_value=self.snapshot).start()
        paths = ['src/commentscope/providers/openrouter.py', 'src/commentscope/providers/openrouter_budget.py']
        patch.object(executor, 'code_hashes', side_effect=lambda: {p: sha(p) for p in paths}).start()
        self.preflight = patch.object(executor, 'provider_preflight', return_value={'tag': 'test-provider'}).start()
        patch.object(executor, 'check_quota').start()
        patch('commentscope.providers.llama_runtime.owned_server', side_effect=AssertionError('No local LLM')).start()
        patch.object(executor, 'quota_watch', return_value=nullcontext()).start()
        patch.object(executor.host_resources, 'watch', side_effect=lambda *args, **kwargs: nullcontext()).start()
        self.metadata = patch.object(executor, 'key_metadata', return_value={'limit_remaining': 1}).start()
        self.time_budget = Mock(); self.time_budget.summary.return_value = {'synthetic': True}
        self.scripted = fixture.ScriptedRunner()
        def respond(request, plan, **kwargs):
            output = self.scripted.call('authored-http', request)['output']
            return {'choices': [{'message': {'content': json.dumps(output)}, 'finish_reason': 'stop'}],
                    'usage': {'cost': 0.00001, 'prompt_tokens': 12, 'completion_tokens': 5}}
        self.time_budget.call.side_effect = respond
        patch.object(executor, 'InferenceBudget', return_value=self.time_budget).start()
        def process(snapshot, runner, embed, inspect, facts, **kwargs):
            self.assertEqual(kwargs['discovery_mode'], 'literal')
            self.assertEqual(kwargs['membership_mode'], 'raw')
            self.assertEqual(kwargs['verification_contract'], executor.raw_membership_verification.FULL_SCOPE)
            for name, value in self.artifacts.items(): kwargs['save'](name, value)
            return deepcopy(self.output)
        self.process = patch.object(executor.minimal_pipeline, 'process', side_effect=process).start()

    def prepare(self):
        return executor.prepare(self.run_dir, self.deployment, self.materials, self.policy, 0.25)

    def test_prepare_freezes_input_and_budget_without_dispatch(self):
        plan = self.prepare()
        self.assertEqual(plan['gate'], 'G1'); self.assertEqual(len(plan['scope_ids']), 12)
        self.assertEqual(plan['maximum_cost_usd'], 0.25)
        self.assertFalse(plan['reference_runtime_input'])
        self.assertTrue((self.run_dir/'frozen-code/src/commentscope/providers/openrouter.py').exists())
        self.time_budget.call.assert_not_called()

    def test_missing_response_persists_diagnostic_without_publishing_completion(self):
        self.prepare()
        failure = executor.ModelResponseUnavailable('extract', 'a'*64, 'b'*64)
        self.process.side_effect = failure
        with self.assertRaises(executor.ModelResponseUnavailable): executor.run(self.run_dir)
        report = json.loads((self.run_dir/'attempts/0001.failed.json').read_text(encoding='utf-8'))
        self.assertEqual(report['diagnostic'], failure.diagnostic)
        self.assertFalse((self.run_dir/'completed.json').exists())
        self.time_budget.call.assert_not_called()

    def test_explicit_free_mode_pins_compact_extraction_without_dispatch(self):
        plan = executor.prepare(self.run_dir, self.deployment, self.materials, self.policy, 0.25,
                                discovery_mode='free')
        self.assertEqual(plan['discovery_mode'], 'free')
        self.assertEqual(plan['extraction_protocol'], executor.compact_claims.PROPOSALS)
        self.assertEqual(plan['assertion_equivalence_protocol'], executor.candidate_consolidation.BILATERAL)
        self.assertEqual(plan['membership_observation_protocol'], executor.raw_membership.WORLD_CONTEXT)
        self.assertEqual(plan['source_context_protocol'], executor.source_context_observations.VERSION)
        self.assertEqual(plan['world_observation_protocol'], executor.statement_worlds.VERSION)
        self.assertEqual(plan['evidence_observation_protocol'], executor.raw_membership_verification.QUALIFIED)
        self.assertEqual(executor.validate(self.run_dir, plan).to_dict(), self.snapshot.to_dict())
        self.time_budget.call.assert_not_called()

    def test_rewritten_membership_protocol_is_rejected_even_with_rehashed_plan(self):
        plan = executor.prepare(self.run_dir, self.deployment, self.materials, self.policy, 0.25,
                                discovery_mode='free')
        plan['membership_observation_protocol'] = executor.raw_membership.VERSION
        path = self.run_dir/'plan.json'; path.write_text(json.dumps(plan))
        (self.run_dir/'frozen.json').write_text(json.dumps({'plan_sha256': sha(path)}))
        with self.assertRaisesRegex(ValueError, 'contract changed'): executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()

    def test_rewritten_evidence_protocol_is_rejected_before_paid_dispatch(self):
        plan = executor.prepare(self.run_dir, self.deployment, self.materials, self.policy, 0.25,
                                discovery_mode='free')
        plan['evidence_observation_protocol'] = executor.raw_membership_verification.BRIEF
        path = self.run_dir/'plan.json'; path.write_text(json.dumps(plan))
        (self.run_dir/'frozen.json').write_text(json.dumps({'plan_sha256': sha(path)}))
        with self.assertRaisesRegex(ValueError, 'contract changed'): executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()

    def test_complete_agent_execution_is_not_a_quality_pass_and_reuses_completed_run(self):
        self.prepare(); result = executor.run(self.run_dir)
        self.assertEqual(result['compiled_agents'], 2); self.assertEqual(result['runtime_turns'], 6)
        self.assertTrue(result['execution_complete']); self.assertFalse(result['quality_gate_passed'])
        self.assertFalse(result['local_llm_started'])
        self.assertEqual(result['run_spending']['charged_usd'], '0.00006')
        self.assertEqual(executor.run(self.run_dir), result)
        self.assertEqual(self.time_budget.call.call_count, 6)
        self.assertEqual(review.load_run(self.run_dir)[0]['artifact_kind'], executor.VERSION)

    def test_copied_run_is_rejected_before_preflight_or_dispatch(self):
        self.prepare(); copy = self.root/'copy'
        executor.shutil.copytree(self.run_dir, copy)
        self.preflight.reset_mock()
        with self.assertRaisesRegex(ValueError, 'original plan directory'): executor.run(copy)
        self.preflight.assert_not_called(); self.time_budget.call.assert_not_called()

    def test_unknown_checkpoint_prevents_any_dispatch(self):
        self.prepare(); write(self.run_dir/'checkpoints/unknown.intent.json', {'authored': 'pending'})
        self.preflight.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'Pending'): executor.run(self.run_dir)
        self.preflight.assert_not_called(); self.metadata.assert_not_called()
        self.time_budget.call.assert_not_called()

    def test_rewriting_a_plan_cannot_raise_its_budget(self):
        self.prepare(); path = self.run_dir/'plan.json'; plan = read_json(path)
        plan['maximum_cost_usd'] = 0.5; path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, 'Frozen remote plan changed'): executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()

    def test_copied_execution_cannot_be_approved_by_review(self):
        self.prepare(); copy = self.root/'review-copy'; executor.shutil.copytree(self.run_dir, copy)
        write(copy/'completed.json', {})
        with self.assertRaisesRegex(ValueError, 'original plan directory'): review.load_run(copy)

    def test_provider_usage_outside_the_bound_keeps_first_response_and_stops(self):
        self.prepare(); original = self.time_budget.call.side_effect
        def oversized(*args, **kwargs):
            result = original(*args, **kwargs); result['usage']['prompt_tokens'] = 10**9
            return result
        self.time_budget.call.side_effect = oversized
        with self.assertRaises(ValueError): executor.run(self.run_dir)
        self.assertEqual(self.time_budget.call.call_count, 1)
        self.assertTrue(list((self.run_dir/'calls').glob('*.result.json')))
        self.assertFalse((self.run_dir/'completed.json').exists())

    def test_changed_materials_are_rejected_before_dispatch(self):
        self.prepare(); self.materials.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'changed'): executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()

    def test_failed_runtime_artifact_is_kept_without_completion(self):
        self.prepare(); original = executor.runtime_probe
        def corrupt(*args, **kwargs):
            runtime = original(*args, **kwargs)
            runtime['turns'][0]['other_histories_unchanged'] = False
            return runtime
        with patch.object(executor, 'runtime_probe', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'history'): executor.run(self.run_dir)
        saved = read_json(self.run_dir/'artifacts/runtime.json')
        self.assertIs(saved['turns'][0]['other_histories_unchanged'], False)
        self.assertFalse((self.run_dir/'completed.json').exists())
        self.assertTrue(list((self.run_dir/'attempts').glob('*.failed.json')))

    def test_larger_gate_cannot_be_requested_without_new_qualification(self):
        self.prepare(); path = self.run_dir/'plan.json'; plan = read_json(path); plan['gate'] = 'G2'
        path.write_text(json.dumps(plan))
        (self.run_dir/'frozen.json').write_text(json.dumps({'plan_sha256': sha(path)}))
        with self.assertRaises(ValueError): executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()


if __name__ == '__main__': unittest.main()
