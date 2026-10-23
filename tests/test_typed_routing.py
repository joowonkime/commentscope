import unittest
from commentscope.providers.local_nli import decide
from commentscope.providers.typed_routing import hypotheses, combine


class TypedRoutingTests(unittest.TestCase):
    def checks(self, values):
        result = {}
        for label,v in zip(hypotheses(),values):
            scores={'entailment':v,'neutral':1-v,'contradiction':0.}
            result[label]={'scores':scores,'relation':decide(scores),'errors':[]}
        return result

    def test_relative_high_score_is_not_absolute_support(self):
        r=combine(self.checks([.01,.00001,.00001]))
        self.assertGreater(r['option_scores']['substantive'],.99)
        self.assertEqual(r['selected'],'substantive');self.assertFalse(r['strict_eligible'])

    def test_ties_are_unresolved_and_errors_not_semantic_votes(self):
        self.assertIsNone(combine(self.checks([.3,.3,.3]))['selected'])
        c=self.checks([.9,.01,.01]);c['substantive']['errors']=['RuntimeError']
        self.assertTrue(combine(c)['errors']);self.assertFalse(combine(c)['strict_eligible'])

    def test_option_inventory_and_relation_tampering_rejected(self):
        with self.assertRaises(ValueError):combine({})
        c=self.checks([.9,.01,.01]);c['substantive']['relation']='contradicts'
        with self.assertRaises(ValueError):combine(c)

    def test_relative_and_absolute_support_can_pass_but_not_approve_service(self):
        r=combine(self.checks([.9,.01,.01]))
        self.assertTrue(r['strict_eligible']);self.assertFalse(r['service_approval']);self.assertFalse(r['calibrated'])
