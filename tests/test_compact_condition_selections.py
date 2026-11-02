"""Typed addresses and complete conditional selections are proposals, never votes."""
from copy import deepcopy
import unittest

from commentscope.factory import compact_claims as compact, minimal_claims as mc


class ConditionalSelectionTests(unittest.TestCase):
    def source(self, text):
        return {'id': 'own', 'text': text,
                'parent': {'id': 'parent', 'text': 'Adopt P only if funded.'}}

    def request(self, source):
        return compact.request(source, protocol=compact.MASKED)

    def result(self, source, *, claims=(), selections=None, status='covered'):
        req = self.request(source)
        locked = req['data']['LOCKED_CONDITIONALS']
        value = {'s': status, 'c': list(claims)}
        if locked: value['l'] = {row['id']: 'asserted' for row in locked} if selections is None else selections
        return {'output': value}

    def test_condition_is_selected_verbatim_before_any_generated_text_exists(self):
        for text in ('I support adopting P only if small providers receive fee waivers.',
                     '소규모 기관의 수수료가 면제될 때만 의무 도입에 찬성합니다.'):
            with self.subTest(text=text):
                source = self.source(text); req = self.request(source)
                self.assertEqual(req['data']['LOCKED_CONDITIONALS'][0]['text'], text)
                bound = compact.bind(source, self.result(source), protocol=compact.MASKED)
                self.assertEqual(bound['claims'][0]['text'], text)
                self.assertTrue(bound['claims'][0]['essential_conditions'])
                self.assertFalse(bound['semantic_approval'])
                self.assertEqual(mc.candidates([bound])[0]['text'], text)
                self.assertEqual(mc.validate(bound), bound)

    def test_cannot_generate_bare_stance_or_independent_demand_from_locked_condition(self):
        source = self.source('I support adopting P only if providers receive fee waivers.')
        for text in ('I support adopting P.', 'Providers must receive fee waivers.'):
            claim = {'t': text, 'e': {'S000': True}, 'k': {'S000': False}, 'a': 'asserted'}
            with self.subTest(text=text), self.assertRaises(ValueError):
                compact.bind(source, self.result(source, claims=[claim]), protocol=compact.MASKED)

    def test_quotes_questions_and_parent_never_create_own_literal_selections(self):
        for text in ('Someone said "Adopt P only if funded."',
                     'Should we adopt P only if funded?', 'Adopt P.'):
            self.assertEqual(self.request(self.source(text))['data']['LOCKED_CONDITIONALS'], [])

    def test_reported_uncertain_and_omitted_selections_never_nominate(self):
        source = self.source('Adopt P only if funded.')
        key = self.request(source)['data']['LOCKED_CONDITIONALS'][0]['id']
        for author in ('reported', 'uncertain', 'omitted'):
            result = self.result(source, selections={key: author},
                                 status='non_substantive' if author == 'omitted' else 'covered')
            bound = compact.bind(source, result, protocol=compact.MASKED)
            self.assertEqual(mc.candidates([bound]), [])

    def test_masks_accept_only_exact_child_addresses_and_boolean_values(self):
        source = self.source('Adopt P. Protect privacy.')
        claim = {'t': 'Adopt P.', 'e': {'S000': True, 'S001': False},
                 'k': {'S000': False, 'S001': False}, 'a': 'asserted'}
        bound = compact.bind(source, self.result(source, claims=[claim]), protocol=compact.MASKED)
        self.assertEqual([s['id'] for s in bound['claims'][0]['evidence']], ['S000'])
        for mask in ({'S000': 1, 'S001': False}, {'S000': 'true', 'S001': False},
                     {'S000': True}, {'S000': True, 'S001': False, 'parent': True},
                     'S000', {'S000': False, 'S001': False}):
            row = {**claim, 'e': mask}
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                compact.bind(source, self.result(source, claims=[row]), protocol=compact.MASKED)

    def test_locked_addresses_and_protocol_cannot_be_changed_or_mixed_on_supplement(self):
        source = self.source('Adopt P only if funded. Protect privacy.')
        first = compact.bind(source, self.result(source, status='partial'), protocol=compact.MASKED)
        for modify in (lambda r: r['response']['l'].update(C99='asserted'),
                       lambda r: r['claims'][0].update(text='Adopt P.'),
                       lambda r: r.update(artifact_kind=compact.VERSION)):
            changed = deepcopy(first); modify(changed)
            with self.assertRaises(ValueError): mc.validate(changed)
        with self.assertRaises(ValueError): compact.request(source, previous=first)

    def test_supplement_preserves_complete_condition_without_reclassifying_or_repeating_it(self):
        source = self.source('Adopt P only if funded. Protect privacy.')
        first = compact.bind(source, self.result(source, status='partial'), protocol=compact.MASKED)
        req = compact.request(source, previous=first, protocol=compact.MASKED)
        self.assertEqual(req['schema']['properties']['l']['properties']['C1']['enum'], ['omitted'])
        claim = {'t': 'Protect privacy.', 'e': {'S000': False, 'S001': True},
                 'k': {'S000': False, 'S001': False}, 'a': 'asserted'}
        result = self.result(source, claims=[claim], selections={'C1': 'omitted'})
        second = compact.bind(source, result, previous=first, protocol=compact.MASKED)
        self.assertEqual([c['text'] for c in second['claims']],
                         ['Adopt P only if funded.', 'Protect privacy.'])
        self.assertEqual(mc.validate(second), second)
        with self.assertRaises(ValueError):
            compact.bind(source, self.result(source), previous=first, protocol=compact.MASKED)


