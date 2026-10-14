from collections import Counter
from copy import deepcopy
import json
import unittest

from commentscope.factory import fact_checks as facts
from experiments import fact_gate_probe as gate
from experiments.grounding_contract_demo import fixture, response


class FactGateTests(unittest.TestCase):
    def source(self):
        bundle = fixture()
        return {'document': bundle['documents'][0], 'selections': bundle['checks'][0]['selections'],
                'model': bundle['model'], 'expires_at': bundle['expires_at']}

    def records(self, rows, state=None):
        records = []
        for row in rows:
            target = state or row['expected']
            output = {'verdict': target, 'supporting_ids': ['E1'] if target in {'supported', 'conflicting'} else [],
                      'refuting_ids': ['E2' if target == 'conflicting' else 'E1'] if target in {'refuted', 'conflicting'} else [],
                      'reason': 'Authored unit test output, not inference.'}
            records.append(facts.check(row['packet'], self.source()['model'], lambda *a, value=output, **k: response(value)))
        return records

    def test_fixed_balance_and_failed_policy_case_retained(self):
        cases = gate.case_definitions()
        self.assertEqual(Counter(c['expected'] for c in cases), dict.fromkeys(facts.STATES, 10))
        self.assertEqual(len({c['id'] for c in cases}), 40)
        self.assertIn('insufficient-later-policy', {c['id'] for c in cases})

    def test_references_not_in_model_request_and_provenance_explicit(self):
        source = self.source(); saved = deepcopy(source)
        for row in gate.build_rows(source):
            request = facts.invocation(row['packet'], source['model'])
            self.assertEqual(set(request['data']), {'CLAIM', 'EVIDENCE'})
            self.assertNotIn('reference_reason', json.dumps(request))
            self.assertNotIn('expected', request['data'])
            if row['source_cohort'] == 'synthetic_conflicting_controls':
                self.assertEqual(len(row['documents']), 2)
                self.assertTrue(all(d['source_kind'] == 'synthetic' for d in row['documents']))
            else:
                self.assertEqual(row['documents'], [source['document']])
        self.assertEqual(source, saved)

    def test_perfect_contract_counts_do_not_approve_product(self):
        rows = gate.build_rows(self.source())
        plan = {'rows': rows, 'model': self.source()['model'], 'scope': 'unit-test only'}
        report = gate.summarize(plan, self.records(rows))
        self.assertTrue(report['fact_decision_development_gate_passed'])
        self.assertFalse(report['quality_gate_passed']); self.assertEqual(report['agents'], [])
        self.assertEqual(sum(c['exact'] for c in report['by_reference'].values()), 40)

    def test_abstain_all_and_support_all_fail_distinct_checks(self):
        rows = gate.build_rows(self.source())
        plan = {'rows': rows, 'model': self.source()['model'], 'scope': 'unit-test only'}
        for state in ['supported', 'insufficient']:
            report = gate.summarize(plan, self.records(rows, state))
            self.assertFalse(report['fact_decision_development_gate_passed'])
        self.assertEqual(gate.summarize(plan, self.records(rows, 'supported'))['unsupported_false_support'], 30)

    def test_missing_record_is_not_a_smaller_denominator(self):
        rows = gate.build_rows(self.source())
        with self.assertRaises(ValueError):
            gate.summarize({'rows': rows, 'model': self.source()['model']}, self.records(rows)[:-1])


if __name__ == '__main__': unittest.main()
