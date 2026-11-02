"""One bounded proposition list; failures are rejected rather than deduplicated."""
from copy import deepcopy
import unittest

from commentscope.factory import compact_claims as compact, minimal_claims as mc
from commentscope.factory.automatic_contract import digest


PROTOCOL = 'compact-source-claims-20261103-v6'


def row(*, evidence=('S000',), conditions=(), text='', locked='', author='asserted'):
    return {'e': list(evidence), 'k': list(conditions), 't': text, 'l': locked, 'a': author}


class UnifiedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'own', 'text': 'Protect privacy. I wouldn’t stop working.',
                       'parent': {'id': 'parent', 'text': 'A different author reason.'}}

    def bind(self, rows, *, source=None, status='covered', previous=None):
        return compact.bind(source or self.source, {'output': {'s': status, 'c': rows}},
                            protocol=PROTOCOL, previous=previous)

    def test_all_representations_share_one_schema_bounded_list(self):
        req = compact.request(self.source, protocol=PROTOCOL)
        self.assertEqual(set(req['schema']['properties']), {'s', 'c'})
        claims = req['schema']['properties']['c']
        self.assertEqual(claims['maxItems'], 16)
        props = claims['items']['properties']
        self.assertEqual(set(props), {'e', 'k', 't', 'l', 'a'})
        self.assertEqual(props['e']['minItems'], 1)
        self.assertNotIn('maxItems', props['e'])
        self.assertNotIn('maxItems', props['k'])
        self.assertEqual(props['l']['enum'], [''])

    def test_literal_and_rewrite_preserve_canonical_text_and_actual_response(self):
        literal = self.bind([row(evidence=('S001',))])
        rewrite = self.bind([row(evidence=('S001',), text='I wouldn’t stop working.')])
        self.assertEqual(literal['canonical_record'], rewrite['canonical_record'])
        self.assertNotEqual(literal['response'], rewrite['response'])
        self.assertEqual(literal['claims'][0]['text'], 'I wouldn’t stop working.')
        self.assertEqual(compact.validate(literal), literal)
        self.assertFalse(literal['semantic_approval'])

    def test_seventeen_rows_fail_and_sixteen_distinct_rows_are_valid(self):
        source = {**self.source, 'text': ' '.join(f'Claim {i}.' for i in range(17))}
        rows = [row(evidence=(f'S{i:03}',)) for i in range(17)]
        self.assertEqual(len(self.bind(rows[:16], source=source, status='partial')['claims']), 16)
        with self.assertRaises(ValueError): self.bind(rows, source=source)

    def test_duplicate_literal_and_rewrite_are_never_silently_removed(self):
        with self.assertRaisesRegex(ValueError, 'Repeated proposition'):
            self.bind([row(), row(text='Protect privacy.')])
        with self.assertRaises(ValueError): self.bind([row(), row()])

    def test_whole_locked_condition_uses_the_same_list_and_capacity(self):
        source = {**self.source, 'text': 'Adopt P only if funded. Protect privacy.'}
        req = compact.request(source, protocol=PROTOCOL)
        self.assertNotIn('l', req['schema']['properties'])
        self.assertEqual(req['schema']['properties']['c']['items']['properties']['l']['enum'], ['', 'C1'])
        locked = row(locked='C1', conditions=('S000',))
        bound = self.bind([locked, row(evidence=('S001',))], source=source)
        self.assertEqual(bound['claims'][0]['text'], 'Adopt P only if funded.')
        self.assertEqual(bound['claims'][0]['essential_conditions'][0]['id'], 'S000')
        for change in ({'k': []}, {'e': ['S001']}, {'t': 'Adopt P.'}, {'l': 'C999'}):
            invalid = {**locked, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.bind([invalid], source=source)
        with self.assertRaises(ValueError):
            self.bind([row(text='Adopt P.')], source=source)

    def test_literals_cannot_invent_join_skip_or_omit_a_selected_condition(self):
        source = {**self.source, 'text': 'First claim. Essential condition. Last claim.'}
        for invalid in (row(evidence=()), row(evidence=('parent',)),
                        row(evidence=('S000', 'S000')), row(evidence=('S002', 'S000')),
                        row(evidence=('S000', 'S002')), row(conditions=('S001',))):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.bind([invalid], source=source)

    def test_many_locked_conditions_share_the_budget_and_one_supplement(self):
        source = {**self.source, 'text': ' '.join(f'Adopt policy {i} only if funded.' for i in range(17))}
        req = compact.request(source, protocol=PROTOCOL)
        locked = req['data']['LOCKED_CONDITIONALS']
        self.assertEqual(len(locked), 17)
        rows = [row(evidence=x['evidence_segment_ids'], conditions=x['essential_condition_segment_ids'],
                    locked=x['id']) for x in locked]
        with self.assertRaises(ValueError): self.bind(rows, source=source)
        first = self.bind(rows[:16], source=source, status='partial')
        supplement = compact.request(source, protocol=PROTOCOL, previous=first)
        self.assertEqual(supplement['schema']['properties']['c']['items']['properties']['l']['enum'], ['', 'C17'])
        second = self.bind(rows[16:], source=source, previous=first)
        self.assertEqual(len(second['claims']), 17)
        self.assertEqual(compact.validate(second), second)

    def test_reported_and_uncertain_claims_are_not_votes_and_supplements_do_not_repeat(self):
        for author in ('reported', 'uncertain'):
            self.assertEqual(mc.candidates([self.bind([row(author=author)])]), [])
        first = self.bind([row()], status='partial')
        second = self.bind([row(evidence=('S001',))], previous=first)
        self.assertEqual(len(second['claims']), 2)
        with self.assertRaises(ValueError): self.bind([row()], previous=first)
        with self.assertRaises(ValueError): compact.request(self.source, protocol=PROTOCOL, previous=second)

    def test_unknown_fields_failed_results_and_mutated_records_are_rejected(self):
        with self.assertRaises(ValueError): self.bind([{**row(), 'v': True}])
        with self.assertRaises(ValueError): self.bind([row(text='   ')])
        with self.assertRaises(ValueError):
            compact.bind(self.source, {'output': {'s': 'covered', 'c': [row()], 'v': []}}, protocol=PROTOCOL)
        with self.assertRaises(ValueError):
            compact.bind(self.source, {'output': None, 'errors': ['invalid_response']}, protocol=PROTOCOL)
        record = self.bind([row()]); changed = deepcopy(record); changed['response']['c'][0]['t'] = 'Reject privacy.'
        with self.assertRaises(ValueError): compact.validate(changed)

    def test_v5_request_stays_byte_exact(self):
        source = {'id': 'own', 'text': 'Adopt P only if funded. Protect privacy.', 'parent': None}
        self.assertEqual(digest(compact.request(source, protocol=compact.SEGMENTED)),
                         '8a829ba92dff937585702f71b3a7d3d25b69d8981bed652add3ac7931ce70ca7')


if __name__ == '__main__': unittest.main()
