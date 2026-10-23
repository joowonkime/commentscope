from contextlib import nullcontext, ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory import comment_utilization as utilization
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import framed_corpus_pipeline as p
from experiments.grounding_contract_demo import MODEL
from tests import test_stance_agents as fixture
from tests.test_framed_corpus import PipelineRunner


class FakeBase:
    executed = []

    def __init__(self, directory, plan, budget):
        self.directory = directory; self.plan_sha = sha(directory/'plan.json'); self.seq = 0
        self.pipeline = PipelineRunner(None)

    def call(self, stage, req, *, provider=None, maximum=None):
        self.seq += 1; self.executed.append(stage)
        if stage.startswith('embed-'):
            texts = req['data']['texts']; path = Path(req['data']['output'])
            artifact = {'texts_sha256': digest(texts), 'model': p.framed_embedding.MODEL,
                        'revision': p.framed_embedding.REVISION, 'local_files_only': True,
                        'vectors': {sid: [1., 0.] for sid in texts}}
            write(path, artifact)
            return {**artifact, 'output': str(path), 'sha256': sha(path)}
        if stage == 'runtime':
            core = req['data']['PERSPECTIVE']['core_claim_id']
            missing = 'exact annual' in req['data']['QUESTION']
            return {'errors': [], 'output': {'answerability': 'not_in_evidence' if missing else 'grounded',
                'claim_ids': [] if missing else [core], 'limitation': 'missing_evidence' if missing else 'none'}}
        return self.pipeline.call(stage, req)


class FramedCorpusPipelineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.runs = self.root/'runs'; self.directory = self.runs/'new'
        data = fixture.StanceAgentTests(); data.setUp(); self.snapshot = data.snapshot
        self.snapshot_path = self.root/'snapshot.json'; write(self.snapshot_path, self.snapshot.to_dict())
        rows = [{'source_id': s.comment_id, 'source_sha256': digest(s.text_original), 'eligibility': 'meaningful',
                 'reason': 'Authored synthetic reference, not actual corpus evaluation.'} for s in self.snapshot.comments]
        self.reference = utilization.freeze_reference(self.snapshot, rows, evaluator='synthetic-fixture', protocol='before output')
        self.reference_path = self.root/'reference.json'; write(self.reference_path, self.reference)
        self.cycle = self.root/'cycle.json'; write(self.cycle, {
            'goal_revision': 'factory-goal-20261014-r4', 'cycle_id': 'mvp-factory-20261014',
            'analysis_seconds': None, 'limit_seconds': None, 'ledger': str(self.runs/'ledger.sqlite')})
        self.source = self.root/'deployment.json'; write(self.source, {
            'deployments': {'profile': {'server': {'path': 'synthetic', 'sha256': '0'*64},
                'models': {'baseline': {'path': 'synthetic', 'sha256': '0'*64}},
                'runtime': {'reasoning': 'on', 'reasoning_budget': 1024, 'context': 8192}}},
            'model_files': {}, 'classifier': MODEL, 'documents': [], 'selections': []})
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        for patched in (patch.object(p, 'PRIVATE_ROOT', self.runs), patch.object(p, 'file_hash', return_value='0'*64),
                        patch.object(p, 'code_hashes', return_value={}), patch.object(p, 'Runner', FakeBase),
                        patch.object(p, 'owned_server', return_value=nullcontext())):
            self.stack.enter_context(patched)
        self.budget = Mock(); self.budget.summary.return_value = {'calls': [], 'synthetic': True}
        self.stack.enter_context(patch.object(p, 'InferenceBudget', return_value=self.budget))
        FakeBase.executed = []

    def prepare(self): p.prepare(self.directory, self.snapshot_path, self.reference_path, self.source, self.cycle)

    def test_complete_bound_corpus_path_and_existing_runtime(self):
        self.prepare(); report = p.run(self.directory)
        self.assertEqual(report['canonical_population'], 5); self.assertEqual(report['compiled_profiles'], 1)
        self.assertEqual(report['runtime_turns'], 3); self.assertTrue(report['execution_complete'])
        self.assertFalse(report['quality_gate_passed']); self.assertIsNone(report['correct_comment_utilization'])
        self.assertEqual(read_json(self.directory/'plan.json')['reference']['sha256'], digest(self.reference))
        before = len(FakeBase.executed); p.run(self.directory)
        self.assertEqual(len(FakeBase.executed), before)

    def test_same_plan_resumes_completed_analysis_without_new_model_calls(self):
        self.prepare()
        with patch.object(p, 'runtime_probe', side_effect=RuntimeError('interrupted after analysis')):
            with self.assertRaises(RuntimeError): p.run(self.directory)
        self.assertTrue((self.directory/'attempts/0001.failed.json').exists())
        FakeBase.executed = []
        report = p.run(self.directory)
        self.assertGreater(report['same_plan_reused_calls_this_attempt'], 0)
        self.assertEqual(FakeBase.executed, ['runtime'] * 3)
        self.assertTrue((self.directory/'attempts/0002.started.json').exists())

    def test_reference_uncertainty_is_not_excluded_or_turned_into_full_pass(self):
        rows = [{**r, 'eligibility': 'uncertain'} for r in self.reference['rows']]
        reference = utilization.freeze_reference(self.snapshot, rows, evaluator='synthetic', protocol='before output')
        with self.assertRaisesRegex(ValueError, 'Complete'): p.reference_check(self.snapshot, reference, digest(reference))
        sample = utilization.freeze_reference(self.snapshot, self.reference['rows'][:2], evaluator='synthetic',
                                             protocol='before output', scope_ids=[r['source_id'] for r in self.reference['rows'][:2]])
        with self.assertRaisesRegex(ValueError, 'Complete'): p.reference_check(self.snapshot, sample, digest(sample))

    def test_foreign_or_changed_reference_cannot_start(self):
        with self.assertRaises(ValueError): p.reference_check(self.snapshot, self.reference, 'changed')

    def test_output_must_remain_private(self):
        with self.assertRaisesRegex(ValueError, 'private'):
            p.prepare(self.root/'public', self.snapshot_path, self.reference_path, self.source, self.cycle)

    def test_advisory_lock_prevents_simultaneous_execution(self):
        self.prepare()
        with p.experiment_lock(self.directory):
            with self.assertRaisesRegex(RuntimeError, 'live executor'):
                with p.experiment_lock(self.directory): pass
        with p.experiment_lock(self.directory): pass


if __name__ == '__main__': unittest.main()
