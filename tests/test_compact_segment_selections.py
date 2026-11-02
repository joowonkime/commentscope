"""Bound segment selections preserve source text without repairing model replies."""
from copy import deepcopy
import unittest

from commentscope.factory import compact_claims as compact, minimal_claims as mc


class SegmentSelectionTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'own', 'text': 'A yearly grant. I wouldn’t stop working.',
                       'parent': {'id': 'parent', 'text': 'Everyone should quit work.'}}

    def request(self, source=None, **kwargs):
        return compact.request(source or self.source, protocol=compact.SEGMENTED, **kwargs)

    def result(self, *, evidence=None, conditions=None, author='asserted', claims=(), status='covered'):
        return {'output': {'s': status, 'c': list(claims), 'v': [{
            'e': ['S001'] if evidence is None else evidence,
            'k': [] if conditions is None else conditions, 'a': author}]}}

    def bind(self, result, source=None, **kwargs):
        return compact.bind(source or self.source, result, protocol=compact.SEGMENTED, **kwargs)

    def test_closed_id_arrays_require_own_evidence_and_allow_no_condition(self):
        req = self.request()
        for key in ('c', 'v'):
            props = req['schema']['properties'][key]['items']['properties']
            self.assertEqual(props['e']['type'], 'array')
            self.assertEqual(props['e']['minItems'], 1)
            self.assertEqual(props['e']['items']['enum'], ['S000', 'S001'])
            self.assertEqual(props['k']['minItems'], 0)
            self.assertNotIn('pattern', str(props))
        self.assertNotIn('t', req['schema']['properties']['v']['items']['properties'])

    def test_literal_copies_curly_apostrophe_quotes_and_newlines_from_own_source(self):
        source = {**self.source, 'text': 'I wouldn’t stop working.\nI said "keep working".'}
        bound = self.bind(self.result(evidence=['S000', 'S001']), source)
        # Canonical whitespace normalization remains the existing contract.
        self.assertEqual(bound['claims'][0]['text'], mc.normalize(source['text']))
        self.assertEqual([e['text'] for e in bound['claims'][0]['evidence']],
                         [s['text'] for s in mc.packet(source)['ORIGINAL_SEGMENTS']])
        self.assertFalse(bound['semantic_approval'])
        self.assertEqual(mc.validate(bound), bound)

    def test_literal_and_rewrite_have_the_same_canonical_claim_without_faking_wire_provenance(self):
        literal = self.bind(self.result())
        rewritten = self.bind({'output': {'s': 'covered', 'v': [], 'c': [{
            'e': ['S001'], 'k': [], 'a': 'asserted', 't': 'I wouldn’t stop working.'}]}})
        self.assertEqual(literal['canonical_record'], rewritten['canonical_record'])
        self.assertNotEqual(literal['request_sha256'], literal['canonical_record']['request_sha256'])
        self.assertNotEqual(literal['output_sha256'], rewritten['output_sha256'])

    def test_empty_duplicate_foreign_and_wrongly_typed_addresses_are_rejected_without_repair(self):
        for evidence in ([], ['S001', 'S001'], ['parent'], ['S999'], [1], [True],
                         '01', {'S001': True}, ['S001', 'S000']):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.bind(self.result(evidence=evidence))
        for conditions in (['S999'], ['S000', 'S000'], [False], '00'):
            with self.subTest(conditions=conditions), self.assertRaises(ValueError):
                self.bind(self.result(conditions=conditions))

    def test_noncontiguous_literal_cannot_concatenate_unselected_words(self):
        source = {**self.source, 'text': 'First claim. Negation or condition. Last claim.'}
        with self.assertRaises(ValueError):
            self.bind(self.result(evidence=['S000', 'S002']), source)
        with self.assertRaises(ValueError):
            self.bind(self.result(evidence=['S000'], conditions=['S001']), source)

    def test_previous_wire_requests_remain_byte_exact(self):
        from commentscope.factory.automatic_contract import digest
        source = {'id': 'own', 'text': 'Adopt P only if funded. Protect privacy.', 'parent': None}
        expected = {
            compact.VERSION: '516220cb86b8b41b360e34836fca0d9ab455c3af1e1afe7da2912ad3672b3757',
            compact.MASKED: 'bb262775120b6918509535218823bccce5bc46f3e0d015a2ba52b440bad670fa',
            compact.INDEXED: '71cf80ba7c53216ca08d255d9e5d200f31310d0251ba3202a492f0228f2d33ff',
            compact.SEGMENTED_BOUNDED: 'a41e204007752c29d1eecf2dec20f16d07728dc05d33fa0279ba16422bb92d5d'}
        for protocol, request_hash in expected.items():
            self.assertEqual(digest(compact.request(source, protocol=protocol)), request_hash)

    def test_rewritten_claims_still_bind_actual_own_ids(self):
        for key in ('e', 'k'):
            for bad in ('00', ['parent'], ['S000', 'S000'], [False]):
                row = {'e': ['S001'], 'k': [], 'a': 'asserted', 't': 'The author would keep working.'}
                row[key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    self.bind({'output': {'s': 'covered', 'v': [], 'c': [row]}})

    def test_literal_authorship_status_and_capacity_use_unchanged_canonical_checks(self):
        for author in ('reported', 'uncertain'):
            self.assertEqual(mc.candidates([self.bind(self.result(author=author))]), [])
        for result in (self.result(author='unknown'), self.result(status='non_substantive'),
                       self.result(status='unresolved'), self.result(status='unknown')):
            with self.subTest(result=result), self.assertRaises(ValueError): self.bind(result)
        with self.assertRaises(ValueError):
            self.bind(self.result(evidence=['S000']), {**self.source, 'text': 'x'*601})
        too_many = self.result(); too_many['output']['v'] *= 17
        with self.assertRaises(ValueError): self.bind(too_many)
        duplicate = self.result(); duplicate['output']['v'] *= 2
        with self.assertRaises(ValueError): self.bind(duplicate)
        source = {**self.source, 'text': ' '.join(f'Claim {i}.' for i in range(25))}
        ids = [s['id'] for s in mc.packet(source)['ORIGINAL_SEGMENTS']]
        self.assertEqual(len(ids), 25)
        with self.assertRaises(ValueError): self.bind(self.result(evidence=ids), source)

    def test_literal_and_free_paths_cannot_bypass_a_locked_whole_condition(self):
        source = {**self.source, 'text': 'Adopt P only if funded.'}
        req = self.request(source)
        self.assertEqual(req['data']['LOCKED_CONDITIONALS'][0]['text'], source['text'])
        valid = {'output': {'s': 'covered', 'c': [], 'v': [], 'l': {'C1': 'asserted'}}}
        self.assertEqual(self.bind(valid, source)['claims'][0]['text'], source['text'])
        for key, row in (('v', {'e': ['S000'], 'k': [], 'a': 'asserted'}),
                         ('c', {'e': ['S000'], 'k': [], 'a': 'asserted', 't': 'Adopt P.'})):
            invalid = deepcopy(valid); invalid['output']['l']['C1'] = 'omitted'
            invalid['output'][key] = [row]
            with self.subTest(key=key), self.assertRaises(ValueError): self.bind(invalid, source)

    def test_unknown_fields_failed_json_and_mutated_wire_never_get_repaired(self):
        failed = self.result(); failed['errors'] = ['invalid_response']
        extra = self.result(); extra['output']['v'][0]['t'] = 'Parent invented text.'
        for result in (failed, extra, {'output': None, 'errors': ['invalid_response']}):
            with self.assertRaises(ValueError): self.bind(result)
        bound = self.bind(self.result())
        changed = deepcopy(bound); changed['response']['v'][0]['e'] = ['S000']
        with self.assertRaises(ValueError): mc.validate(changed)

    def test_one_supplement_preserves_existing_literal_and_rejects_repetition(self):
        first = self.bind(self.result(status='partial'))
        second = self.bind(self.result(evidence=['S000']), previous=first)
        self.assertEqual([c['text'] for c in second['claims']],
                         ['I wouldn’t stop working.', 'A yearly grant.'])
        self.assertEqual(mc.validate(second), second)
        with self.assertRaises(ValueError): self.bind(self.result(), previous=first)
        with self.assertRaises(ValueError): self.request(previous=second)


if __name__ == '__main__': unittest.main()
