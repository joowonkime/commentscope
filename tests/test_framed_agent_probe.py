from contextlib import nullcontext
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from commentscope.factory import position_frames as frames, framed_clusters as clusters
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import framed_agent_probe as p
from tests.test_stance_agents import Runner as ArgumentRunner


class FakeRunner(ArgumentRunner):
    recorded = []
    fail_source = None

    def __init__(self, directory, plan, budget):
        super().__init__(); self.plan_sha = sha(directory/'plan.json')

    def call(self, stage, req):
        self.recorded.append((stage, req))
        if stage.endswith('membership'):
            sid = req['data']['SOURCE_ID']
            if sid == self.fail_source: return {'errors': ['transport_error'], 'output': None}
            return {'errors': [], 'output': {'relation': p.EXPECTED_RELATIONS[sid],
                'authorship': 'asserted_or_endorsed', 'scope_preserved': 'no' if sid == 'D' else 'yes',
                'evidence_segment_ids': ['S000']}}
        if stage == 'runtime':
            core = req['data']['PERSPECTIVE']['core_claim_id']
            missing = 'exact annual' in req['data']['QUESTION']
            return {'errors': [], 'output': {'answerability': 'not_in_evidence' if missing else 'grounded',
                     'claim_ids': [] if missing else [core], 'limitation': 'missing_evidence' if missing else 'none'}}
        return super().call(stage, req)


class FramedAgentProbeTests(TestCase):
    def setup_source(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); source = root/'source'; directory = root/'probe'; cycle = root/'cycle.json'
        snapshot = p.synthetic_snapshot()
        deployment = {'server': {'path': 'synthetic', 'sha256': '0'*64},
                      'models': {'baseline': {'path': 'synthetic', 'sha256': '0'*64}},
                      'runtime': {'reasoning': 'on', 'reasoning_budget': 1024, 'context': 8192}}
        write(source/'plan.json', {'artifact_kind': 'framed-cluster-synthetic-controls-0.2',
             'deployment': deployment, 'snapshot_sha256': digest(snapshot.to_dict())})
        write(source/'completed.json', {'plan_sha256': sha(source/'plan.json')})
        records = []
        for comment in snapshot.comments:
            record = frames.bind(frames.source_packet(snapshot, comment.comment_id), {'output': {
                'status': 'positions', 'positions': [{'target': 'synthetic', 'statement': comment.text_original,
                'mode': 'normative', 'entity': 'synthetic', 'time': '', 'segment_ids': ['S000'],
                'qualifications': [], 'reasons': []}]}})
            records.append(record); write(source/'frames'/(comment.comment_id + '.json'), record)
        candidate = clusters.proposals(records, {'output': {'candidates': [{
            'contract': p.TARGET, 'nominees': [r['positions'][0]['id'] for r in records[:3]]}]}})
        write(source/'automatic-proposals.json', candidate)
        write(cycle, {'goal_revision': 'factory-goal-20261014-r4', 'cycle_id': 'mvp-factory-20261014',
                      'analysis_seconds': None, 'limit_seconds': None, 'ledger': str(root/'ledger')})
        return directory, source, cycle

    def run_probe(self, fail_source=None):
        directory, source, cycle = self.setup_source()
        FakeRunner.recorded = []; FakeRunner.fail_source = fail_source
        budget = Mock(); budget.summary.return_value = {'calls': [], 'synthetic': True}
        with patch.object(p, 'file_hash', return_value='0'*64), patch.object(p, 'code_hashes', return_value={}):
            p.prepare(directory, source, cycle)
            with patch.object(p, 'AllocatedRunner', FakeRunner), patch.object(p, 'InferenceBudget', return_value=budget), \
                 patch.object(p, 'owned_server', return_value=nullcontext()): p.run(directory)
        return directory, read_json(directory/'completed.json')

    def test_all_automatic_candidates_through_actual_runtime_without_labels(self):
        directory, report = self.run_probe()
        self.assertTrue(report['fixed_controls_passed'])
        self.assertEqual(report['automatic_membership_count'], 6)
        self.assertEqual(report['compiled_profiles'], 1)
        self.assertEqual(report['runtime_turns'], 3)
        self.assertFalse(report['quality_gate_passed']); self.assertFalse(report['fresh_corpus_analysis'])
        self.assertTrue((directory/'bundle.json').exists())
        for _, req in FakeRunner.recorded:
            self.assertNotIn('expected', str(req['data']))
        runtime = read_json(directory/'runtime.json')
        self.assertEqual(runtime['turns'][-1]['turn']['status'], 'abstain')

    def test_failed_member_remains_unassessed_and_agent_not_rescued(self):
        directory, report = self.run_probe(fail_source='B')
        self.assertFalse(report['fixed_controls_passed']); self.assertEqual(report['compiled_profiles'], 0)
        mapped = read_json(directory/'map.json')['opinion_map']['perspectives'][0]
        self.assertEqual(mapped['counts']['supported'], 2); self.assertEqual(mapped['counts']['unassessed'], 1)
        self.assertEqual(report['runtime_turns'], 0)

    def test_source_file_change_detected_before_model_calls(self):
        directory, source, cycle = self.setup_source()
        with patch.object(p, 'file_hash', return_value='0'*64), patch.object(p, 'code_hashes', return_value={}):
            p.prepare(directory, source, cycle)
        # Mock the read-side hash; do not modify frozen artifacts.
        with patch.object(p, 'sha', return_value='changed'), patch.object(p, 'owned_server') as server:
            with self.assertRaisesRegex(ValueError, 'Frozen'): p.run(directory)
            server.assert_not_called()

    def test_no_overwrite(self):
        directory, source, cycle = self.setup_source()
        with self.assertRaisesRegex(ValueError, 'overwrite'): p.prepare(source, source, cycle)

    def test_incorrect_completed_plan_binding_rejected(self):
        directory, source, cycle = self.setup_source()
        with patch.object(p, 'sha', return_value='wrong'):
            with self.assertRaisesRegex(ValueError, 'bound'): p.prepare(directory, source, cycle)
