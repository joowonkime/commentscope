"""Deterministic runtime identity/history checks; no inference or quality labels."""
from copy import deepcopy
import unittest

from commentscope.agents.runtime_probe import QUESTIONS, runtime_check
from commentscope.factory.automatic_contract import digest


class RuntimeArtifactContractTests(unittest.TestCase):
    def setUp(self):
        self.compiled = {'profiles': [{'candidate_id': 'A'}, {'candidate_id': 'B'}]}
        self.runtime = {'all_compiled_candidate_ids': ['A', 'B'], 'turns': [
            {'candidate_id': cid, 'question_id': q['id'], 'other_histories_unchanged': True,
             'turn': {'candidate_id': cid, 'question': q['text'], 'status': 'answered',
                      'compiled_sha256': digest(self.compiled)}}
            for cid in ['A', 'B'] for q in QUESTIONS]}

    def test_complete_runtime_and_explicit_abstention_are_valid(self):
        self.runtime['turns'][0]['turn']['status'] = 'abstain'
        runtime_check(self.runtime, self.compiled)

    def test_cross_agent_history_change_is_rejected(self):
        self.runtime['turns'][0]['other_histories_unchanged'] = False
        with self.assertRaisesRegex(ValueError, 'history'):
            runtime_check(self.runtime, self.compiled)

    def test_missing_history_check_is_not_assumed_successful(self):
        del self.runtime['turns'][0]['other_histories_unchanged']
        with self.assertRaisesRegex(ValueError, 'history'):
            runtime_check(self.runtime, self.compiled)

    def test_numeric_history_flag_is_not_a_true_verification(self):
        self.runtime['turns'][0]['other_histories_unchanged'] = 1
        with self.assertRaisesRegex(ValueError, 'history'):
            runtime_check(self.runtime, self.compiled)

    def test_turn_from_another_agent_cannot_use_the_outer_label(self):
        self.runtime['turns'][0]['turn']['candidate_id'] = 'B'
        with self.assertRaisesRegex(ValueError, 'Agent'):
            runtime_check(self.runtime, self.compiled)

    def test_question_identifier_cannot_hide_a_different_question(self):
        self.runtime['turns'][0]['turn']['question'] = 'A different question'
        with self.assertRaisesRegex(ValueError, 'question'):
            runtime_check(self.runtime, self.compiled)

    def test_error_status_is_not_a_valid_executed_answer(self):
        self.runtime['turns'][0]['turn']['status'] = 'error'
        with self.assertRaisesRegex(ValueError, 'status'):
            runtime_check(self.runtime, self.compiled)

    def test_missing_or_duplicate_fixed_turn_is_rejected(self):
        self.runtime['turns'][-1] = deepcopy(self.runtime['turns'][0])
        with self.assertRaises(ValueError):
            runtime_check(self.runtime, self.compiled)

    def test_historical_question_text_is_checked_against_its_frozen_plan(self):
        frozen = [{'id': q['id'], 'text': 'Frozen question: '+q['text']} for q in QUESTIONS]
        texts = {q['id']: q['text'] for q in frozen}
        for row in self.runtime['turns']:
            row['turn']['question'] = texts[row['question_id']]
        runtime_check(self.runtime, self.compiled, questions=frozen)

    def test_empty_partial_run_is_not_given_a_new_agent_minimum(self):
        runtime_check({'all_compiled_candidate_ids': [], 'turns': []}, {'profiles': []})


if __name__ == '__main__':
    unittest.main()
