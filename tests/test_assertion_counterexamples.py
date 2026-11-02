"""A primary equivalence vote cannot bypass an independent missing-assertion veto."""
from copy import deepcopy
import unittest

from commentscope.factory import assertion_counterexamples as counter
from commentscope.factory import candidate_consolidation as cc, minimal_claims as mc
from commentscope.factory import proposition_requirements as pr
from test_minimal_factory import extraction, membership


def observations(left='possible', right='impossible'):
    return {'a_scenario': 'A consistent position without B.' if left == 'possible' else '',
            'a_without_b': left, 'b_scenario': 'B consistent without A.' if right == 'possible' else '',
            'b_without_a': right}


class AssertionCounterexampleTests(unittest.TestCase):
    def setUp(self):
        self.a = 'I oppose compulsory attendance.'
        self.b = 'Attendance should be voluntary.'

    def bind(self, a_without_b='possible', b_without_a='impossible', **kwargs):
        return counter.bind(self.a, self.b, {'output': observations(a_without_b, b_without_a), **kwargs})

    def test_request_contains_complete_assertions_without_primary_decision_or_source_reasons(self):
        req = counter.request(self.a, self.b)
        self.assertEqual(req['data'], {'A': self.a, 'B': self.b})
        self.assertIn('permission', req['system'])
        self.assertIn('binary', req['system'])
        self.assertLessEqual(req['max_tokens'], 512)

    def test_either_direction_possible_or_unclear_vetoes_even_if_the_other_impossible(self):
        for left, right in [('possible', 'impossible'), ('impossible', 'possible'),
                            ('unclear', 'impossible'), ('impossible', 'unclear')]:
            self.assertFalse(self.bind(left, right)['passed'])
        self.assertTrue(self.bind('impossible', 'impossible')['passed'])

    def test_missing_direction_unknown_values_and_failed_responses_cannot_be_repaired(self):
        for output in ({'a_without_b': 'impossible'},
                       {'a_without_b': True, 'b_without_a': 'impossible'},
                       {'a_without_b': 'no', 'b_without_a': 'impossible'},
                       {'a_without_b': 'impossible', 'b_without_a': 'impossible', 'reason': 'same'}):
            with self.assertRaises(ValueError): counter.bind(self.a, self.b, {'output': output})
        with self.assertRaises(ValueError): self.bind(errors=['invalid_response'])

    def test_request_source_response_and_pass_flag_replay_without_semantic_repair(self):
        bound = self.bind()
        self.assertEqual(counter.validate(bound), bound)
        for change in (lambda x: x.update(a='Compulsory attendance is acceptable.'),
                       lambda x: x.update(request_sha256='0'*64),
                       lambda x: x['response'].update(a_without_b='impossible'),
                       lambda x: x.update(passed=True)):
            other = deepcopy(bound); change(other)
            with self.assertRaises(ValueError): counter.validate(other)

    def test_nonempty_scenario_vetoes_a_conflicting_positive_label_without_repair(self):
        value = observations('impossible', 'impossible'); value['a_scenario'] = 'A is accepted for another reason.'
        bound = counter.bind(self.a, self.b, {'output': value})
        self.assertFalse(bound['passed'])
        self.assertEqual(bound['response'], value)
        value['a_scenario'] = 'x'*601
        with self.assertRaises(ValueError): counter.bind(self.a, self.b, {'output': value})

    def test_legacy_paid_observations_replay_but_cannot_approve_current_merges(self):
        legacy = counter.bind(self.a, self.b, {'output': {'a_without_b': 'impossible',
            'b_without_a': 'impossible'}}, protocol=counter.LEGACY)
        self.assertEqual(counter.validate(legacy), legacy)
        inputs = self.inputs(); check = self.check(inputs)
        check['check'] = counter.bind(check['check']['a'], check['check']['b'],
            {'output': legacy['response']}, protocol=counter.LEGACY)
        with self.assertRaises(ValueError): self.merge(inputs, [check])

    def inputs(self):
        sources = [{'id': 'a', 'text': self.a, 'parent': None},
                   {'id': 'b', 'text': self.b, 'parent': None}]
        candidates = mc.candidates(extraction(sources, {s['id']: [s['text']] for s in sources}))
        pairs = [{'source_id': sid, 'candidate_id': c['id']} for c in candidates for sid in c['nominees']]
        members = [membership(sources, candidates, pairs)]
        pair = dict(zip(('a', 'b'), sorted(c['id'] for c in candidates)))
        index = {c['id']: c for c in candidates}; qualifications = []
        for left, right in ((pair['a'], pair['b']), (pair['b'], pair['a'])):
            shape = pr.bind_shape(index[right]['text'], {'output': {'status': 'complete', 'qualifications': []}})
            assessment = pr.assessment({'id': left, 'text': index[left]['text'], 'parent': None}, shape, [])
            qualifications.append({'from_candidate_id': left, 'to_candidate_id': right, 'assessment': assessment})
        return sources, candidates, members, [pair], index, qualifications

    def merge(self, inputs, checks=(), relation='equivalent', protocol=None):
        sources, candidates, members, pairs, _, qualifications = inputs
        return cc.bind(sources, candidates, members, pairs,
            {'output': {'decisions': [{'pair_id': 'P1', 'relation': relation}]}}, qualifications,
            protocol=cc.BILATERAL if protocol is None else protocol, assertion_checks=checks)

    def check(self, inputs, a_without_b='possible', b_without_a='impossible'):
        pair, index = inputs[3][0], inputs[4]
        return {**pair, 'check': counter.bind(index[pair['a']]['text'], index[pair['b']]['text'],
            {'output': observations(a_without_b, b_without_a)})}

    def test_missing_or_negative_independent_proof_prevents_primary_equivalent_merge(self):
        inputs = self.inputs()
        for checks in ([], [self.check(inputs)]):
            record = self.merge(inputs, checks)
            self.assertEqual(record['relations'][0]['model_relation'], 'equivalent')
            self.assertEqual(record['relations'][0]['relation'], 'uncertain')
            merged = cc.consolidate(*inputs[:3], [record])
            self.assertEqual(len(merged['candidates']), 2)
            self.assertEqual(merged['memberships'], [])

    def test_positive_independent_proof_is_only_an_additional_veto_not_automatic_approval(self):
        inputs = self.inputs(); checks = [self.check(inputs, 'impossible', 'impossible')]
        record = self.merge(inputs, checks)
        self.assertEqual(record['relations'][0]['relation'], 'equivalent')
        different = self.merge(inputs, checks, relation='different')
        self.assertEqual(different['relations'][0]['relation'], 'different')
        missing_qualifications = cc.bind(*inputs[:4],
            {'output': {'decisions': [{'pair_id': 'P1', 'relation': 'equivalent'}]}},
            protocol=cc.BILATERAL, assertion_checks=checks)
        self.assertEqual(missing_qualifications['relations'][0]['relation'], 'uncertain')

    def test_wrong_pair_text_duplicate_or_rewritten_proof_is_rejected_on_binding_and_replay(self):
        inputs = self.inputs(); check = self.check(inputs)
        bad_text = deepcopy(check)
        bad_text['check'] = counter.bind('An unrelated statement.', self.b,
            {'output': observations('impossible', 'impossible')})
        bad_id = {**check, 'a': 'foreign'}
        for checks in ([bad_text], [bad_id], [check, check]):
            with self.assertRaises(ValueError): self.merge(inputs, checks)
        bound = self.merge(inputs, [check]); changed = deepcopy(bound)
        changed['assertion_checks'][0]['check']['passed'] = True
        with self.assertRaises(ValueError): cc.consolidate(*inputs[:3], [changed])
        with self.assertRaises(ValueError): self.merge(inputs, [check], protocol=cc.ASSERTION_ONLY)


if __name__ == '__main__': unittest.main()
