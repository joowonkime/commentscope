from collections import Counter
import unittest

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.agents.grounded_runtime import GroundedSession
from experiments import grounded_answer_probe as probe
from experiments.grounding_contract_demo import EXPIRY, response


class GroundedAnswerProbeTests(unittest.TestCase):
    def test_two_explicitly_synthetic_profiles_with_distinct_core(self):
        bundle = probe.bundle_fixture(EXPIRY)
        result = compile_inputs(bundle)
        self.assertEqual(len(result['profiles']), 2)
        self.assertEqual(len({p['core_claim_id'] for p in result['profiles']}), 2)
        self.assertEqual(result['source_judgment_origins'], ['synthetic_fixture'])
        self.assertFalse(result['quality_gate_passed'])

    def test_questions_are_balanced_and_references_not_in_request(self):
        rows = probe.questions(); bundle = probe.bundle_fixture(EXPIRY)
        self.assertEqual(Counter(r['cohort'] for r in rows), {'answerable': 10, 'unanswerable': 10})
        self.assertEqual(len({r['id'] for r in rows}), 20)
        for row in rows:
            req = GroundedSession(bundle, 'P1').invocation(row['text'])
            self.assertNotIn('target', req['data']); self.assertNotIn('cohort', req['data'])

    def test_contract_perfect_fixture_still_not_real_agents(self):
        bundle = probe.bundle_fixture(EXPIRY); rows = probe.questions(); rounds = []
        for row in rows:
            turns = {}
            for cid, available in [('P1', ['position', 'observed']), ('P2', ['optional', 'choice'])]:
                target = row['target']
                ids = [] if target == 'none' else available if target == 'both' else available[:1] if target == 'core' else available[1:]
                output = {'answerability': 'grounded' if ids else 'not_in_evidence', 'claim_ids': ids,
                          'limitation': 'none' if ids else 'missing_evidence'}
                turns[cid] = GroundedSession(bundle, cid, provider=lambda *a, out=output, **k: response(out)).ask(row['text'])
            rounds.append({'id': row['id'], 'turns': turns, 'seconds': 1})
        report = probe.summarize({'rows': rows, 'scope': 'test'}, rounds)
        self.assertTrue(report['controlled_answer_gate_passed'])
        self.assertEqual(report['counts']['answerable'], {'total': 20, 'passed': 20})
        self.assertEqual(report['counts']['unanswerable'], {'total': 20, 'passed': 20})
        self.assertEqual(report['real_agents'], 0); self.assertFalse(report['quality_gate_passed'])
        rounds[0]['turns']['P1']['status'] = 'error'
        report = probe.summarize({'rows': rows, 'scope': 'test'}, rounds)
        self.assertEqual(report['counts']['answerable']['passed'], 19)
        with self.assertRaises(ValueError): probe.summarize({'rows': rows, 'scope': 'test'}, rounds[:-1])


if __name__ == '__main__': unittest.main()
