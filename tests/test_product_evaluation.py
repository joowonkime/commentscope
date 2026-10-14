import unittest
from commentscope.factory.product_evaluation import execution_state


class ProductEvaluationTests(unittest.TestCase):
    def test_diagnostic_preserves_failed_and_incomplete_measurement(self):
        original = {'development_gate_passed': False, 'all_relations_complete': False,
                    'observed_evaluation': 5, 'planned_evaluation': 100, 'false_accepted_observed': ['J1']}
        state = execution_state(original, 'product_diagnostic')
        self.assertFalse(state['relation_target_met']); self.assertFalse(state['source_configuration_qualified'])
        self.assertEqual(state['source_measurement'], original)
        self.assertEqual(state['mvp_acceptance'], 'not_evaluated'); self.assertEqual(state['qualified_agents'], 0)
        state['source_measurement']['false_accepted_observed'].clear()
        self.assertEqual(original['false_accepted_observed'], ['J1'])

    def test_source_pass_never_implies_product_or_paper_pass(self):
        state = execution_state({'development_gate_passed': True, 'all_relations_complete': True}, 'qualified_configuration')
        self.assertTrue(state['source_configuration_qualified'])
        self.assertEqual(state['mvp_acceptance'], 'not_evaluated')
        self.assertEqual(state['paper_validation'], 'not_evaluated')

    def test_qualified_mode_and_unknown_modes_remain_closed(self):
        for purpose in ('qualified_configuration', 'skip', None):
            with self.subTest(purpose=purpose), self.assertRaises(ValueError):
                execution_state({'development_gate_passed': False}, purpose)