class IndexedSelectionTests(unittest.TestCase):
    def test_binary_transport_has_the_same_canonical_checks_and_literal_conditions(self):
        source = {'id': 'own', 'text': 'Adopt P only if funded.', 'parent': None}
        result = {'output': {'s': 'covered', 'c': [], 'l': {'C1': 'asserted'}}}
        indexed = compact.bind(source, result, protocol=compact.INDEXED)
        masked = compact.bind(source, result, protocol=compact.MASKED)
        self.assertEqual(indexed['canonical_record'], masked['canonical_record'])
        self.assertNotEqual(indexed['request_sha256'], masked['request_sha256'])
        self.assertEqual(mc.validate(indexed), indexed)

    def test_only_one_binary_character_per_own_segment_is_accepted(self):
        source = {'id': 'own', 'text': 'Adopt P. Protect privacy.', 'parent': None}
        req = compact.request(source, protocol=compact.INDEXED)
        self.assertEqual(req['data']['ADDRESS_ORDER'], ['S000', 'S001'])
        self.assertEqual(req['schema']['properties']['c']['items']['properties']['e']['pattern'], '^[01]{2}$')
        self.assertIn('binary strings', req['system'])
        claim = {'t': 'Adopt P.', 'e': '10', 'k': '00', 'a': 'asserted'}
        def bind(row):
            return compact.bind(source, {'output': {'s': 'covered', 'c': [row]}}, protocol=compact.INDEXED)
        bound = bind(claim)
        self.assertEqual([s['id'] for s in bound['claims'][0]['evidence']], ['S000'])
        self.assertEqual(mc.validate(bound), bound)
        for key in ('e', 'k'):
            for mask in ('S000', '1', '101', '10\n', ' 10', '12', 'true', 10, {'S000': True}):
                with self.subTest(key=key, mask=mask), self.assertRaises(ValueError):
                    bind({**claim, key: mask})
        with self.assertRaises(ValueError): bind({**claim, 'e': '00'})

    def test_binary_masks_cannot_bypass_the_full_conditional_selection(self):
        source = {'id': 'own', 'text': 'Adopt P only if funded.', 'parent': None}
        result = {'output': {'s': 'covered', 'c': [
            {'t': 'Adopt P.', 'e': '1', 'k': '0', 'a': 'asserted'}], 'l': {'C1': 'omitted'}}}
        with self.assertRaises(ValueError): compact.bind(source, result, protocol=compact.INDEXED)


if __name__ == '__main__': unittest.main()
