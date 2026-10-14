from copy import deepcopy
import unittest

from commentscope.factory import candidate_search as retrieval, grounded_core as core, core_groups
from experiments.claim_frame_probe import unit


def score(*args):
    return {'errors': [], 'relation': 'supports', 'scores': {'entailment': .9, 'neutral': .05, 'contradiction': .05}}


def audit(source):
    return {'support': 'supported', 'evidence_quote': source, **{f: 'preserved' for f in core.FIELDS}}


class GroundedCoreTests(unittest.TestCase):
    def calls(self, system, data, schema):
        if system == core.PROPOSE_SYSTEM:
            self.assertEqual(set(data), {'LEFT', 'RIGHT'})
            return {'errors': [], 'output': {'core': 'A substantive common proposition.'}}
        self.assertEqual(set(data), {'SOURCE', 'TARGET'})
        return {'errors': [], 'output': audit(data['SOURCE'])}

    def test_source_failure_never_rescued_by_audit(self):
        def reject(*args):
            return {'errors': [], 'relation': 'not_established', 'scores': {'entailment': .05, 'neutral': .9, 'contradiction': .05}}
        def forbidden(*args): self.fail('No rescue call permitted')
        self.assertFalse(core.verify('A', 'B', forbidden, reject)['allowed'])

    def test_quote_and_enums_are_checked_not_trusted(self):
        self.assertFalse(core.validate_audit(audit('Source'), 'Source'))
        for patch in [{'evidence_quote': 'Foreign'}, {'evidence_quote': ''}, {'time': 'changed'},
                      {'support': []}, {'scope': 'present'}, {'extra': True}]:
            self.assertTrue(core.validate_audit({**audit('Source'), **patch}, 'Source'))

    def test_high_nli_score_does_not_override_relational_rejection(self):
        def changed(system, data, schema):
            return {'errors': [], 'output': {**audit(data['SOURCE']), 'support': 'unsupported', 'presuppositions': 'changed'}}
        result = core.verify('I would take a job.', 'I would keep my current job.', changed, score)
        self.assertFalse(result['allowed'])
        self.assertIn('presuppositions', result['blocked_reasons'])

    def test_explicit_time_or_condition_veto_cannot_be_rescued_by_models(self):
        def forbidden(*args): self.fail('Mechanical veto must not call audit')
        for a, b in [('Automation will replace jobs.', 'Automation is replacing jobs.'),
                     ('If jobs disappear, help is needed.', 'Help is needed.')]:
            self.assertFalse(core.verify(a, b, forbidden, score)['allowed'])

    def test_original_source_and_claim_both_checked(self):
        checked = []
        def calls(system, data, schema):
            checked.append(data)
            return self.calls(system, data, schema)
        u = unit('a', 'Original source', 'Extracted claim')
        prepared = core.prepare(u, calls, score)
        self.assertTrue(core.check_core(u, prepared, 'Core', calls, score)['allowed'])
        self.assertIn({'SOURCE': 'Original source', 'TARGET': 'Core'}, checked)
        self.assertIn({'SOURCE': 'Extracted claim', 'TARGET': 'Core'}, checked)
        changed = deepcopy(u); changed['statement'] = 'Changed'
        with self.assertRaises(ValueError): core.check_core(changed, prepared, 'Core', calls, score)

    def test_proposal_first_not_shortest_or_automatic_evidence(self):
        result = core.discover(unit('a', 'Source A', 'A'), unit('b', 'Source B', 'B'), self.calls, score)
        self.assertEqual(len(result['candidates']), 3)
        self.assertEqual(result['selected_core'], 'A substantive common proposition.')

    def test_self_control_keeps_two_input_slots(self):
        a = unit('a', 'Source', 'Claim')
        result = core.discover(a, a, self.calls, score)
        self.assertEqual(len(result['prepared']), 2)

    def data(self):
        return [{'claim_id': str(i), 'source_comment_id': 's'+str(i), 'mode': mode,
                 'statement': 'Transit service should improve', 'spans': [{'text': 'Source'}]}
                for i, mode in enumerate(['normative', 'prediction', 'description'])]

    def test_cross_mode_retrieval_is_not_semantic_approval(self):
        units = self.data(); vectors = [[1., 0.]]*3
        self.assertEqual(retrieval.funnel(units, retrieval.search(units, vectors, 'same_mode'))['with_neighbors'], 0)
        candidates = retrieval.search(units, vectors, 'cross_mode')
        self.assertEqual(retrieval.funnel(units, candidates)['eligible_anchors'], 3)
        reject = lambda *args: {'selected_core': None}
        result = core_groups.assemble(units, candidates, reject, lambda *args: {'allowed': False}, cross_mode=True)
        self.assertFalse(result['groups'])
        self.assertEqual(core_groups.replay(units, candidates, result, reject, lambda *args: {'allowed': False}), result)
        with self.assertRaises(ValueError): core_groups.assemble(units, candidates, reject, reject)

    def test_hybrid_bounds_determinism_and_no_same_source(self):
        units = self.data()*1
        for i in range(3, 20): units.append({**units[0], 'claim_id': str(i), 'source_comment_id': 's'+str(i)})
        units[1]['source_comment_id'] = units[0]['source_comment_id']
        result = retrieval.search(units, [[1., 0.]]*len(units))
        self.assertEqual(result, retrieval.search(units, [[1., 0.]]*len(units)))
        self.assertTrue(all(len(v) <= 12 for v in result.values()))
        self.assertNotIn('1', [r['claim_id'] for r in result['0']])

    def test_retrieval_input_validation(self):
        units = self.data()
        for vectors in [[], [[0., 0.]]*3, [[1., float('nan')]]*3, [[1.], [1., 2.], [1.]]]:
            with self.assertRaises(ValueError): retrieval.search(units, vectors)
        self.assertEqual(retrieval.search([], []), {})


if __name__ == '__main__': unittest.main()
