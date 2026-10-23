from copy import deepcopy
from collections import Counter
import unittest

from experiments import actual_agent_probe as probe
from experiments.grounded_answer_probe import bundle_fixture
from experiments.grounding_contract_demo import EXPIRY, response
from commentscope.agents.grounded_runtime import GroundedSession


class ActualAgentProbeTests(unittest.TestCase):
    def setup_plan(self):
        bundle = bundle_fixture(EXPIRY); refs = probe.inventory(bundle)
        return {'bundle': bundle, 'references': refs, 'all_profile_ids': list(refs),
                'rows': probe.questions(), 'upstream_review_passed': False}

    def rounds(self, plan):
        result = []
        texts = {c['id']: c['text'] for c in plan['bundle']['claims']}
        for row in plan['rows']:
            turns = {}
            for cid in plan['all_profile_ids']:
                ids = plan['references'][cid][row['target']]
                value = {'claim_ids': ids, 'answerability': 'grounded' if ids else 'not_in_evidence',
                         'limitation': 'none' if ids else 'missing_evidence'}
                def provider(system, data, schema, *, v=value, **kwargs):
                    aliases = {e['text']: e['claim_id'] for e in data['PERSPECTIVE']['allowed_entries']}
                    return response({**v, 'claim_ids': [aliases[texts[i]] for i in v['claim_ids']]})
                turns[cid] = GroundedSession(plan['bundle'], cid, provider=provider).ask(row['text'])
            result.append({'id': row['id'], 'turns': turns, 'pair_seconds': 1})
        return result

    def test_frozen_questions_do_not_send_labels_to_model(self):
        plan = self.setup_plan()
        self.assertEqual(Counter(r['cohort'] for r in plan['rows']), {'answerable': 10, 'unanswerable': 10})
        for row in plan['rows']:
            req = GroundedSession(plan['bundle'], 'P1').invocation(row['text'])
            self.assertFalse(set(req['data']) - {'PERSPECTIVE','QUESTION','HISTORY','QUESTION_ROLE_CONSTRAINT'})
            self.assertNotIn('cohort', req['data']); self.assertNotIn('target', req['data'])

    def test_all_profiles_scored_without_quality_promotion(self):
        plan = self.setup_plan(); report = probe.summarize(plan, self.rounds(plan))
        self.assertTrue(report['actual_input_answer_gate_passed'])
        self.assertEqual(report['counts']['answerable'], {'total':20,'passed':20})
        self.assertEqual(report['counts']['unanswerable'], {'total':20,'passed':20})
        self.assertFalse(report['quality_gate_passed']); self.assertFalse(report['upstream_review_passed'])

    def test_missing_candidate_question_or_required_reason_is_not_hidden(self):
        plan = self.setup_plan(); rounds = self.rounds(plan)
        with self.assertRaises(ValueError): probe.summarize(plan, rounds[:-1])
        missing = deepcopy(rounds); missing[0]['turns'].pop('P2')
        with self.assertRaises(ValueError): probe.summarize(plan, missing)
        rounds[5]['turns']['P1']['points'] = []
        self.assertEqual(probe.summarize(plan, rounds)['by_profile']['P1']['answerable']['passed'], 9)

    def test_each_profile_and_latency_must_pass_not_just_average(self):
        plan = self.setup_plan(); rounds = self.rounds(plan)
        for i in (0,1): rounds[i]['turns']['P1']['status'] = 'error'
        self.assertFalse(probe.summarize(plan, rounds)['actual_input_answer_gate_passed'])
        rounds = self.rounds(plan)
        for r in rounds: r['pair_seconds'] = 61
        self.assertFalse(probe.summarize(plan, rounds)['actual_input_answer_gate_passed'])

    def test_inventory_does_not_handpick_two_profiles(self):
        plan = self.setup_plan(); bundle = plan['bundle']
        third = deepcopy(bundle['candidates'][1]); third['id'] = 'P3'; bundle['candidates'].append(third)
        self.assertEqual(list(probe.inventory(bundle)), ['P1','P2','P3'])
        bundle['candidates'] = bundle['candidates'][:1]
        with self.assertRaises(ValueError): probe.inventory(bundle)


if __name__ == '__main__': unittest.main()
