from copy import deepcopy
import unittest

from commentscope.factory import candidate_consolidation as cc, minimal_claims as mc
from commentscope.factory import proposition_requirements as pr
from commentscope.factory import raw_membership as raw
from test_minimal_factory import extraction, membership
import test_contextual_propositions as scoped_fixture


class EquivalenceAssertionBoundaryTests(unittest.TestCase):
    def raw_members(self, sources, candidates):
        originals = {s['id']: s for s in sources}
        proofs = [raw.bind(originals[sid], c, {'output': {
            'relation': 'supported', 'authorship': 'asserted_or_endorsed',
            'candidate_interpretation': 'clear', 'scope_preserved': 'yes',
            'contribution': 'substantive', 'evidence_segment_ids': ['S000']}})
            for c in candidates for sid in c['nominees']]
        return [raw.batch(sources, candidates, proofs)]

    def setup_inputs(self, suffix='because access matters.'):
        sources = [
            {'id': 'a', 'text': 'Extend library hours '+suffix, 'parent': None},
            {'id': 'b', 'text': 'Keep the library open longer. Add more windows.', 'parent': None}]
        candidates = mc.candidates(extraction(sources, {
            'a': ['Extend library hours.'], 'b': ['Keep the library open longer.']}))
        pairs = [{'source_id': sid, 'candidate_id': c['id']}
                 for c in candidates for sid in c['nominees']]
        members = [membership(sources, candidates, pairs)]
        pair = [dict(zip(('a', 'b'), sorted(c['id'] for c in candidates)))]
        return sources, candidates, members, pair

    def request(self, inputs):
        return cc.equivalence_request(*inputs, protocol=cc.ASSERTION_ONLY)

    def test_source_only_reasons_and_extra_requests_cannot_enter_compared_assertions(self):
        inputs = self.setup_inputs()
        req = self.request(inputs)
        pair = req['data']['PAIRS'][0]
        self.assertEqual({pair['A']['text'], pair['B']['text']},
                         {'Extend library hours.', 'Keep the library open longer.'})
        self.assertNotIn('access matters', str(req['data']))
        self.assertNotIn('Add more windows', str(req['data']))
        self.assertNotIn('SUPPORTING_ORIGINALS', str(req['data']))
        changed = self.request(self.setup_inputs('because quiet space matters.'))
        self.assertEqual(req, changed)
        self.assertNotEqual(inputs[0], self.setup_inputs('because quiet space matters.')[0])

    def test_complete_candidate_conditions_and_negation_are_not_trimmed(self):
        sources = [{'id': 'a', 'text': 'Extend hours only if staff are paid.', 'parent': None},
                   {'id': 'b', 'text': 'Do not extend hours.', 'parent': None}]
        candidates = mc.candidates(extraction(sources, {s['id']: [s['text']] for s in sources}))
        members = self.raw_members(sources, candidates)
        pair = [dict(zip(('a', 'b'), sorted(c['id'] for c in candidates)))]
        before = deepcopy((sources, candidates, members, pair))
        req = self.request((sources, candidates, members, pair))
        self.assertEqual({req['data']['PAIRS'][0][k]['text'] for k in ('A', 'B')},
                         {s['text'] for s in sources})
        self.assertEqual(before, (sources, candidates, members, pair))

    def test_equivalent_still_needs_both_full_text_qualification_checks(self):
        inputs = self.setup_inputs(); source, candidates, members, pairs = inputs
        result = {'output': {'decisions': [{'pair_id': 'P1', 'relation': 'equivalent'}]}}
        audit = cc.bind(*inputs, result, protocol=cc.ASSERTION_ONLY)
        self.assertEqual(audit['relations'][0]['relation'], 'uncertain')
        self.assertEqual(len(cc.consolidate(source, candidates, members, [audit])['candidates']), 2)
        lookup = {c['id']: c for c in candidates}; p = pairs[0]; checks = []
        for left, right in ((p['a'], p['b']), (p['b'], p['a'])):
            shape = pr.bind_shape(lookup[right]['text'], {'output': {'status': 'complete', 'qualifications': []}})
            checks.append({'from_candidate_id': left, 'to_candidate_id': right,
                           'assessment': pr.assessment({'id': left, 'text': lookup[left]['text'], 'parent': None}, shape, [])})
        audit = cc.bind(*inputs, result, checks, protocol=cc.ASSERTION_ONLY)
        merged = cc.consolidate(source, candidates, members, [audit])
        self.assertEqual(len(merged['candidates']), 1)
        self.assertFalse(merged['memberships'])
        self.assertTrue(merged['final_wording_reassessment_required'])
        audit['protocol'] = 'unknown'
        with self.assertRaises(ValueError):
            cc.consolidate(source, candidates, members, [audit])

    def test_context_bound_assertions_cannot_be_stripped_into_text_only_comparisons(self):
        records = [scoped_fixture.selected({'id': sid, 'text': 'This is expensive.',
                    'parent': {'id': 'p'+sid, 'text': topic}})
                   for sid, topic in [('a', 'Rail tickets.'), ('b', 'Parking permits.')]]
        sources = [r['source'] for r in records]; candidates = mc.candidates(records)
        members = self.raw_members(sources, candidates)
        pair = [dict(zip(('a', 'b'), sorted(c['id'] for c in candidates)))]
        with self.assertRaisesRegex(ValueError, 'context|scoped|Context'):
            self.request((sources, candidates, members, pair))
        self.assertIn('BOUND_MEANING', str(cc.equivalence_request(sources, candidates, members, pair)))

    def test_historical_context_request_and_binding_still_replay(self):
        inputs = self.setup_inputs()
        req = cc.equivalence_request(*inputs)
        self.assertIn('SUPPORTING_ORIGINALS', str(req['data']))
        audit = cc.bind(*inputs, {'output': {'decisions': [{'pair_id': 'P1', 'relation': 'different'}]}})
        self.assertNotIn('protocol', audit)
        self.assertEqual(len(cc.consolidate(*inputs[:3], [audit])['candidates']), 2)
