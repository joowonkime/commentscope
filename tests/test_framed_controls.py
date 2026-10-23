from contextlib import nullcontext
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import framed_cluster_controls as p


class FakeRunner:
    calls = []
    fail_source = None

    def __init__(self, directory, plan, budget):
        self.plan_sha = sha(directory/'plan.json')

    def call(self, stage, req):
        self.calls.append((stage, req))
        data = req['data']
        if stage.startswith('frame-'):
            sid = data['SOURCE_ID']
            if sid == self.fail_source: return {'errors': ['transport_error'], 'output': None}
            value = {'status': 'positions', 'positions': [{
                'target': 'safety reviews' if sid != 'F' else 'public notices',
                'statement': data['SOURCE_SEGMENTS'][0]['text'].strip(),
                'mode': 'normative', 'entity': 'reviews' if sid != 'F' else 'notices',
                'time': '', 'segment_ids': ['S000'], 'qualifications': [], 'reasons': []}]}
        elif stage == 'automatic-discovery':
            value = {'candidates': [{'contract': p.TARGET,
                                    'nominees': [v['id'] for v in data['POSITION_VIEWS'][:3]]}]}
        else:
            sid = data['ORIGINAL']['id']
            relation = 'supported' if sid in 'ABC' else {'D': 'conditional', 'E': 'opposed', 'F': 'unrelated'}[sid]
            value = {'frame_fidelity': 'faithful', 'premise_completeness': 'preserved',
                     'relation': relation, 'qualifications': [], 'reason': 'Synthetic transport stub.'}
        return {'errors': [], 'output': value}


class FramedControlsTests(TestCase):
    def run_control(self, *, fail_source=None):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name)
        plan = {'artifact_kind': p.VERSION, 'fixed_target': p.TARGET,
                'inputs': {}, 'code_sha256': {}, 'deployment': {
                    'server': {'path': 'synthetic', 'sha256': 'fake'},
                    'models': {'baseline': {'path': 'synthetic', 'sha256': 'fake'}}},
                'snapshot_sha256': digest(p.synthetic_snapshot().to_dict()),
                'budget': {'ledger': 'synthetic', 'cycle_id': 'synthetic'},
                'cases': [{'id': sid, 'expected_fixed_target_support': expected} for sid, _, expected in p.CASES]}
        write(directory/'plan.json', plan)
        FakeRunner.calls = []; FakeRunner.fail_source = fail_source
        budget = Mock(); budget.summary.return_value = {'calls': [], 'synthetic': True}
        with patch.object(p, 'file_hash', return_value='fake'), patch.object(p, 'AllocatedRunner', FakeRunner), \
             patch.object(p, 'InferenceBudget', return_value=budget), \
             patch.object(p, 'owned_server', return_value=nullcontext()):
            p.run(directory)
        return directory, read_json(directory/'completed.json')

    def test_complete_synthetic_path_has_no_runtime_reference_labels(self):
        directory, report = self.run_control()
        self.assertTrue(report['fixed_target_controls_passed'])
        self.assertEqual(report['positive_retained'], 3)
        self.assertFalse(report['quality_gate_passed'])
        self.assertFalse(report['fresh_corpus_analysis'])
        self.assertTrue((directory/'automatic-proposals.json').exists())
        self.assertTrue((directory/'cluster-output.json').exists())
        self.assertTrue(all('expected' not in str(req['data']) for _, req in FakeRunner.calls))

    def test_failed_source_remains_missing_not_repaired_or_excluded(self):
        _, report = self.run_control(fail_source='B')
        self.assertFalse(report['fixed_target_controls_passed'])
        self.assertEqual(len(report['rows']), 6)
        self.assertEqual(report['positive_retained'], 2)
        self.assertEqual(next(r for r in report['rows'] if r['source_id'] == 'B')['actual_relation'], 'unassessed')

    def test_old_cycle_cap_cannot_be_copied_into_new_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = Path(tmp)/'cycle.json'
            write(cycle, {'goal_revision': 'factory-goal-20261014-r4', 'cycle_id': 'mvp-factory-20261014',
                          'analysis_seconds': 3600, 'limit_seconds': 28800})
            with self.assertRaisesRegex(ValueError, 'uncapped'):
                p.prepare(Path(tmp)/'new', Path(tmp)/'absent-deployment', cycle)

    def test_existing_experiment_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                p.prepare(Path(tmp), Path('unused'), Path('unused'))

    def test_allocated_runner_forwards_total_generation_limit(self):
        runner = object.__new__(p.AllocatedRunner)
        runner.plan = {'deployment': {'runtime': {'reasoning': 'on', 'reasoning_budget': 1024, 'context': 8192}}}
        req = {'system': 'test', 'data': {}, 'schema': {}, 'max_tokens': 1024}
        with patch.object(p.Runner, 'call', return_value={'output': 'stub'}) as call:
            self.assertEqual(runner.call('membership', req), {'output': 'stub'})
            self.assertEqual(call.call_args.args[1]['max_tokens'], 2048)
        self.assertEqual(req['max_tokens'], 1024)
