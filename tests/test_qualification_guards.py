import unittest
from commentscope.factory import qualification_guards as guard


class QualificationGuardsTests(unittest.TestCase):
    def test_explicit_future_and_current_block_with_original_witness_offsets(self):
        a, b = 'Automation will replace jobs.', 'Automation is replacing jobs.'
        result = guard.compare(a, b)
        self.assertFalse(result['allowed'])
        self.assertIn('explicit_time_change', result['blocked_reasons'])
        for side, text in [('source', a), ('target', b)]:
            for rows in result['time_witnesses'][side].values():
                for r in rows: self.assertEqual(text[r['start']:r['end']], r['text'])

    def test_normative_and_conditional_synonyms_are_not_category_vetoes(self):
        self.assertTrue(guard.compare('The library should open longer.', 'The library ought to extend its hours.')['allowed'])
        self.assertTrue(guard.compare('If rent rises, support should increase.', 'If rents go up, support should increase.')['allowed'])

    def test_condition_drop_add_and_operator_changes_block(self):
        for a, b in [('If jobs disappear, help is needed.', 'Help is needed.'),
                     ('Help is needed.', 'Unless jobs disappear, help is needed.'),
                     ('If jobs disappear, help is needed.', 'Unless jobs disappear, help is needed.')]:
            self.assertIn('explicit_condition_change', guard.compare(a, b)['blocked_reasons'])

    def test_unrecognized_tense_is_not_claimed_safe(self):
        result = guard.compare('Machines replace workers.', 'Machines will replace workers.')
        self.assertTrue(result['time_alignment_abstained'])
        self.assertTrue(result['allowed'])  # Means no mechanical veto, not semantic support.

    def test_mixed_or_reported_events_abstain_from_surface_time_alignment(self):
        for text in ['The author says automation will replace jobs.',
                     'Automation is replacing jobs and will replace more.',
                     'Automation could replace jobs.']:
            self.assertTrue(guard.compare(text, 'Automation is replacing jobs.')['time_alignment_abstained'])


if __name__ == '__main__': unittest.main()
