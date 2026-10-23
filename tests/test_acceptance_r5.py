"""Accounting boundary tests, not semantic model quality evidence."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest import TestCase

from commentscope.factory import acceptance, comment_utilization as utilization
from commentscope.factory.automatic_contract import digest
import test_comment_utilization as legacy_tests


def profile():
    return json.loads(Path('tests/fixtures/factory-acceptance-r5.json').read_text())


class AcceptanceR5Tests(TestCase):
    def setUp(self):
        self.fixture = legacy_tests.CommentUtilizationTests()
        self.fixture.setUp()
        f = self.fixture
        f.snapshot = replace(f.snapshot, comments=tuple(
            replace(f.snapshot.comments[0], comment_id=f's{i:04}', text_original=f'Original contribution {i}.')
            for i in range(999)))
        f.rows = [{'source_id': c.comment_id, 'source_sha256': digest(c.text_original),
                   'eligibility': 'meaningful' if i < 755 else 'non_substantive',
                   'reason': 'Synthetic pre-output eligibility.'}
                  for i, c in enumerate(f.snapshot.comments)]
        f.reference = f.freeze()
        f.assessments = [f.assignment(i) for i in range(453)]

    def evaluate(self, review=None, reference=None):
        f = self.fixture
        ref = f.reference if reference is None else reference
        return utilization.evaluate(f.snapshot, ref, f.perspectives, f.assessments,
            f.review() if review is None else review, expected_reference_sha256=digest(ref),
            acceptance_profile=profile(), expected_acceptance_sha256=acceptance.R5_DIGEST)

    def test_exact_452_453_boundary_and_unchanged_r4_reference(self):
        f = self.fixture; original = deepcopy(f.reference)
        passing = self.evaluate()
        self.assertTrue(passing['corpus_clustering_target_met'])
        self.assertEqual(passing['goal_revision'], acceptance.R5)
        self.assertEqual(passing['reference_goal_revision'], acceptance.R4)
        self.assertEqual(f.reference, original)
        self.assertFalse(f.evaluate()['coverage_target_met'])
        f.assessments.pop()
        self.assertFalse(self.evaluate()['coverage_target_met'])

    def test_wrong_or_unknown_extra_support_cannot_hide_behind_453(self):
        f = self.fixture
        f.assessments.append(f.assignment(453))
        for verdict in ('not_supported', 'uncertain', None):
            review = f.review()
            if verdict is None: review['supports'].pop()
            else: review['supports'][-1]['verdict'] = verdict
            with self.subTest(verdict=verdict):
                result = self.evaluate(review)
                self.assertTrue(result['coverage_target_met'])
                self.assertFalse(result['corpus_clustering_target_met'])

    def test_multilabel_and_duplicates_never_turn_452_into_453(self):
        f = self.fixture; f.assessments.pop()
        f.perspectives.append({'id': 'P2', 'claim': {'text': 'Second stance.'}, 'upstream_agent_state': 'not_evaluated'})
        f.assessments += [f.assignment(0), f.assignment(0, 'P2'), f.assignment(1, 'P2')]
        result = self.evaluate()
        self.assertEqual(len(result['utilized_source_ids']), 452)
        self.assertFalse(result['coverage_target_met'])

    def test_singletons_do_not_complete_the_shared_cluster_threshold(self):
        f = self.fixture; f.assessments.pop()
        f.perspectives.append({'id': 'P2', 'claim': {'text': 'Unique stance.'}, 'upstream_agent_state': 'rare'})
        f.assessments.append(f.assignment(452, 'P2'))
        self.assertFalse(self.evaluate()['coverage_target_met'])

    def test_denominator_cannot_change_even_with_newly_supplied_hash(self):
        f = self.fixture
        f.rows[754]['eligibility'] = 'non_substantive'
        with self.assertRaisesRegex(ValueError, 'denominator'):
            self.evaluate(reference=f.freeze())

    def test_partial_or_unresolved_reference_cannot_be_r5_corpus(self):
        f = self.fixture
        with self.assertRaises(ValueError):
            self.evaluate(reference=f.freeze([c.comment_id for c in f.snapshot.comments[:754]]))
        f.rows[754]['eligibility'] = 'uncertain'
        with self.assertRaises(ValueError): self.evaluate(reference=f.freeze())

    def test_changed_contract_or_missing_pin_is_rejected(self):
        p = profile()
        acceptance.validate(p, acceptance.R5_DIGEST)
        with self.assertRaises(ValueError): acceptance.validate(p, None)
        p['correct_utilization']['minimum_count'] = 452
        with self.assertRaises(ValueError): acceptance.validate(p, digest(p))
        with self.assertRaises(ValueError): acceptance.from_plan({'goal_revision': acceptance.R5})

    def test_intermediate_integer_boundaries_and_fixed_denominators(self):
        p = profile(); n, d = acceptance.ratio(p)
        for gate, count, meaningful, minimum in [('G2', 24, 19, 12), ('G3', 96, 74, 45)]:
            acceptance.check_scope(p, gate, count, meaningful)
            self.assertLess((minimum - 1)*d, meaningful*n)
            self.assertGreaterEqual(minimum*d, meaningful*n)
            with self.assertRaises(ValueError): acceptance.check_scope(p, gate, count, meaningful - 1)
