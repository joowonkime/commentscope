"""Synthetic accounting tests; these do not measure model semantic quality."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from commentscope.factory import comment_utilization as m, opinion_map
from commentscope.factory.automatic_contract import digest
from commentscope.ingestion import load_snapshot


class CommentUtilizationTests(TestCase):
    def setUp(self):
        raw = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        texts = ['Require safety reviews.', 'Make safety reviews mandatory.',
                 'I support mandatory safety reviews.', 'Safety reviews should be required.',
                 'Require reviews with waivers for small labs.', 'Great video!']
        self.snapshot = replace(raw, usage=replace(raw.usage, expires_at='2099-01-01T00:00:00Z'),
                                comments=tuple(replace(raw.comments[0], comment_id=f's{i}', text_original=t)
                                               for i, t in enumerate(texts)))
        self.rows = [{'source_id': c.comment_id, 'source_sha256': digest(c.text_original),
                      'eligibility': 'meaningful' if i < 5 else 'non_substantive',
                      'reason': 'Synthetic stance.' if i < 5 else 'Generic praise only.'}
                     for i, c in enumerate(self.snapshot.comments)]
        self.reference = self.freeze()
        self.perspectives = [{'id': 'P1', 'claim': {'text': 'Require safety reviews.'},
                              'upstream_agent_state': 'not_evaluated'}]
        self.assessments = [self.assignment(i) for i in range(4)]

    def freeze(self, scope=None):
        rows = self.rows if scope is None else [r for r in self.rows if r['source_id'] in scope]
        return m.freeze_reference(self.snapshot, rows, evaluator='synthetic-test-author',
                                  protocol='Labels authored before synthetic outputs; no human gold claim.',
                                  scope_ids=scope)

    def assignment(self, i, pid='P1', relation='supported'):
        source = self.snapshot.comments[i]
        p = next(p for p in self.perspectives if p['id'] == pid)
        return {'perspective_id': pid, 'source_id': source.comment_id,
                'source_sha256': digest(source.text_original), 'claim_sha256': digest(p['claim']),
                'relation': relation, 'evidence_ref': f'synthetic:{pid}:{i}'}

    def review(self):
        mapped = opinion_map.build(self.snapshot, self.perspectives, self.assessments)
        lookup = {p['id']: p for p in self.perspectives}
        sources = {c.comment_id: c for c in self.snapshot.comments}
        # Synthetic oracle for tests only, NOT a runtime-to-oracle adapter.
        return {'map_sha256': digest(mapped), 'evaluator': 'synthetic-test-author',
                'clusters': [{'perspective_id': p['id'], 'claim_sha256': digest(p['claim']),
                              'verdict': 'coherent', 'reason': 'Synthetic shared stance.'}
                             for p in self.perspectives],
                'supports': [{'perspective_id': r['perspective_id'], 'source_id': r['canonical_source_id'],
                              'claim_sha256': digest(lookup[r['perspective_id']]['claim']),
                              'source_sha256': digest(sources[r['canonical_source_id']].text_original),
                              'verdict': 'supported', 'reason': 'Synthetic source supports this stance.'}
                             for r in mapped['assessments'] if r['relation'] == 'supported']}

    def evaluate(self, review=None, reference=None, expected=None):
        ref = self.reference if reference is None else reference
        return m.evaluate(self.snapshot, ref, self.perspectives, self.assessments,
                          self.review() if review is None else review,
                          expected_reference_sha256=digest(ref) if expected is None else expected)

    def test_eighty_percent_uses_meaningful_not_raw_or_assigned_denominator(self):
        out = self.evaluate()
        self.assertEqual(out['canonical_population'], 6)
        self.assertEqual(out['meaningful_sources'], 5)
        self.assertEqual(out['correct_comment_utilization'], .8)
        self.assertEqual(out['unutilized_meaningful_ids'], ['s4'])
        self.assertEqual(out['excluded_source_ids'], ['s5'])
        self.assertTrue(out['corpus_clustering_target_met'])
        self.assertEqual(out['agent_approval'], 'not_evaluated')
        self.assertEqual(out['mvp_acceptance'], 'not_evaluated')

    def test_perfect_precision_with_low_utilization_fails_coverage(self):
        self.assessments = self.assessments[:3]
        out = self.evaluate()
        self.assertEqual(out['correct_comment_utilization'], .6)
        self.assertTrue(out['support_validity_passed'])
        self.assertFalse(out['corpus_clustering_target_met'])

    def test_all_unassigned_is_zero_not_success(self):
        self.assessments = []
        out = self.evaluate()
        self.assertEqual(out['correct_comment_utilization'], 0)
        self.assertFalse(out['support_validity_passed'])
        self.assertFalse(out['corpus_clustering_target_met'])

    def test_no_candidates_retains_meaningful_denominator(self):
        self.perspectives, self.assessments = [], []
        out = self.evaluate()
        self.assertEqual(out['meaningful_sources'], 5)
        self.assertEqual(out['correct_comment_utilization'], 0)

    def test_singleton_storage_does_not_count_as_clustering(self):
        self.perspectives = [{'id': f'P{i}', 'claim': {'text': f'Synthetic distinct position {i}.'},
                              'upstream_agent_state': 'rare'} for i in range(5)]
        self.assessments = [self.assignment(i, f'P{i}') for i in range(5)]
        out = self.evaluate()
        self.assertEqual(out['counted_support_relations'], 5)
        self.assertEqual(out['correct_comment_utilization'], 0)

    def test_reviewed_shared_pair_is_not_automatically_an_agent(self):
        self.assessments = self.assessments[:2]
        out = self.evaluate()
        self.assertEqual(out['correct_comment_utilization'], .4)
        self.assertFalse(out['per_cluster'][0]['agent_approved'])

    def test_unknown_eligibility_does_not_shrink_denominator_into_success(self):
        self.rows[4]['eligibility'] = 'uncertain'
        out = self.evaluate(reference=self.freeze())
        self.assertIsNone(out['correct_comment_utilization'])
        self.assertEqual(out['unresolved_eligibility_ids'], ['s4'])
        self.assertFalse(out['coverage_target_met'])

    def test_empty_meaningful_population_is_not_perfect_coverage(self):
        self.rows = [{**r, 'eligibility': 'non_substantive'} for r in self.rows]
        self.assessments = []
        out = self.evaluate(reference=self.freeze())
        self.assertIsNone(out['correct_comment_utilization'])
        self.assertFalse(out['corpus_clustering_target_met'])

    def test_sample_success_cannot_be_corpus_success(self):
        out = self.evaluate(reference=self.freeze(['s0', 's1', 's2', 's3']))
        self.assertEqual(out['correct_comment_utilization'], 1)
        self.assertTrue(out['coverage_target_met'])
        self.assertEqual(out['scope'], 'sample')
        self.assertFalse(out['corpus_clustering_target_met'])

    def test_missing_reference_row_is_rejected_not_silently_excluded(self):
        self.rows.pop()
        with self.assertRaises(ValueError):
            self.freeze()

    def test_missing_exclusion_reason_is_rejected(self):
        self.rows[-1]['reason'] = ' '
        with self.assertRaises(ValueError):
            self.freeze()

    def test_frozen_denominator_cannot_change_after_run(self):
        old_hash = digest(self.reference)
        self.rows[4]['eligibility'] = 'non_substantive'
        changed = self.freeze()
        with self.assertRaises(ValueError):
            self.evaluate(reference=changed, expected=old_hash)

    def test_incomplete_scope_cannot_claim_full_corpus(self):
        ref = self.freeze(['s0', 's1', 's2'])
        ref['scope'] = 'full_corpus'
        with self.assertRaises(ValueError):
            self.evaluate(reference=ref)

    def test_unknown_or_duplicate_reference_sources_rejected(self):
        for scope in (['s0', 'unknown'], ['s0', 's0']):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.freeze(scope)

    def test_duplicate_reference_judgments_rejected(self):
        self.rows.append(deepcopy(self.rows[0]))
        with self.assertRaises(ValueError):
            self.freeze()

    def test_reference_is_bound_to_full_snapshot_and_context(self):
        source = replace(self.snapshot.comments[0], parent_status='missing', parent_id='missing-parent')
        self.snapshot = replace(self.snapshot, comments=(source,) + self.snapshot.comments[1:])
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_changed_reference_source_text_rejected(self):
        self.rows[0]['source_sha256'] = digest('Different source.')
        with self.assertRaises(ValueError):
            self.freeze()

    def test_missing_review_is_not_model_support_truth(self):
        review = self.review()
        review['supports'] = []
        out = self.evaluate(review)
        self.assertEqual(out['support_counts']['unreviewed'], 4)
        self.assertEqual(out['correct_comment_utilization'], 0)
        self.assertFalse(out['support_validity_passed'])

    def test_uncertain_review_is_not_correct(self):
        review = self.review()
        review['supports'][0]['verdict'] = 'uncertain'
        out = self.evaluate(review)
        self.assertEqual(out['correct_comment_utilization'], .6)
        self.assertEqual(out['support_counts']['uncertain'], 1)
        self.assertFalse(out['support_validity_passed'])

    def test_wrong_extra_edge_is_not_hidden_by_correct_coverage(self):
        self.perspectives.append({'id': 'P2', 'claim': {'text': 'Oppose mandatory safety reviews.'},
                                  'upstream_agent_state': 'not_evaluated'})
        self.assessments.append(self.assignment(0, 'P2'))
        review = self.review()
        next(r for r in review['supports'] if r['perspective_id'] == 'P2')['verdict'] = 'not_supported'
        out = self.evaluate(review)
        self.assertEqual(out['correct_comment_utilization'], .8)
        self.assertTrue(out['coverage_target_met'])
        self.assertEqual(out['support_counts']['not_supported'], 1)
        self.assertFalse(out['corpus_clustering_target_met'])

    def test_invalid_uncertain_or_unreviewed_cluster_gives_no_coverage(self):
        for verdict in ('invalid', 'uncertain', None):
            review = self.review()
            if verdict is None:
                review['clusters'] = []
            else:
                review['clusters'][0]['verdict'] = verdict
            out = self.evaluate(review)
            with self.subTest(verdict=verdict):
                self.assertEqual(out['correct_comment_utilization'], 0)
                self.assertFalse(out['corpus_clustering_target_met'])

    def test_conflict_between_exclusion_and_support_requires_reconciliation(self):
        self.assessments.append(self.assignment(5))
        out = self.evaluate()
        self.assertEqual(out['correct_comment_utilization'], .8)
        self.assertEqual(out['reference_conflict_ids'], ['s5'])
        self.assertFalse(out['support_validity_passed'])

    def test_multilabel_comment_counts_once(self):
        self.perspectives.append({'id': 'P2', 'claim': {'text': 'A separate synthetic stance.'},
                                  'upstream_agent_state': 'not_evaluated'})
        self.assessments.extend(self.assignment(i, 'P2') for i in range(4))
        out = self.evaluate()
        self.assertEqual(out['counted_support_relations'], 8)
        self.assertEqual(out['correct_comment_utilization'], .8)

    def test_repeated_and_alias_assignments_do_not_inflate_counts(self):
        # Canonicalization chooses the lexicographically smallest ID.
        alias = replace(self.snapshot.comments[0], comment_id='z-alias-s0')
        self.snapshot = replace(self.snapshot, comments=self.snapshot.comments + (alias,))
        self.reference = self.freeze()
        self.assessments += [self.assignment(0), self.assignment(6)]
        out = self.evaluate()
        self.assertEqual(out['canonical_population'], 6)
        self.assertEqual(out['counted_support_relations'], 4)
        self.assertEqual(out['correct_comment_utilization'], .8)

    def test_alias_cannot_be_used_as_an_extra_denominator_entry(self):
        alias = replace(self.snapshot.comments[0], comment_id='z-alias-s0')
        self.snapshot = replace(self.snapshot, comments=self.snapshot.comments + (alias,))
        self.rows.append({**self.rows[0], 'source_id': alias.comment_id})
        with self.assertRaises(ValueError):
            self.freeze()

    def test_new_canonical_id_requires_a_new_source_bound_reference(self):
        alias = replace(self.snapshot.comments[0], comment_id='a-new-canonical')
        self.snapshot = replace(self.snapshot, comments=self.snapshot.comments + (alias,))
        with self.assertRaises(ValueError):
            self.freeze()

    def test_conditional_uncertain_and_unassessed_links_not_support(self):
        for relation in ('conditional', 'uncertain', 'unassessed', 'not_supported'):
            self.assessments = [self.assignment(i, relation=relation) for i in range(4)]
            out = self.evaluate()
            with self.subTest(relation=relation):
                self.assertEqual(out['counted_support_relations'], 0)
                self.assertEqual(out['correct_comment_utilization'], 0)

    def test_review_cannot_be_reused_after_output_change(self):
        review = self.review()
        self.assessments.pop()
        with self.assertRaises(ValueError):
            self.evaluate(review)

    def test_reviewed_claim_and_source_hashes_required(self):
        for section, key in (('supports', 'source_sha256'), ('supports', 'claim_sha256'),
                             ('clusters', 'claim_sha256')):
            review = self.review()
            review[section][0][key] = 'stale'
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                self.evaluate(review)

    def test_unknown_support_and_duplicate_reviews_rejected(self):
        review = self.review()
        review['supports'][0]['source_id'] = 'unknown'
        with self.assertRaises(ValueError):
            self.evaluate(review)
        for key in ('supports', 'clusters'):
            review = self.review()
            review[key].append(deepcopy(review[key][0]))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.evaluate(review)

    def test_inputs_remain_unchanged(self):
        review = self.review()
        before = deepcopy((self.reference, self.perspectives, self.assessments, review))
        self.evaluate(review)
        self.assertEqual(before, (self.reference, self.perspectives, self.assessments, review))

    def test_expired_snapshot_cannot_be_evaluated(self):
        self.snapshot = replace(self.snapshot, usage=replace(self.snapshot.usage,
                                                             expires_at='2000-01-01T00:00:00Z'))
        with self.assertRaises(ValueError):
            self.freeze()
