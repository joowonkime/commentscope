from copy import deepcopy
import unittest

from commentscope.factory import fact_checks as facts
from experiments.fact_deployment_probe import deployment_plan
from experiments.grounding_contract_demo import fixture


class FactDeploymentTests(unittest.TestCase):
    def test_deployment_changes_no_claim_prompt_evidence_or_expectation(self):
        bundle = fixture()
        claim = bundle['claims'][1]
        packet = facts.packet(claim, bundle['documents'], bundle['checks'][0]['selections'], bundle['expires_at'])
        original = {'server': {'sha256': 'a'*64}, 'model': bundle['model'],
                    'models': {'baseline': {'name': 'old'}}, 'runtime': {'context': 8192},
                    'rows': [{'packet': packet, 'expected': 'supported', 'request_sha256': 'old'}],
                    'criteria': {'unsupported_false_support_max': 0}}
        saved = deepcopy(original)
        candidate = {'name': 'candidate', 'revision': 'revision', 'sha256': 'b'*64}
        result = deployment_plan(original, candidate)
        self.assertEqual(original, saved)
        self.assertEqual(result['runtime'], original['runtime'])
        self.assertEqual(result['criteria'], original['criteria'])
        self.assertEqual(result['rows'][0]['expected'], 'supported')
        self.assertEqual(facts.invocation(packet, result['model']), facts.invocation(packet, original['model']))
        self.assertEqual(result['rows'][0]['packet'], packet)
        self.assertNotEqual(result['model'], original['model'])


if __name__ == '__main__': unittest.main()
