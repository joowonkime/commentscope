"""Offline accounting/identity tests, not semantic model quality measurements."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory import comment_utilization as utilization
from commentscope.factory import position_frames, stance_membership as stance
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import framed_corpus_review as r
from tests import test_stance_agents as fixtures


class FramedCorpusReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StanceAgentTests(); self.fixture.setUp()
        self.snapshot = self.fixture.snapshot
        self.reference = utilization.freeze_reference(self.snapshot,
            [{'source_id': c.comment_id, 'source_sha256': digest(c.text_original), 'eligibility': 'meaningful',
              'reason': 'Synthetic authored stance.'} for c in self.snapshot.comments],
            evaluator='synthetic-test-author', protocol='Authored before synthetic model outputs.')
        self.prepared = self.packet()

    def packet(self):
        return r.packet(self.snapshot, self.reference, self.fixture.frames, [self.fixture.candidate],
                        self.fixture.memberships, digest(self.reference))

    def part(self, count=3):
        template = self.prepared['review_template']
        return {'artifact_kind': r.VERSION + '-part', 'packet_sha256': digest(self.prepared),
                'evaluator': 'synthetic-test-author',
                'clusters': [{**v, 'verdict': 'coherent', 'reason': 'Authored shared stance.'} for v in template['clusters']],
                'supports': [{**v, 'verdict': 'supported', 'reason': 'Authored direct support.'}
                             for v in template['supports'][:count]]}

    def test_packet_contains_all_sources_and_no_prefilled_semantic_verdict(self):
        self.assertEqual(len(self.prepared['sources']), 5)
        template = self.prepared['review_template']
        self.assertEqual(len(template['clusters']), 1); self.assertEqual(len(template['supports']), 3)
        self.assertTrue(all(v['verdict'] is None and v['reason'] == '' for v in template['clusters'] + template['supports']))
        self.assertFalse(self.prepared['runtime_input']); self.assertFalse(self.prepared['quality_gate_passed'])

    def test_missing_review_is_unreviewed_not_model_approved(self):
        out = r.review(self.snapshot, self.reference, self.prepared, [])
        self.assertEqual(out['support_counts']['unreviewed'], 3)
        self.assertEqual(out['correct_comment_utilization'], 0)
        self.assertFalse(out['corpus_clustering_target_met']); self.assertEqual(out['mvp_acceptance'], 'not_evaluated')

    def test_partial_review_has_full_denominator_and_unreviewed_edges(self):
        out = r.review(self.snapshot, self.reference, self.prepared, [self.part(2)])
        self.assertEqual(out['meaningful_sources'], 5); self.assertEqual(out['correct_comment_utilization'], .4)
        self.assertEqual(out['support_counts']['unreviewed'], 1); self.assertFalse(out['support_validity_passed'])
        self.assertEqual(out['agent_approval'], 'not_evaluated')

    def test_single_reviewed_contributor_is_not_a_shared_cluster(self):
        out = r.review(self.snapshot, self.reference, self.prepared, [self.part(1)])
        self.assertEqual(out['correct_comment_utilization'], 0)

    def test_complete_support_review_still_cannot_pass_low_coverage(self):
        out = r.review(self.snapshot, self.reference, self.prepared, [self.part()])
        self.assertTrue(out['support_validity_passed']); self.assertEqual(out['correct_comment_utilization'], .6)
        self.assertFalse(out['corpus_clustering_target_met'])

    def test_wrong_support_is_not_hidden_by_two_correct_supports(self):
        part = self.part(); part['supports'][-1].update(verdict='not_supported', reason='Synthetic incorrect assignment.')
        out = r.review(self.snapshot, self.reference, self.prepared, [part])
        self.assertEqual(out['correct_comment_utilization'], .4)
        self.assertEqual(out['support_counts']['not_supported'], 1); self.assertFalse(out['support_validity_passed'])

    def test_duplicate_parts_and_unfilled_template_are_rejected(self):
        with self.assertRaises(ValueError): r.review(self.snapshot, self.reference, self.prepared, [self.part(), self.part()])
        part = self.part(); part['supports'] = self.prepared['review_template']['supports']
        with self.assertRaises(ValueError): r.review(self.snapshot, self.reference, self.prepared, [part])

    def test_changed_packet_hash_source_hash_and_target_are_rejected(self):
        part = self.part(); part['packet_sha256'] = 'wrong'
        with self.assertRaises(ValueError): r.review(self.snapshot, self.reference, self.prepared, [part])
        part = self.part(); part['supports'][0]['source_sha256'] = 'wrong'
        with self.assertRaises(ValueError): r.review(self.snapshot, self.reference, self.prepared, [part])
        changed = deepcopy(self.prepared); changed['opinion_map']['perspectives'][0]['claim']['text'] = 'Oppose policy P.'
        with self.assertRaises(ValueError): r.review(self.snapshot, self.reference, changed, [])

    def test_available_parent_is_separate_from_author_text(self):
        comments = list(self.snapshot.comments); comments[1] = replace(comments[1], parent_id=comments[0].comment_id)
        self.snapshot = self.fixture.snapshot = replace(self.snapshot, comments=tuple(comments))
        self.fixture.frames = [position_frames.bind(position_frames.source_packet(self.snapshot, f['source']['id']),
                              {'output': f['extraction']}) for f in self.fixture.frames]
        # Nomination hashes change with parent context, so rebuild via the same proposer contract.
        from commentscope.factory import framed_clusters
        self.fixture.candidate = framed_clusters.proposals(self.fixture.frames, {'output': {'candidates': [{
            'contract': self.fixture.candidate['contract'],
            'nominees': [f['positions'][0]['id'] for f in self.fixture.frames[:3]]}]}})[0]
        self.fixture.memberships = [self.fixture.member(i, rel) for i, rel in enumerate(
            ['supported', 'supported', 'supported', 'conditional', 'opposed'])]
        self.reference = utilization.freeze_reference(self.snapshot, self.reference['rows'], evaluator='synthetic', protocol='before output')
        prepared = self.packet(); source = prepared['sources']['s1']
        self.assertEqual(source['text'], comments[1].text_original)
        self.assertEqual(source['parent'], {'id': 's0', 'text': comments[0].text_original})

    def test_empty_output_does_not_remove_any_source_from_denominator(self):
        prepared = r.packet(self.snapshot, self.reference, [], [], [], digest(self.reference))
        out = r.review(self.snapshot, self.reference, prepared, [])
        self.assertEqual(len(prepared['sources']), 5); self.assertEqual(out['meaningful_sources'], 5)
        self.assertEqual(out['correct_comment_utilization'], 0)

    def disk_run(self, root):
        run = root/'run'; snapshot_path = root/'snapshot.json'; reference_path = root/'reference.json'
        write(snapshot_path, self.snapshot.to_dict()); write(reference_path, self.reference)
        plan = {'artifact_kind': 'frozen-whole-framed-corpus-pipeline-0.1', 'runtime_reference_labels': False,
                'snapshot': str(snapshot_path), 'snapshot_file_sha256': sha(snapshot_path),
                'reference': {'path': str(reference_path), 'sha256': digest(self.reference)},
                'inputs': {str(snapshot_path): sha(snapshot_path), str(reference_path): sha(reference_path)}, 'code_sha256': {}}
        write(run/'plan.json', plan); write(run/'started.json', {'plan_sha256': sha(run/'plan.json')})
        for name, value in [('frames', self.fixture.frames), ('candidates', [self.fixture.candidate]),
                            ('memberships', self.fixture.memberships), ('map', stance.assemble_map(
                                self.snapshot, self.fixture.frames, [self.fixture.candidate], self.fixture.memberships))]:
            write(run/'artifacts'/f'{name}.json', value)
        return run

    def test_disk_packet_evaluation_and_tamper_detection_without_runtime_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, 'PRIVATE_ROOT', Path(tmp)):
            root = Path(tmp); run = self.disk_run(root); directory = root/'review'
            before = {str(p): sha(p) for p in run.rglob('*.json')}
            result = r.prepare(directory, run)
            self.assertEqual(result['counted_support_relations'], 3)
            self.assertEqual(result['semantic_verdicts'], 0)
            write(root/'part.json', self.part())
            out = r.evaluate(directory, [root/'part.json'], root/'report.json')
            self.assertEqual(out['correct_comment_utilization'], .6)
            self.assertEqual(before, {str(p): sha(p) for p in run.rglob('*.json')})
            with self.assertRaises(ValueError): r.prepare(directory, run)
            # A source-bearing review packet may not be edited after binding.
            with patch.object(r, 'sha', side_effect=lambda p: 'changed' if str(p).endswith('memberships.json') else sha(p)):
                with self.assertRaises(ValueError): r.evaluate(directory, [], root/'changed-report.json')

    def test_missing_final_map_and_public_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, 'PRIVATE_ROOT', Path(tmp)):
            root = Path(tmp); run = self.disk_run(root)
            with patch.object(Path, 'is_file', return_value=False):
                with self.assertRaisesRegex(ValueError, 'Final membership map'): r.prepare(root/'review', run)
            with self.assertRaisesRegex(ValueError, 'private'): r.prepare(root.parent/'public-review', run)


if __name__ == '__main__': unittest.main()
