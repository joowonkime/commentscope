"""An empty proposal is unresolved, never coverage or an automatic retry."""
from copy import deepcopy
import unittest

from commentscope.factory import compact_claims as compact, minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from test_compact_unified_selections import row


PROTOCOL = 'compact-source-claims-20261103-v7'


class ProposalOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'own', 'text': 'Protect privacy. Keep public access.', 'parent': None}

    def bind(self, rows, *, more=False, source=None, previous=None):
        return compact.bind(source or self.source, {'output': {'c': rows, 'm': more}},
                            protocol=PROTOCOL, previous=previous)

    def test_schema_has_one_bounded_list_and_boolean_continuation_without_status(self):
        req = compact.request(self.source, protocol=PROTOCOL)
        self.assertEqual(set(req['schema']['properties']), {'c', 'm'})
        self.assertEqual(req['schema']['properties']['m'], {'type': 'boolean'})
        self.assertEqual(req['schema']['properties']['c']['maxItems'], 16)
        self.assertEqual(req['schema']['properties']['c']['minItems'], 0)

    def test_empty_primary_is_unresolved_for_either_continuation_hint(self):
        for hint in (False, True):
            with self.subTest(hint=hint):
                bound = self.bind([], more=hint)
                self.assertEqual(bound['status'], 'unresolved')
                self.assertEqual(bound['claims'], [])
                self.assertEqual(bound['response'], {'c': [], 'm': hint})
                self.assertFalse(bound['semantic_approval'])
                self.assertEqual(mc.candidates([bound]), [])
                self.assertEqual(compact.validate(bound), bound)

    def test_empty_primary_does_not_dispatch_another_model_request(self):
        calls = []
        def work(stage, items, request, bind, size):
            results = []
            for item in items:
                calls.append((stage, request([item])))
                results.append(bind([item], {'output': {'c': [], 'm': True}}))
            return results
        records = compact.discover([self.source], work, protocol=PROTOCOL)
        self.assertEqual(len(calls), 1)
        self.assertEqual(records[0]['status'], 'unresolved')

    def test_literal_and_rewrite_keep_the_existing_canonical_checks(self):
        literal = self.bind([row()])
        rewrite = self.bind([row(text='Protect privacy.')])
        old = compact.bind(self.source, {'output': {'s': 'covered', 'c': [row()]}}, protocol=compact.UNIFIED)
        self.assertEqual(literal['canonical_record'], old['canonical_record'])
        self.assertEqual(literal['canonical_record'], rewrite['canonical_record'])
        self.assertNotEqual(literal['response'], old['response'])
        self.assertFalse(literal['semantic_approval'])

    def test_supplement_can_finish_without_erasing_previous_claims(self):
        first = self.bind([row()], more=True)
        self.assertEqual(first['status'], 'partial')
        finished = self.bind([], previous=first)
        self.assertEqual(finished['status'], 'covered')
        self.assertEqual(finished['claims'], first['claims'])
        self.assertEqual(finished['additional_passes'], 1)
        self.assertEqual(compact.validate(finished), finished)
        with self.assertRaises(ValueError): self.bind([], previous=finished)

    def test_empty_supplement_with_more_keeps_partial_and_one_pass_limit(self):
        first = self.bind([row()], more=True)
        second = self.bind([], more=True, previous=first)
        self.assertEqual(second['status'], 'partial')
        self.assertEqual(second['claims'], first['claims'])
        with self.assertRaises(ValueError): self.bind([row(evidence=('S001',))], previous=second)

    def test_sixteen_limit_and_whole_conditions_remain_binding(self):
        source = {**self.source, 'text': ' '.join(f'Adopt policy {i} only if funded.' for i in range(17))}
        req = compact.request(source, protocol=PROTOCOL)
        rows = [row(evidence=x['evidence_segment_ids'], conditions=x['essential_condition_segment_ids'],
                    locked=x['id']) for x in req['data']['LOCKED_CONDITIONALS']]
        with self.assertRaises(ValueError): self.bind(rows, source=source)
        first = self.bind(rows[:16], source=source, more=True)
        second = self.bind(rows[16:], source=source, previous=first)
        self.assertEqual(len(second['claims']), 17)
        self.assertEqual(compact.validate(second), second)
        with self.assertRaises(ValueError): self.bind([{**rows[0], 'k': []}], source=source)
        with self.assertRaises(ValueError): self.bind([row(text='Adopt policy 0.')], source=source)

    def test_bad_types_duplicates_and_mutations_are_rejected(self):
        for hint in (None, 0, 1, 'false'):
            with self.subTest(hint=hint), self.assertRaises(ValueError): self.bind([], more=hint)
        with self.assertRaises(ValueError): self.bind([row(), row(text='Protect privacy.')])
        with self.assertRaises(ValueError): self.bind([row(evidence=('parent',))])
        with self.assertRaises(ValueError):
            compact.bind(self.source, {'output': {'c': [], 'm': False, 's': 'covered'}}, protocol=PROTOCOL)
        with self.assertRaises(ValueError):
            compact.bind(self.source, {'output': None, 'errors': ['invalid_json']}, protocol=PROTOCOL)
        bound = self.bind([row()]); changed = deepcopy(bound); changed['response']['m'] = True
        with self.assertRaises(ValueError): compact.validate(changed)

    def test_v6_empty_covered_still_fails_and_request_is_byte_exact(self):
        with self.assertRaisesRegex(ValueError, 'Empty covered extraction'):
            compact.bind(self.source, {'output': {'s': 'covered', 'c': []}}, protocol=compact.UNIFIED)
        source = {'id': 'own', 'text': 'Adopt P only if funded. Protect privacy.', 'parent': None}
        self.assertEqual(digest(compact.request(source, protocol=compact.UNIFIED)),
                         'a62e7e45b9e121c33a3b670455027a8cbf355bac4c2d32fdb19568d9296526c7')


if __name__ == '__main__': unittest.main()
