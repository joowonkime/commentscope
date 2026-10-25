from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.providers import llama_runtime
from commentscope.storage import write_json_exclusive as write
from experiments import minimal_factory_pipeline as executor
from experiments import minimal_factory_review as review
from test_portable_runtime import deployment


class PortableExecutorTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='runs', prefix='test-portable-executor-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.d = deployment(self.root.resolve())

    def test_new_deployment_does_not_read_legacy_8b_plan(self):
        with patch.object(executor, 'read_json', side_effect=AssertionError('Must not load legacy deployment')):
            executor.deployment_check(self.d)
        self.assertIn(executor.VERSION, review.EXECUTORS)

    def test_unqualified_cannot_jump_to_larger_gates(self):
        executor.check_admission('G1', self.d, None)
        for gate in ('G2', 'G3', 'G4'):
            with self.subTest(gate=gate), self.assertRaises(ValueError):
                executor.check_admission(gate, self.d, None)

    def qualification(self):
        run = self.root/'g1'; packet_dir = self.root/'review'
        prior = {'gate': 'G1', 'deployment': deepcopy(self.d), 'code_sha256': {'code': 'fixed'},
                 'verification_contract': executor.raw_membership_verification.ALIGNED,
                 'discovery_mode': 'free', 'membership_mode': 'raw'}
        write(run/'plan.json', prior)
        write(run/'artifacts/output.json', {'synthetic': 'output'})
        write(run/'artifacts/runtime.json', {'synthetic': 'runtime'})
        completed = {'execution_complete': True, 'plan_sha256': executor.sha(run/'plan.json'),
                     'output_sha256': executor.sha(run/'artifacts/output.json'),
                     'runtime_sha256': executor.sha(run/'artifacts/runtime.json')}
        write(run/'completed.json', completed)
        packet = {**completed, 'run': str(run)}
        write(packet_dir/'packet.json', packet)
        write(packet_dir/'review.json', {'packet_sha256': digest(packet)})
        result = {'gate': 'G1', 'gate_passed': True, 'requirements': {'all': True},
                  'review_sha256': executor.sha(packet_dir/'review.json'), 'packet_sha256': digest(packet)}
        write(packet_dir/'result.json', result)
        row = {'run': str(run), **{k: str(packet_dir/(k+'.json')) for k in ('packet', 'review', 'result')}}
        manifest = self.root/'admission.json'
        write(manifest, {'gates': {'G1': row}})
        return manifest, result

    def test_admission_replays_bound_offline_review(self):
        manifest, result = self.qualification()
        with patch.object(executor, 'code_hashes', return_value={'code': 'fixed'}), \
             patch.object(executor.acceptance, 'from_plan', return_value={'r5': True}), \
             patch.object(review, 'evaluate', return_value=result) as replay:
            executor.check_admission('G2', self.d, manifest)
        replay.assert_called_once()

    def test_changed_model_or_algorithm_requires_requalification(self):
        manifest, result = self.qualification()
        other = deepcopy(self.d); other['model']['sha256'] = 'f'*64
        with patch.object(executor, 'code_hashes', return_value={'code': 'fixed'}):
            with self.assertRaises(ValueError):
                executor.check_admission('G2', other, manifest)
            with self.assertRaises(ValueError):
                executor.check_admission('G2', self.d, manifest, 'contextual', 'raw')

    def test_written_pass_flag_cannot_override_offline_evaluator(self):
        manifest, result = self.qualification()
        failed = {**result, 'gate_passed': False}
        with patch.object(executor, 'code_hashes', return_value={'code': 'fixed'}), \
             patch.object(executor.acceptance, 'from_plan', return_value={'r5': True}), \
             patch.object(review, 'evaluate', return_value=failed):
            with self.assertRaises(ValueError):
                executor.check_admission('G2', self.d, manifest)

    def test_factory_model_lifetime_uses_portable_server(self):
        events = []
        @contextmanager
        def server(d, directory, observe, quota):
            events.append('start')
            try:
                yield llama_runtime.Client(d)
            finally:
                events.append('stop')
                write(directory/'resources/finished.json', {'observer_stopped': True})
        with patch.object(llama_runtime, 'owned_server', side_effect=server):
            with executor.lifetimes(self.root, {'deployment': self.d}, 1) as models:
                self.assertEqual(models.invoke('llm', lambda: 'operation'), 'operation')
                self.assertEqual(models.invoke('llm', lambda: 'next'), 'next')
        self.assertEqual(events, ['start', 'stop'])
