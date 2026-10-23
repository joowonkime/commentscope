"""Offline all-Agent review integration; all model answers are synthetic."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import sequential_agent_review as review
from experiments import sequential_corpus_pipeline as pipeline
from experiments.framed_agent_probe import runtime_probe
from tests import test_sequential_corpus_pipeline as fixture


class SequentialAgentReviewTests(unittest.TestCase):
    def setUp(self):
        self.execution = fixture.SequentialCorpusTests(); self.execution.setUp()
        self.addCleanup(self.execution.doCleanups)
        self.run = self.execution.directory
        self.directory = self.execution.runs/'agent-review'

    def execute(self):
        self.execution.prepare(); pipeline.run(self.run)

    def part(self):
        part = read_json(self.directory/'part-template.json')
        part['evaluator'] = 'synthetic-test-author-not-independent-gold'
        for row in part['rows']:
            row.update(verdict='pass', reason='Authored synthetic verdict for evaluator mechanics only.')
        return part

    def evaluate(self, part=None, name='evaluation'):
        paths = []
        if part is not None:
            path = self.execution.runs/(name + '-part.json'); write(path, part); paths.append(path)
        return review.evaluate(self.directory, paths, self.execution.runs/(name + '.json'))

    def replace_json(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_all_profile_entries_and_fixed_turns_blank_without_inference_or_mutation(self):
        self.execute(); before = {str(p): sha(p) for p in self.run.rglob('*.json')}
        count = len(self.execution.requests)
        with patch.object(pipeline, 'Runner', side_effect=AssertionError('No inference')), \
                patch.object(pipeline, 'file_hash', side_effect=AssertionError('No model weight reads')):
            prepared = review.prepare(self.directory, self.run)
            result = self.evaluate()
        packet = read_json(self.directory/'packet.json')
        self.assertEqual(prepared['generated_agents'], 1)
        profile = packet['agents'][0]['profile']
        self.assertEqual(len([t for t in packet['tasks'] if t['kind'] == 'entry']), len(profile['prompt_entries']))
        self.assertEqual(len([t for t in packet['tasks'] if t['kind'] == 'runtime_turn']), 3)
        self.assertTrue(all(r['verdict'] is None for r in packet['review_template']))
        self.assertEqual(result['review_counts']['unreviewed'], prepared['review_tasks'])
        self.assertFalse(result['agent_content_runtime_review_passed'])
        self.assertEqual(result['mvp_acceptance'], 'not_evaluated')
        self.assertIsNone(result['correct_comment_utilization'])
        self.assertEqual(before, {str(p): sha(p) for p in self.run.rglob('*.json')})
        self.assertEqual(count, len(self.execution.requests))

    def test_partial_failed_and_uncertain_reviews_never_become_all_pass(self):
        self.execute(); review.prepare(self.directory, self.run)
        full = self.part(); count = len(full['rows'])
        partial = deepcopy(full); partial['rows'] = partial['rows'][:1]
        result = self.evaluate(partial, 'partial')
        self.assertEqual(result['review_counts']['unreviewed'], count - 1)
        for verdict in ('fail', 'uncertain'):
            part = deepcopy(full); part['rows'][-1]['verdict'] = verdict
            result = self.evaluate(part, verdict)
            self.assertEqual(result['review_counts'][verdict], 1)
            self.assertFalse(result['all_tasks_reviewed_pass'])
            self.assertFalse(result['agent_content_runtime_review_passed'])

    def test_one_agent_all_pass_is_not_minimum_two_or_complete_mvp(self):
        self.execute(); review.prepare(self.directory, self.run)
        result = self.evaluate(self.part())
        self.assertTrue(result['all_tasks_reviewed_pass'])
        self.assertFalse(result['agent_content_runtime_review_passed'])
        self.assertEqual(result['source_support_validity'], 'not_evaluated_here')
        self.assertEqual(result['fixed_fact_benchmark'], 'not_evaluated_here')
        self.assertEqual(result['mvp_acceptance'], 'not_evaluated')

    def test_duplicate_unknown_changed_or_unfinished_rows_are_rejected(self):
        self.execute(); review.prepare(self.directory, self.run); original = self.part()
        cases = []
        duplicate = deepcopy(original); duplicate['rows'].append(deepcopy(duplicate['rows'][0])); cases.append(duplicate)
        for key, value in [('task_id', 'unknown'), ('task_sha256', 'changed'), ('verdict', None), ('reason', '')]:
            changed = deepcopy(original); changed['rows'][0][key] = value; cases.append(changed)
        for i, part in enumerate(cases):
            with self.subTest(i=i), self.assertRaisesRegex(ValueError, 'review task'):
                self.evaluate(part, 'bad' + str(i))

    def test_missing_completion_cannot_promote_analysis_to_runtime_completion(self):
        self.execute(); (self.run/'completed.json').rename(self.run/'completed-backup.json')
        with self.assertRaisesRegex(ValueError, 'Completed Agent/output/runtime'):
            review.prepare(self.directory, self.run)

    def test_output_agent_bundle_and_argument_reconstruction_bindings(self):
        self.execute()
        path = self.run/'artifacts/agent-inputs.json'; original = read_json(path)
        altered = deepcopy(original); altered['compiled']['profiles'][0]['model_core_support_count'] = 999
        self.replace_json(path, altered)
        with self.assertRaisesRegex(ValueError, 'artifact bindings'):
            review.prepare(self.directory, self.run)
        self.replace_json(path, original)
        path = self.run/'artifacts/analyses.json'; analyses = read_json(path)
        analyses[0]['source_sha256'] = 'changed'; self.replace_json(path, analyses)
        with self.assertRaisesRegex(ValueError, 'Source argument record changed'):
            review.prepare(self.directory, self.run)

    def test_runtime_replay_rejects_changed_citations_even_if_completion_hash_is_recomputed(self):
        self.execute(); path = self.run/'artifacts/runtime.json'; runtime = read_json(path)
        runtime['turns'][0]['turn']['points'][0]['citations']['comment_evidence'][0]['span']['text'] = 'Fabricated citation.'
        self.replace_json(path, runtime)
        report = read_json(self.run/'completed.json'); report['runtime_sha256'] = digest(runtime)
        self.replace_json(self.run/'completed.json', report)
        with self.assertRaisesRegex(ValueError, 'replay differs'):
            review.prepare(self.directory, self.run)

    def test_runtime_replay_checks_all_sessions_and_history_requests(self):
        self.execute(); bundle = read_json(self.run/'artifacts/agent-inputs.json')['bundle']
        # A second synthetic ID shares the claim only to exercise isolation, not
        # to establish two semantically distinct real Agents.
        second = deepcopy(bundle['candidates'][0]); second['id'] += '-second'
        bundle['candidates'].append(second)
        class Selection:
            def call(self, stage, req):
                missing = 'exact annual' in req['data']['QUESTION']
                return {'errors': [], 'output': {'answerability': 'not_in_evidence' if missing else 'grounded',
                    'claim_ids': [] if missing else [req['data']['PERSPECTIVE']['core_claim_id']],
                    'limitation': 'missing_evidence' if missing else 'none'}}
        runtime = runtime_probe(bundle, Selection())
        self.assertEqual(review.replay_runtime(bundle, runtime)['replayed_turns'], 6)
        changed = deepcopy(runtime); changed['turns'][3]['turn']['request_sha256'] = 'foreign history'
        with self.assertRaisesRegex(ValueError, 'replay differs'): review.replay_runtime(bundle, changed)
        changed = deepcopy(runtime); changed['turns'][0]['other_histories_unchanged'] = False
        with self.assertRaisesRegex(ValueError, 'replay differs'): review.replay_runtime(bundle, changed)

    def test_unverified_essential_facts_keep_no_agent_output_and_deferrals(self):
        self.execution.fact_mode = True; self.execute()
        review.prepare(self.directory, self.run); packet = read_json(self.directory/'packet.json')
        self.assertEqual(packet['agents'], []); self.assertTrue(packet['fact_deferrals'])
        self.assertTrue(any(c['requires'] for c in packet['claims']))
        result = self.evaluate(self.part())
        self.assertFalse(result['agent_content_runtime_review_passed'])
        self.assertEqual(result['generated_agents'], 0)

    def test_recorded_runtime_errors_remain_errors_not_successful_abstentions(self):
        self.execute(); bundle = read_json(self.run/'artifacts/agent-inputs.json')['bundle']
        class BadSelection:
            def call(self, stage, req):
                return {'errors': [], 'output': {'answerability': 'grounded',
                    'claim_ids': ['foreign-claim'], 'limitation': 'none'}}
        runtime = runtime_probe(bundle, BadSelection())
        replayed = review.replay_runtime(bundle, runtime)
        self.assertEqual(replayed['error_turns'], 3)
        self.assertTrue(all(r['turn']['status'] == 'error' for r in runtime['turns']))
        changed = deepcopy(runtime); changed['turns'][0]['turn']['status'] = 'abstain'
        with self.assertRaisesRegex(ValueError, 'replay differs'): review.replay_runtime(bundle, changed)

    def test_parts_with_different_evaluators_or_packet_bindings_are_not_combined(self):
        self.execute(); review.prepare(self.directory, self.run)
        part = self.part(); first = deepcopy(part); first['rows'] = part['rows'][:1]
        second = deepcopy(part); second['rows'] = part['rows'][1:]; second['evaluator'] = 'different-protocol'
        one = self.execution.runs/'one.json'; two = self.execution.runs/'two.json'
        write(one, first); write(two, second)
        with self.assertRaisesRegex(ValueError, 'different evaluator'):
            review.evaluate(self.directory, [one, two], self.execution.runs/'mixed.json')
        changed = deepcopy(part); changed['packet_sha256'] = 'different-packet'
        with self.assertRaisesRegex(ValueError, 'review part'): self.evaluate(changed, 'wrong-packet')

    def test_packet_inventory_includes_every_agent_and_exposed_fact(self):
        self.execute(); packet, _ = review.load_run(self.run)
        plan = read_json(self.run/'plan.json'); output = read_json(self.run/'artifacts/output.json')
        _, _, opinion, _ = review.corpus_review.load_run(self.run)
        analyses = read_json(self.run/'artifacts/analyses.json'); runtime = read_json(self.run/'artifacts/runtime.json')
        inputs = output['agent_inputs']; first = inputs['compiled']['profiles'][0]
        first['prompt_entries'][0]['kind'] = 'fact'
        second = deepcopy(first); second['candidate_id'] += '-second'
        inputs['compiled']['profiles'].append(second)
        candidate = deepcopy(inputs['bundle']['candidates'][0]); candidate['id'] = second['candidate_id']
        inputs['bundle']['candidates'].append(candidate)
        perspective = deepcopy(opinion['opinion_map']['perspectives'][0]); perspective['id'] = second['candidate_id']
        opinion['opinion_map']['perspectives'].append(perspective)
        # Packet inventory test only: deliberately changed synthetic data cannot
        # pass load_run's real source/compilation reconstruction.
        prepared = review.packet(plan, opinion, output, analyses, runtime, packet['mechanical_runtime_replay'])
        self.assertEqual(len(prepared['agents']), 2)
        self.assertEqual(len([t for t in prepared['tasks'] if t['kind'] == 'agent_contract']), 2)
        self.assertEqual(len([t for t in prepared['tasks'] if t['kind'] == 'fact']), 2)

    def test_packet_tampering_private_output_and_no_overwrite(self):
        self.execute()
        with self.assertRaisesRegex(ValueError, 'private'):
            review.prepare(self.execution.root/'outside', self.run)
        review.prepare(self.directory, self.run)
        with self.assertRaisesRegex(ValueError, 'overwrite'): review.prepare(self.directory, self.run)
        with self.assertRaisesRegex(ValueError, 'private'):
            review.evaluate(self.directory, [], self.execution.root/'outside.json')
        packet = read_json(self.directory/'packet.json'); packet['agents'] = []
        self.replace_json(self.directory/'packet.json', packet)
        with self.assertRaisesRegex(ValueError, 'packet changed'): self.evaluate()


if __name__ == '__main__': unittest.main()
