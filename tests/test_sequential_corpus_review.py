"""New execution contract to existing evaluation, with synthetic models only."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import sequential_corpus_pipeline as pipeline
from experiments import sequential_corpus_review as review
from tests import test_sequential_corpus_pipeline as fixture


class SequentialReviewTests(unittest.TestCase):
    def setUp(self):
        self.execution = fixture.SequentialCorpusTests(); self.execution.setUp()
        self.addCleanup(self.execution.doCleanups)
        self.execution.prepare(); pipeline.run(self.execution.directory)
        self.run = self.execution.directory
        self.directory = self.execution.runs/'review'
        self.output = self.execution.runs/'evaluation.json'

    def part(self, count=3):
        part = read_json(self.directory/'part-template.json')
        part['evaluator'] = 'synthetic-test-author-not-independent-gold'
        for row in part['clusters']: row.update(verdict='coherent', reason='Authored synthetic shared stance.')
        part['supports'] = part['supports'][:count]
        for row in part['supports']: row.update(verdict='supported', reason='Authored synthetic direct support.')
        return part

    def execute_review(self, part):
        path = self.execution.runs/'part.json'; write(path, part)
        return review.evaluate(self.directory, [path], self.output)

    def test_full_execution_packet_and_review_without_model_or_runtime_mutation(self):
        before = {str(p): sha(p) for p in self.run.rglob('*.json')}
        call_count = len(self.execution.requests)
        with patch.object(pipeline, 'Runner', side_effect=AssertionError('No inference in review')), \
                patch.object(pipeline, 'file_hash', side_effect=AssertionError('No model weight reads in review')):
            prepared = review.prepare(self.directory, self.run)
            self.assertEqual(prepared, {'clusters': 1, 'counted_support_relations': 3,
                'canonical_population': 5, 'semantic_verdicts': 0, 'new_model_calls': 0})
            template = read_json(self.directory/'part-template.json')
            self.assertTrue(all(r['verdict'] is None for r in template['supports'] + template['clusters']))
            result = self.execute_review(self.part())
        self.assertEqual(result['meaningful_sources'], 5)
        self.assertEqual(result['correct_comment_utilization'], .6)
        self.assertTrue(result['support_validity_passed']); self.assertFalse(result['corpus_clustering_target_met'])
        self.assertEqual(result['mvp_acceptance'], 'not_evaluated')
        self.assertEqual(result['agent_approval'], 'not_evaluated')
        self.assertFalse(result['runtime_input']); self.assertFalse(result['independent_gold'])
        self.assertEqual(before, {str(p): sha(p) for p in self.run.rglob('*.json')})
        self.assertEqual(call_count, len(self.execution.requests))

    def test_partial_review_keeps_full_denominator_and_unknown_supports(self):
        review.prepare(self.directory, self.run)
        result = self.execute_review(self.part(2))
        self.assertEqual(result['meaningful_sources'], 5)
        self.assertEqual(result['correct_comment_utilization'], .4)
        self.assertEqual(result['support_counts']['unreviewed'], 1)
        self.assertFalse(result['support_validity_passed'])

    def test_wrong_support_cannot_be_offset_by_correct_contributions(self):
        review.prepare(self.directory, self.run); part = self.part()
        part['supports'][-1].update(verdict='not_supported', reason='Authored incorrect synthetic assignment.')
        result = self.execute_review(part)
        self.assertEqual(result['correct_comment_utilization'], .4)
        self.assertEqual(result['support_counts']['not_supported'], 1)
        self.assertFalse(result['support_validity_passed'])

    def test_empty_review_never_counts_model_support_as_verified(self):
        review.prepare(self.directory, self.run)
        result = review.evaluate(self.directory, [], self.output)
        self.assertEqual(result['meaningful_sources'], 5)
        self.assertEqual(result['correct_comment_utilization'], 0)
        self.assertEqual(result['support_counts']['unreviewed'], 3)

    def test_rejects_missing_map_and_source_map_mismatch(self):
        target = self.run/'artifacts/map.json'
        target.rename(self.run/'artifacts/map-backup.json')
        with self.assertRaisesRegex(ValueError, 'Final membership map'):
            review.prepare(self.directory, self.run)
        write(target, {})
        with self.assertRaisesRegex(ValueError, 'reconstruction'):
            review.prepare(self.directory, self.run)

    def test_foreign_execution_contract_is_not_coerced_into_supported_version(self):
        path = self.run/'plan.json'; plan = read_json(path)
        plan['artifact_kind'] = 'frozen-whole-framed-corpus-pipeline-0.1'
        path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, 'execution contract'):
            review.prepare(self.directory, self.run)

    def test_frozen_packet_and_membership_tampering_are_rejected(self):
        review.prepare(self.directory, self.run)
        packet = read_json(self.directory/'packet.json'); changed = deepcopy(packet)
        changed['sources']['s0']['text'] = 'A fabricated opinion.'
        (self.directory/'packet.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'packet changed'):
            review.evaluate(self.directory, [], self.output)
        (self.directory/'packet.json').write_text(json.dumps(packet))
        (self.run/'artifacts/memberships.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'inputs/code changed'):
            review.evaluate(self.directory, [], self.output)

    def test_private_and_non_overwriting_output_boundaries(self):
        with self.assertRaisesRegex(ValueError, 'private'):
            review.prepare(self.execution.root/'outside', self.run)
        review.prepare(self.directory, self.run)
        with self.assertRaisesRegex(ValueError, 'overwrite'): review.prepare(self.directory, self.run)
        with self.assertRaisesRegex(ValueError, 'private'):
            review.evaluate(self.directory, [], self.execution.root/'outside.json')


if __name__ == '__main__': unittest.main()
