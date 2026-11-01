"""Real synthetic artifacts bind the full review inventory; no model is called."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.agents.runtime_probe import runtime_probe
from commentscope.factory import acceptance
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import minimal_factory_pipeline as executor
from experiments import minimal_factory_review as review
import test_minimal_pipeline as pipeline_fixture


class ReviewPacketBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='runs', prefix='test-packet-binding-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run = self.root/'run'
        self.directory = self.root/'review'
        factory = pipeline_fixture.MinimalPipelineTests()
        factory.setUp()
        texts = {}
        for sid in 'ABCDEFGHIJKL':
            if sid in 'ABCIJ': text = f'Adopt P because Reason {sid} matters.'
            elif sid in 'EGL': text = f'Reject P because Other reason {sid} matters.'
            else: text = f'Consider separate proposal {sid}.'
            texts[sid] = text
        factory.snapshot = replace(factory.snapshot, comments=tuple(
            replace(factory.snapshot.comments[0], comment_id=sid, text_original=text)
            for sid, text in texts.items()))
        runner = pipeline_fixture.ScriptedRunner()
        output = factory.process(runner)
        runtime = runtime_probe(output['agent_inputs']['bundle'], runner)
        self.assertEqual(len(output['agent_inputs']['compiled']['profiles']), 2)
        profile = read_json('tests/fixtures/factory-acceptance-r5.json')
        snapshot = self.run/'snapshot.json'
        write(snapshot, factory.snapshot.to_dict())
        plan = {'artifact_kind': executor.VERSION, 'run_directory': str(self.run),
                'gate': 'G1', 'goal_revision': acceptance.R5,
                'acceptance_profile': profile, 'acceptance_profile_sha256': digest(profile),
                'snapshot': str(snapshot), 'snapshot_sha256': sha(snapshot),
                'questions': deepcopy(review.QUESTIONS),
                'scope_ids': sorted(texts), 'reference_runtime_input': False,
                'cross_run_response_reuse': False}
        write(self.run/'plan.json', plan)
        write(self.run/'artifacts/output.json', output)
        write(self.run/'artifacts/runtime.json', runtime)
        write(self.run/'artifacts/initial-candidates.json', factory.saved['initial-candidates'])
        write(self.run/'completed.json', {
            'execution_complete': True, 'plan_sha256': sha(self.run/'plan.json'),
            'output_sha256': sha(self.run/'artifacts/output.json'),
            'runtime_sha256': sha(self.run/'artifacts/runtime.json'),
            'binding_errors': 0, 'fresh_run': True})
        self.fact_report = {'passed': True, 'supported_kept': 9,
                            'unsupported_false_support': 0, 'fresh_inference': False}
        facts = patch.object(review, 'replay_benchmark', return_value=self.fact_report)
        facts.start(); self.addCleanup(facts.stop)
        review.prepare(self.directory, self.run)
        self.packet = read_json(self.directory/'packet.json')
        self.labels = {c['id']: ('mandatory' if c['text'] == 'Adopt P.' else
                                'voluntary' if c['text'] == 'Reject P.' else None)
                       for c in output['candidates']}

    def evaluate(self, *, reverse_review=False):
        # Re-hash a changed packet as an editor could; hashes alone are insufficient.
        (self.directory/'packet.json').write_text(json.dumps(self.packet))
        unique = {t['id']: t for t in self.packet['tasks']}
        rows = [{'id': t['id'], 'verdict': 'pass', 'reason': 'Authored synthetic test only.',
                 'omissions': [], 'label': self.labels.get(t['key'])
                 if t['kind'] in ('candidate', 'agent') else None} for t in unique.values()]
        if reverse_review: rows.reverse()
        write(self.directory/'review.json', {
            'artifact_kind': review.R5_VERSION+'-review', 'packet_sha256': digest(self.packet),
            'evaluator': 'synthetic_fixture_not_semantic_gold', 'rows': rows})
        return review.evaluate(self.directory, self.directory/'review.json', self.directory/'result.json')

    def test_original_complete_packet_can_be_reviewed(self):
        result = self.evaluate()
        self.assertTrue(result['gate_passed'])
        self.assertFalse(result['factory_complete'])

    def test_review_order_can_change_without_altering_the_packet(self):
        self.assertTrue(self.evaluate(reverse_review=True)['gate_passed'])

    def test_omitting_counted_support_cannot_be_hidden_by_rehashing(self):
        victim = next(t for t in self.packet['tasks'] if t['kind'] == 'support')
        self.packet['tasks'].remove(victim)
        with self.assertRaisesRegex(ValueError, 'immutable run'):
            self.evaluate()

    def test_substituting_source_or_claim_cannot_be_hidden_by_rehashing(self):
        victim = next(t for t in self.packet['tasks'] if t['kind'] == 'support')
        victim['data']['claim'] = 'An invented different position.'
        with self.assertRaisesRegex(ValueError, 'immutable run'):
            self.evaluate()

    def test_duplicated_task_cannot_disappear_in_the_task_dictionary(self):
        self.packet['tasks'].append(deepcopy(self.packet['tasks'][0]))
        with self.assertRaisesRegex(ValueError, 'immutable run'):
            self.evaluate()

    def test_agent_runtime_inventory_cannot_be_removed(self):
        self.packet['tasks'] = [t for t in self.packet['tasks'] if t['kind'] != 'runtime']
        with self.assertRaisesRegex(ValueError, 'immutable run'):
            self.evaluate()

    def test_benchmark_summary_cannot_be_rewritten(self):
        self.packet['fact_benchmark']['supported_kept'] = 10
        with self.assertRaisesRegex(ValueError, 'immutable run'):
            self.evaluate()

    def test_benchmark_pass_flag_cannot_replace_the_replayed_result(self):
        self.fact_report['passed'] = False
        with self.assertRaisesRegex(ValueError, 'immutable run'):
            self.evaluate()

    def test_numeric_zero_does_not_replace_the_frozen_boolean_metadata(self):
        self.packet['runtime_input'] = 0
        with self.assertRaisesRegex(ValueError, 'immutable run'):
            self.evaluate()

    def test_consistent_hashes_and_pass_verdicts_cannot_approve_invalid_runtime(self):
        baseline = read_json(self.run/'artifacts/runtime.json')
        mutations = {
            'history': lambda r: r['turns'][0].update(other_histories_unchanged=False),
            'owner': lambda r: r['turns'][0]['turn'].update(candidate_id='another-agent'),
            'question': lambda r: r['turns'][0]['turn'].update(question='A different question'),
            'status': lambda r: r['turns'][0]['turn'].update(status='error'),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                runtime = deepcopy(baseline); mutate(runtime)
                (self.run/'artifacts/runtime.json').write_text(json.dumps(runtime))
                completed = read_json(self.run/'completed.json')
                completed['runtime_sha256'] = sha(self.run/'artifacts/runtime.json')
                (self.run/'completed.json').write_text(json.dumps(completed))
                self.directory = self.root/('review-'+label)
                review.prepare(self.directory, self.run)
                self.packet = read_json(self.directory/'packet.json')
                result = self.evaluate()
                self.assertFalse(result['requirements']['all_runtime_turns_valid'])
                self.assertFalse(result['gate_passed'])
                self.assertTrue(result['runtime_contract_errors'])
                self.assertTrue(all(value for key, value in result['requirements'].items()
                                    if key != 'all_runtime_turns_valid'))


if __name__ == '__main__':
    unittest.main()
