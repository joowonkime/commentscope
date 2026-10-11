from copy import deepcopy
import random
import string
import unittest

from commentscope.factory import evidence_units as e, evidence_core, core_groups
from commentscope.factory.automatic_contract import segments


class EvidenceUnitsTests(unittest.TestCase):
    def calls(self, system, data, schema):
        if system == e.SELECT_SYSTEM:
            return {'errors': [], 'output': {'status': 'substantive', 'ranges': [{'first': 'S000', 'last': 'S000'}]}}
        return {'errors': [], 'output': {'status': 'substantive', 'topic_quote': 'trains'}}

    def test_no_model_authored_statement_or_foreign_segment_is_accepted(self):
        parts = segments('Trains should be frequent.')
        for value in [{'status': 'substantive', 'ranges': [{'first': 'S000', 'last': 'S000', 'statement': 'Invented'}]},
                      {'status': 'substantive', 'ranges': [{'first': 'S000', 'last': 'S099'}]},
                      {'status': 'substantive', 'ranges': []}]:
            self.assertTrue(e.validate_selection(value, parts))

    def test_context_is_own_comment_and_exactly_bounded(self):
        original = 'I receive housing assistance. I get $820 each month.'
        u = e.bind('source', original, {'first': 'S001', 'last': 'S001'}, 'housing assistance')
        self.assertEqual(u['statement'], 'I get $820 each month.')
        self.assertEqual(''.join(s['text'] for s in u['spans']), original)
        self.assertEqual(len(u['focus_spans']), 1)
        e.validate_bound(u, original)
        with self.assertRaises(ValueError): e.validate_bound(u, 'Foreign parent comment.')
        with self.assertRaises(ValueError): e.bind('source', original, {'first': 'S001', 'last': 'S001'}, 'basic income')

    def test_long_context_is_not_silently_truncated(self):
        text = 'A'*510+'. Useful trains.'
        self.assertIsNone(e.bind('source', text, {'first':'S001', 'last':'S001'}, 'trains'))

    def test_deictic_formula_is_blocked_even_if_selector_approves(self):
        for text in ['We should do it.', 'I agree with that.', 'They should do this!']:
            def calls(system, data, schema):
                self.assertEqual(system, e.SELECT_SYSTEM)
                return {'errors': [], 'output': {'status':'substantive', 'ranges':[{'first':'S000','last':'S000'}]}}
            result = e.extract('s', text, calls)
            self.assertFalse(result['units'])
            self.assertEqual(result['candidates'][0]['reason'], 'no_lexical_content')

    def test_no_topic_whitelist_or_blanket_pronoun_rejection(self):
        self.assertTrue(e.has_topic('AI-generated videos can mislead viewers.'))
        self.assertTrue(e.has_topic('It should arrive on time.'))
        self.assertTrue(e.has_topic('안전 검사를 의무화해야 한다.'))

    def test_property_literal_integrity_and_mutation_rejection(self):
        rng = random.Random(407)
        for i in range(100):
            token = ''.join(rng.choices(string.ascii_letters, k=20))
            original = token+' trains are useful. Another sentence.'
            u = e.bind(str(i), original, {'first':'S000','last':'S000'}, 'trains')
            e.validate_bound(u, original)
            for field in ['statement', 'topic_quote', 'source_comment_id']:
                bad = deepcopy(u); bad[field] += ' invented'
                with self.assertRaises((ValueError, KeyError)): e.validate_bound(bad, original)
            bad = deepcopy(u); bad['spans'][0]['text'] = 'Invented source'
            with self.assertRaises(ValueError): e.validate_bound(bad, original)

    def test_selection_then_independent_eligibility(self):
        result = e.extract('s', 'These trains are useful.', self.calls)
        self.assertEqual(result['units'][0]['statement'], 'These trains are useful.')
        def reject(system, data, schema):
            if system == e.SELECT_SYSTEM: return self.calls(system, data, schema)
            return {'errors': [], 'output': {'status':'non_substantive','topic_quote':''}}
        self.assertFalse(e.extract('s', 'These trains are useful.', reject)['units'])

    def test_core_formula_does_not_become_a_shared_perspective(self):
        def forbidden(*args): self.fail('No model required to reject empty formula')
        self.assertFalse(evidence_core.eligibility('We should do it', forbidden)['allowed'])

    def test_density_order_uses_second_distinct_source_not_degree_or_id(self):
        us = [{'claim_id': x, 'source_comment_id': x, 'mode': 'literal', 'spans':[{'text':x}]} for x in ['a','b','c','z']]
        links = {u['claim_id']:[{'claim_id':v['claim_id'], 'cosine': .1} for v in us if v != u] for u in us}
        links['z'][0]['cosine'] = .95; links['z'][1]['cosine'] = .9
        reject = lambda *args: {'selected_core': None}
        result = core_groups.assemble(us, links, reject, reject, budget=1, cross_mode=True, seed_order='source_density')
        self.assertEqual(result['decisions'][0]['anchor_id'], 'z')
        self.assertEqual(core_groups.replay(us, links, result, reject, reject), result)


if __name__ == '__main__': unittest.main()
