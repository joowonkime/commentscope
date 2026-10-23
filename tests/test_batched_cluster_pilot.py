from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.exclusive_models import ExclusiveModels
from commentscope.providers.checkpoint_calls import PendingCallError
from commentscope.storage import write_json_exclusive as write
from experiments import batched_cluster_pilot as p
from tests.test_batch_stances import FakeRunner


class BatchedPilotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.runs = self.root/'runs'; self.runs.mkdir()
        self.directory = self.runs/'pilot'
        self.base = self.root/'base.json'; self.cycle = self.root/'cycle.json'; self.deployment_source = self.root/'deployment.json'
        self.snapshot = p.synthetic_snapshot()
        real = replace(self.snapshot, comments=tuple(replace(self.snapshot.comments[0], comment_id=f's{i:02}',
                         text_original=f'Opinion number {i}.') for i in range(30)))
        self.real_path = self.root/'real.json'; write(self.real_path, real.to_dict())
        self.deployment = {'runtime': {'context': 8192, 'reasoning': 'on', 'reasoning_budget': 1024},
                           'server': {'path': '/synthetic/server', 'sha256': '0'*64},
                           'models': {'baseline': {'path': '/synthetic/weights', 'sha256': '0'*64}}}
        self.model_path = '/synthetic/models--' + p.framed_embedding.MODEL.replace('/', '--') + '/snapshots/' + p.framed_embedding.REVISION + '/model.safetensors'
        write(self.deployment_source, {'deployment': self.deployment})
        write(self.cycle, {'goal_revision': 'factory-goal-20261014-r4', 'cycle_id': 'mvp-factory-20261014',
                          'ledger': str(self.root/'unused.sqlite'), 'limit_seconds': None, 'analysis_seconds': None})
        write(self.base, {'deployment': self.deployment, 'cycle': str(self.cycle), 'snapshot': str(self.real_path),
                         'deployment_source': str(self.deployment_source), 'model_files': {self.model_path: '0'*64}})
        self.budget = Mock(); self.budget.summary.return_value = {'synthetic': True}
        self.calls = []; self.active = None; self.events = []; self.interrupt = None
        owner = self

        @contextmanager
        def server(sequence):
            owner.assertIsNone(owner.active); owner.active = 'llm'; owner.events.append('llm-open')
            try: yield
            finally: owner.active = None; owner.events.append('llm-close')

        @contextmanager
        def auxiliary(sequence):
            owner.assertIsNone(owner.active); owner.active = 'auxiliary'; owner.events.append('aux-open')
            try: yield
            finally: owner.active = None; owner.events.append('aux-close')

        class Base:
            def __init__(self, directory, plan, budget):
                owner.assertIs(budget, owner.budget)
                self.directory = directory; self.plan_sha = sha(directory/'plan.json'); self.seq = 0
                self.fake = FakeRunner()

            def call(self, stage, req, *, provider=None, maximum=None):
                owner.assertEqual(owner.active, 'auxiliary' if provider else 'llm')
                owner.calls.append((stage, deepcopy(req))); self.seq += 1
                write(self.directory/'calls'/f'{self.seq:04}-{stage}.request.json', {'request': req})
                if stage == owner.interrupt: raise KeyboardInterrupt()
                if provider:
                    owner.assertIs(provider, p.framed_embedding.generate)
                    owner.assertEqual(maximum, p.sequential.LIMITS['embedding_seconds'])
                    texts = req['data']['texts']; target = Path(req['data']['output'])
                    artifact = {'texts_sha256': digest(texts), 'vectors': {sid: [1., 0.] for sid in texts},
                                'model': p.framed_embedding.MODEL, 'revision': p.framed_embedding.REVISION, 'local_files_only': True}
                    write(target, artifact)
                    return {'output': str(target), 'sha256': sha(target), **{k: artifact[k] for k in ('texts_sha256', 'model', 'revision')}}
                return self.fake.call(stage, req)

        patches = [patch.object(p.sequential, 'PRIVATE_ROOT', self.runs),
                   patch.object(p.sequential, 'deployment_check'), patch.object(p.sequential, 'qualification', return_value=[]),
                   patch.object(p, 'code_hashes', return_value={}), patch.object(p, 'file_sha256', return_value='0'*64),
                   patch.object(p.sequential, 'preflight'), patch.object(p, 'InferenceBudget', return_value=self.budget),
                   patch.object(p, 'Runner', Base),
                   patch.object(p.sequential, 'lifetimes', side_effect=lambda *a: ExclusiveModels(server, auxiliary))]
        self.mocks = [item.start() for item in patches]
        for item in patches: self.addCleanup(item.stop)

    def prepare(self, arm='controls'):
        return p.prepare(self.directory, arm, self.base)

    def test_prepare_freezes_sample_and_separates_evaluation_from_runtime(self):
        plan = self.prepare('real'); snapshot = p.validate(plan)
        self.assertEqual(len(plan['sample']['source_ids']), 24)
        self.assertEqual(plan['sample']['source_ids'], p.select_ids(snapshot, 'real'))
        self.assertEqual(plan['sample']['canonical_population'], 30)
        self.assertFalse(plan['runtime_reference_labels']); self.assertIsNone(plan['limits']['analysis_seconds'])
        self.assertEqual(self.calls, [])
        self.assertEqual(plan['model_files'], {self.model_path: '0'*64})

    def test_controls_roundtrip_and_exclusive_lifetimes(self):
        self.prepare(); result = p.run(self.directory)
        self.assertEqual(result['scheduled_originals'], 6)
        self.assertEqual(result['membership_judgments'], 6)
        self.assertEqual([s for s, _ in self.calls], ['embed-sources', 'discovery-0000', 'embed-candidates', 'initial-0000'])
        self.assertEqual(result['model_lifetime'], {'server_starts': 2, 'server_stops': 2, 'auxiliary_calls': 2})
        self.assertFalse(result['quality_gate_passed']); self.assertTrue(result['semantic_review_required'])
        self.assertIsNone(self.active)
        for _, req in self.calls:
            self.assertNotIn('review_criteria', req['data']); self.assertNotIn('expected', req['data'])
        self.assertEqual(self.calls[1][1]['max_tokens'], 3072+1024)
        self.assertEqual(self.calls[3][1]['max_tokens'], 128+128*6+1024)

    def test_completed_read_does_not_start_models_or_charge_again(self):
        self.prepare(); result = p.run(self.directory); calls = len(self.calls)
        self.assertEqual(p.run(self.directory), result)
        self.assertEqual(len(self.calls), calls)

    def test_low_resources_decline_before_weights_ledger_and_attempt(self):
        self.prepare()
        with patch.object(p.sequential, 'preflight', side_effect=RuntimeError('Model not started')), \
                patch.object(p, 'file_sha256') as hash_file, patch.object(p, 'InferenceBudget') as budget:
            with self.assertRaisesRegex(RuntimeError, 'Model not started'): p.run(self.directory)
            hash_file.assert_not_called(); budget.assert_not_called()
        self.assertFalse((self.directory/'started.json').exists()); self.assertEqual(self.calls, [])

    def test_interruption_is_retained_and_resume_does_not_silently_retry(self):
        self.prepare(); self.interrupt = 'discovery-0000'
        with self.assertRaises(KeyboardInterrupt): p.run(self.directory)
        self.assertIsNone(self.active)
        self.assertTrue((self.directory/'attempts/0001.failed.json').exists())
        original_calls = len(self.calls); self.interrupt = None
        with self.assertRaises(PendingCallError): p.run(self.directory)
        self.assertEqual(len(self.calls), original_calls)
        self.assertFalse((self.directory/'completed.json').exists())

    def test_changed_snapshot_contract_and_plan_are_rejected(self):
        plan = self.prepare()
        for key in ('sample', 'limits', 'review_criteria', 'deployment'):
            with self.subTest(key=key):
                modified = deepcopy(plan); modified[key] = {}
                with self.assertRaises((ValueError, KeyError)): p.validate(modified)
        with self.assertRaises(ValueError): self.prepare()
        with self.assertRaises(ValueError): p.prepare(self.root/'public', 'real', self.base)

    def test_completed_output_tampering_is_not_accepted(self):
        self.prepare(); p.run(self.directory)
        original_read = p.read_json
        def changed(path):
            value = original_read(path)
            if Path(path).name == 'output.json': value['candidates'] = []
            return value
        with patch.object(p, 'read_json', side_effect=changed):
            with self.assertRaises(ValueError): p.run(self.directory)


if __name__ == '__main__': unittest.main()
