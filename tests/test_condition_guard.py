import unittest

from commentscope.factory import condition_guard as guard


class ConditionGuardTests(unittest.TestCase):
    def test_dropped_conjunct_and_complete_condition_veto(self):
        source = 'I would work if income arrived and childcare remained available.'
        for target in ('I would work if income arrived.', 'I would work.'):
            with self.subTest(target=target):
                self.assertTrue(guard.check(source, target)['veto'])

    def test_condition_moved_and_consequent_weakened_is_not_vetoed(self):
        source = 'If the bus closed, I would cycle to work.'
        self.assertFalse(guard.check(source, 'I would travel to work if the bus closed.')['veto'])

    def test_consequent_conjunction_not_mistaken_for_condition(self):
        self.assertFalse(guard.check('Both a wage and a grant help me.', 'A grant helps me.')['veto'])

    def test_case_and_whitespace_only_normalization(self):
        self.assertFalse(guard.check('IF a grant arrived, I would work.', 'I would work if a  grant arrived.')['veto'])

    def test_paraphrase_and_added_condition_conservatively_vetoed(self):
        source = 'If income arrived, I would work.'
        for target in ('I would work if money arrived.', 'I would work if income arrived and I was healthy.'):
            self.assertTrue(guard.check(source, target)['veto'])

    def test_all_conditions_in_full_source_are_checked(self):
        source = 'If income arrived, I would work. I would move if rents fell.'
        self.assertTrue(guard.check(source, 'I would work if income arrived.')['veto'])

    def test_marker_role_is_preserved_not_anywhere_in_target(self):
        self.assertTrue(guard.check('If a grant arrived, I would work.', 'A grant arrived; I would work.')['veto'])

    def test_marker_word_boundaries_and_unchecked_language(self):
        for source in ('The tariff changed.', '지원금이 오면 일할 것이다.'):
            result = guard.check(source, 'Unrelated claim.')
            self.assertFalse(result['veto'])
            self.assertFalse(result['semantic_approval'])
            self.assertEqual(result['recognized_source_conditions'], 0)

    def test_each_declared_marker_and_exact_offsets(self):
        for marker in ('if', 'unless', 'provided that', 'as long as', 'only when', 'on condition that', 'assuming that'):
            source = f'I would work {marker} transport was available.'
            audit = guard.check(source, 'I would work.')
            self.assertTrue(audit['veto'])
            for span in audit['missing']:
                self.assertEqual(source[span['start']:span['end']], span['text'])

    def test_nothing_can_be_promoted_and_errors_survive(self):
        source = 'I would work if income arrived.'
        claim = {'text': 'I would work.'}
        for raw in ('supported', 'partial', 'unsupported', 'unclear'):
            result = {'errors': [], 'output': {'verdict': raw, 'reason': 'test'}}
            self.assertEqual(guard.effective(result, source, claim, guard.VERSION), 'unclear' if raw == 'supported' else raw)
            self.assertEqual(guard.effective(result, source, claim), raw)
        self.assertEqual(guard.effective({'errors': ['timeout']}, source, claim, guard.VERSION), 'error')
        with self.assertRaises(ValueError):
            guard.effective({'errors': ['timeout']}, source, claim, 'unknown')
