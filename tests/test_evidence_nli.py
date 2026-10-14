import unittest
from commentscope.providers.evidence_nli import aggregate, unanimous


class EvidenceNLITests(unittest.TestCase):
    def test_four_way_aggregation(self):
        for relations, expected in [(['supports'], 'supported'), (['contradicts'], 'refuted'),
                                    (['not_established', 'unclear'], 'insufficient'),
                                    (['supports', 'contradicts'], 'conflicting')]:
            rows = [{'id': str(i), 'relation': relation, 'errors': []} for i, relation in enumerate(relations)]
            self.assertEqual(aggregate(rows)['state'], expected)

    def test_error_and_empty_are_not_successful_rejections(self):
        self.assertEqual(aggregate([])['state'], 'unassessed')
        self.assertEqual(aggregate([{'id': 'e', 'errors': ['overflow']}])['state'], 'error')

    def test_disagreement_never_supports(self):
        for state in ['supported', 'refuted', 'conflicting', 'insufficient']:
            self.assertEqual(unanimous(state, state), state)
            for other in ['supported', 'refuted', 'conflicting', 'insufficient']:
                if other != state: self.assertEqual(unanimous(state, other), 'insufficient')
        self.assertEqual(unanimous('supported', 'error'), 'error')


if __name__ == '__main__': unittest.main()
