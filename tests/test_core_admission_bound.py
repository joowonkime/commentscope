from copy import deepcopy
from itertools import product
import unittest
from unittest.mock import Mock

from commentscope.factory.automatic_contract import digest
from commentscope.factory.core_admission_bound import CoreAdmissionBound, STATES
from experiments.fresh_product_pipeline import Relations


def row(sid, candidate='A', text='Reviews should be required.'):
    claim = {'id': 'C', 'text': text, 'kind': 'fact', 'requires': [],
             'scope': {'entity': 'general', 'time': '', 'conditions': ''}}
    req = {'system': 'Synthetic membership', 'data': {'source': 'Source '+sid, 'target': claim},
           'schema': {}, 'max_tokens': 1}
    return {'id': candidate+sid, 'candidate_id': candidate, 'source_id': sid,
            'text': 'Source '+sid, 'claim': claim, 'request': req, 'request_sha256': digest(req)}


class CoreAdmissionBoundTests(unittest.TestCase):
    def test_exhaustive_gate_and_complete_accepted_counts(self):
        # Test every outcome order, not only convenient successful examples.
        for size, states in [(4, sorted(STATES)), (7, ['supported', 'unsupported'])]:
            rows = [row(str(i)) for i in range(size)]
            for outcomes in product(states, repeat=size):
                bound = CoreAdmissionBound(rows); known = 0; skipped = 0
                for r, state in zip(rows, outcomes, strict=True):
                    proof = bound.skip_proof(r)
                    if proof:
                        self.assertLess(proof['support_upper_bound'], 3); skipped += 1
                    else:
                        bound.observe(r, state); known += state == 'supported'
                total = outcomes.count('supported')
                self.assertEqual(known >= 3, total >= 3)
                if total >= 3:
                    self.assertEqual(known, total); self.assertEqual(skipped, 0)
                summary = bound.report()['pools'][0]
                self.assertEqual(summary['support_upper_bound'], known + skipped)
                self.assertGreaterEqual(summary['support_upper_bound'], total)

    def test_cross_retriever_sources_prevent_false_early_rejection(self):
        left = [row(s) for s in 'abc']; right = [row(s, 'B') for s in 'cde']
        bound = CoreAdmissionBound(left + right)
        for r in left[:2]: bound.observe(r, 'unsupported')
        # A alone cannot reach three, but the pooled c,d,e can.
        self.assertIsNone(bound.skip_proof(left[2]))
        for r in left[2:] + right:
            self.assertIsNone(bound.skip_proof(r)); bound.observe(r, 'supported')
        summary = bound.report()['pools'][0]
        self.assertEqual(summary['canonical_sources'], 5)
        self.assertEqual(summary['model_support_count'], 3)
        self.assertTrue(summary['support_count_complete'])

    def test_skipped_sources_remain_unknown_not_negative_votes(self):
        rows = [row(s) for s in 'abc']; bound = CoreAdmissionBound(rows)
        bound.observe(rows[0], 'partial')
        for r in rows[1:]:
            proof = bound.skip_proof(r)
            self.assertEqual(proof['support_upper_bound'], 2)
            self.assertEqual(proof['unassessed_sources'], 2)
        with self.assertRaises(ValueError): bound.observe(rows[1], 'unassessed')

    def test_opposite_or_conditioned_cores_never_pool(self):
        rows = [row(s) for s in 'abc'] + [row(s, 'B', 'Reviews should be voluntary.') for s in 'def']
        bound = CoreAdmissionBound(rows); bound.observe(rows[0], 'unsupported')
        self.assertIsNotNone(bound.skip_proof(rows[1]))
        self.assertIsNone(bound.skip_proof(rows[3]))
        changed = deepcopy(rows[0]); changed['claim']['scope']['conditions'] = 'Only for dangerous work'
        with self.assertRaises(ValueError): bound.skip_proof(changed)

    def test_population_and_duplicate_integrity(self):
        rows = [row(s) for s in 'abc']
        for field in ['text', 'request_sha256']:
            bad = deepcopy(rows[0]); bad[field] = 'changed'
            with self.assertRaises(ValueError): CoreAdmissionBound(rows + [bad])
        bad = deepcopy(rows[0]); bad['request']['max_tokens'] = 2; bad['request_sha256'] = digest(bad['request'])
        with self.assertRaises(ValueError): CoreAdmissionBound(rows + [bad])
        bound = CoreAdmissionBound(rows)
        with self.assertRaises(ValueError): bound.observe(row('outsider'), 'supported')
        bound.observe(rows[0], 'error')
        with self.assertRaises(ValueError): bound.observe(rows[0], 'supported')
        for minimum in [0, -1, True, 3.0]:
            with self.assertRaises(ValueError): CoreAdmissionBound(rows, minimum)

    def test_runner_never_calls_skipped_or_retries_failed_requests(self):
        rows = [row(s) for s in 'abc']; bound = CoreAdmissionBound(rows)
        runner = Mock(); runner.seq = 1; runner.call.return_value = {'errors': ['timeout'], 'output': None}
        memo = Relations(runner); actual = memo.judge(rows, 'core-baseline', admission_bound=bound)
        self.assertEqual(list(actual.values()), ['error', 'unassessed', 'unassessed'])
        self.assertEqual(runner.call.call_count, 1)
        self.assertTrue(all(t['call_sequence'] is None for t in memo.trace[1:]))
        self.assertTrue(all(t['bound']['support_upper_bound'] == 2 for t in memo.trace[1:]))
        memo.judge(rows[:1], 'core-neighborhood', admission_bound=bound)
        self.assertEqual(runner.call.call_count, 1)
        self.assertTrue(memo.trace[-1]['reused_within_run'])


if __name__ == '__main__': unittest.main()
