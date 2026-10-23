from contextlib import contextmanager, ExitStack
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.checkpoint_calls import PendingCallError
from commentscope.storage import write_json_exclusive as write
from experiments import sequential_corpus_pipeline as p
from tests import test_framed_corpus_pipeline as fixture
from tests.test_framed_corpus import PipelineRunner
from tests import test_resumable_source_comparison as cpu_fixture


class SequentialCorpusTests(unittest.TestCase):
    def setUp(self):
        old = fixture.FramedCorpusPipelineTests(); old.setUp(); self.addCleanup(old.doCleanups)
        self.root, self.runs, self.directory = old.root, old.runs, old.directory
        self.snapshot, self.reference, self.cycle = old.snapshot_path, old.reference_path, old.cycle
        self.auxiliary = old.source
        self.source = self.root/'cpu/plan.json'
        self.deployment = cpu_fixture.CpuComparisonAdmissionTests().deployment()
        self.deployment['runtime'].update(max_seconds_per_model=None, reasoning='on', reasoning_budget=1024)
        for info in (self.deployment['server'], self.deployment['models']['baseline']): info['sha256'] = '0'*64
        write(self.source, {'artifact_kind': 'local-resource-profile-probe-0.1', 'deployment': self.deployment})
        write(self.source.parent/'completed.json', {'plan_sha256': sha(self.source), 'completed_calls': 6,
            'call_errors': 0, 'frame_binding_errors': [], 'resource_stop': False, 'observation_errors': 0,
            'eligible_for_whole_corpus_trial': True, 'minimum_available_mb': 8000,
            'minimum_commit_headroom_bytes': 2*1024**3, 'minimum_disk_free_bytes': 18*1024**3})
        write(self.source.parent/'server/stopped.json', {'returncode': 0})
        write(self.source.parent/'server/runtime.json', {'command': p.command(self.deployment, 'baseline')})
        self.active = None; self.events = []; self.requests = []; self.interrupt_stage = None
        self.fact_mode = False; self.bad_server_cleanup = False; self.bad_observer_cleanup = False
        self.budget = Mock(); self.budget.summary.return_value = {'synthetic': True, 'calls': []}
        owner = self

        class Base(fixture.FakeBase):
            def __init__(self, directory, plan, budget):
                owner.assertIs(budget, owner.budget)
                super().__init__(directory, plan, budget)
                if owner.fact_mode: self.pipeline = PipelineRunner(None, ground_kind='fact', essential=True)

            def call(self, stage, req, *, provider=None, maximum=None):
                expected = 'llm' if provider is None else 'auxiliary'
                owner.assertEqual(owner.active, expected)
                owner.requests.append((stage, deepcopy(req), provider, maximum))
                if stage.startswith(owner.interrupt_stage or 'never-interrupt-'): raise KeyboardInterrupt()
                if provider is p.evidence_nli.generate:
                    # Malformed evidence stays unconfirmed; do not rescue by deleting essential facts.
                    self.seq += 1
                    return {'synthetic_unconfirmed': True}
                return super().call(stage, req, provider=provider, maximum=maximum)

        @contextmanager
        def server(deployment, name, directory):
            self.assertEqual(deployment, self.deployment); self.assertEqual(name, 'baseline')
            self.assertIsNone(self.active); self.active = 'llm'; self.events.append('llm-open')
            try: yield
            finally:
                self.events.append('llm-close'); self.active = None
                write(directory/'stopped.json', {'returncode': 1 if self.bad_server_cleanup else 0})
                write(directory/'resources/finished.json', {'observer_stopped': True})

        @contextmanager
        def auxiliary(directory, policy, observe):
            self.assertEqual(policy, p.host_resources.POLICY)
            self.assertIsNone(self.active); self.active = 'auxiliary'; self.events.append('aux-open')
            try: yield
            finally:
                self.events.append('aux-close'); self.active = None
                write(directory/'finished.json', {'observer_stopped': not self.bad_observer_cleanup})

        stack = ExitStack(); self.addCleanup(stack.close)
        for item in (patch.object(p, 'PRIVATE_ROOT', self.runs), patch.object(p, 'file_hash', return_value='0'*64),
                     patch.object(p, 'code_hashes', return_value={}), patch.object(p, 'Runner', Base),
                     patch.object(p, 'InferenceBudget', return_value=self.budget),
                     patch.object(p, 'owned_server', side_effect=server),
                     patch.object(p.host_resources, 'watch', side_effect=auxiliary)):
            stack.enter_context(item)
        self.admission = stack.enter_context(patch.object(p, 'preflight', return_value={'admitted': True}))

    def prepare(self):
        return p.prepare(self.directory, self.snapshot, self.reference, self.source, self.auxiliary, self.cycle)

    def test_full_semantic_path_runtime_and_exclusive_resource_ownership(self):
        plan = self.prepare(); report = p.run(self.directory)
        self.assertEqual(report['canonical_population'], 5)
        self.assertEqual(report['compiled_profiles'], 1); self.assertEqual(report['runtime_turns'], 3)
        self.assertEqual(report['membership_judgments'], 5)
        self.assertTrue(report['execution_complete']); self.assertFalse(report['quality_gate_passed'])
        self.assertIsNone(report['correct_comment_utilization']); self.assertIsNone(self.active)
        self.assertEqual(report['model_lifetime'], {'server_starts': 3, 'server_stops': 3, 'auxiliary_calls': 3})
        self.assertEqual(self.admission.call_count, 3)
        self.assertEqual(self.events, ['llm-open', 'llm-close', 'aux-open', 'aux-close',
            'llm-open', 'llm-close', 'aux-open', 'aux-close', 'aux-open', 'aux-close', 'llm-open', 'llm-close'])
        self.assertEqual(plan['limits'], p.LIMITS)
        self.assertEqual(len(list((self.directory/'transitions/0001').glob('*.finished.json'))), len(self.requests))
        for stage, req, provider, maximum in self.requests:
            self.assertNotIn('eligibility', str(req)); self.assertNotIn('expected', str(req))
            self.assertNotIn('runtime_input', str(req))
            if provider is p.framed_embedding.generate: self.assertEqual(maximum, 900)
        before = len(self.requests); p.run(self.directory)
        self.assertEqual(len(self.requests), before); self.assertEqual(self.admission.call_count, 3)

    def test_same_plan_resume_cache_hits_do_not_load_models(self):
        self.prepare()
        with patch.object(p, 'runtime_probe', side_effect=RuntimeError('after analysis before runtime')):
            with self.assertRaisesRegex(RuntimeError, 'after analysis'): p.run(self.directory)
        self.requests.clear(); self.events.clear(); self.admission.reset_mock()
        report = p.run(self.directory)
        self.assertEqual([r[0] for r in self.requests], ['runtime'] * 3)
        self.assertEqual(self.events, ['llm-open', 'llm-close']); self.assertEqual(self.admission.call_count, 1)
        self.assertGreater(report['same_plan_reused_calls_this_attempt'], 0)
        self.assertEqual(report['model_lifetime']['auxiliary_calls'], 0)

    def test_interruption_does_not_retry_pending_or_leave_owned_server(self):
        self.prepare(); self.interrupt_stage = 'frame-'
        with self.assertRaises(KeyboardInterrupt): p.run(self.directory)
        self.assertIsNone(self.active); self.assertEqual(self.events, ['llm-open', 'llm-close'])
        before = len(self.requests); self.interrupt_stage = None
        with self.assertRaises(PendingCallError): p.run(self.directory)
        self.assertEqual(len(self.requests), before); self.assertEqual(self.admission.call_count, 1)
        self.assertFalse((self.directory/'completed.json').exists())

    def test_uncertain_shutdown_prevents_auxiliary_start(self):
        self.prepare(); self.bad_server_cleanup = True
        with self.assertRaises(RuntimeError): p.run(self.directory)
        self.assertNotIn('aux-open', self.events)
        self.assertFalse((self.directory/'completed.json').exists())

    def test_auxiliary_observer_cleanup_failure_stops_before_next_llm(self):
        self.prepare(); self.bad_observer_cleanup = True
        with self.assertRaisesRegex(RuntimeError, 'observer cleanup'): p.run(self.directory)
        self.assertEqual(self.admission.call_count, 1)
        self.assertEqual(self.events, ['llm-open', 'llm-close', 'aux-open', 'aux-close'])

    def test_failed_llm_admission_makes_no_model_call(self):
        self.prepare(); self.admission.side_effect = RuntimeError('resource admission')
        with self.assertRaisesRegex(RuntimeError, 'resource admission'): p.run(self.directory)
        self.assertEqual(self.requests, []); self.assertEqual(self.events, [])

    def test_fact_provider_runs_exclusively_and_unverified_essentials_defer(self):
        self.fact_mode = True; self.prepare(); report = p.run(self.directory)
        facts = [r for r in self.requests if r[2] is p.evidence_nli.generate]
        self.assertEqual(len(facts), 1); self.assertEqual(facts[0][3], 600)
        self.assertEqual(report['compiled_profiles'], 0); self.assertEqual(report['runtime_turns'], 0)
        self.assertFalse(report['quality_gate_passed']); self.assertEqual(report['model_lifetime']['auxiliary_calls'], 4)
        out = read_json(self.directory/'artifacts/output.json')
        core = next(c for c in out['agent_inputs']['bundle']['claims'] if c['id'].endswith(':C'))
        self.assertEqual(len(core['requires']), 3)

    def test_frozen_contract_rejects_timeout_policy_reference_and_cycle_drift(self):
        plan = self.prepare()
        changes = [('limits', {**plan['limits'], 'call_seconds': 180}), ('runtime_reference_labels', True),
                   ('model_lifetime', {}), ('quality_gate_passed', True), ('budget', {'cycle_id': 'other'}),
                   ('reference', {**plan['reference'], 'runtime_input': True}),
                   ('documents', [{'expires_at': '2099-01-01T00:00:00Z'}])]
        for key, value in changes:
            changed = deepcopy(plan); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): p.validate(changed)
        self.assertEqual(self.requests, [])

    def test_unknown_provider_does_not_own_a_model(self):
        self.prepare(); plan = read_json(self.directory/'plan.json')
        base = Mock(directory=self.directory, plan_sha=sha(self.directory/'plan.json'), seq=0)
        with p.lifetimes(self.directory, plan, 1) as models:
            wrapped = p.SequentialRunner(base, models, self.directory/'transitions/0001')
            with self.assertRaisesRegex(ValueError, 'provider'):
                wrapped.call('unknown', {}, provider=lambda: None)
        self.assertEqual(self.events, []); base.call.assert_not_called()

    def test_completed_runtime_tampering_is_not_accepted(self):
        self.prepare(); p.run(self.directory)
        before = len(self.requests)
        (self.directory/'artifacts/runtime.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'runtime changed'): p.run(self.directory)
        self.assertEqual(len(self.requests), before)

    def test_failed_qualification_is_not_replaced_by_unit_test_success(self):
        path = self.source.parent/'completed.json'
        done = read_json(path); done['completed_calls'] = 5
        import json
        path.write_text(json.dumps(done))
        with self.assertRaisesRegex(ValueError, 'deployment trial'): self.prepare()
        self.assertFalse(self.directory.exists()); self.assertEqual(self.requests, [])

    def test_private_destination_and_new_plan_required(self):
        with self.assertRaisesRegex(ValueError, 'private'):
            p.prepare(self.root/'outside', self.snapshot, self.reference, self.source, self.auxiliary, self.cycle)
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'overwrite'): self.prepare()


if __name__ == '__main__': unittest.main()
