from pathlib import Path
import tempfile
import unittest

from commentscope.factory import condition_guard as guard
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from experiments.policy_retention_ceiling import ceiling
import test_directed_off_deployment


class PolicyRetentionCeilingTests(unittest.TestCase):
    def plan(self, root, veto_count):
        plan = test_directed_off_deployment.DirectedOffDeploymentTests().parent()
        # These data are synthetic and frozen before evaluation, never a runtime repair.
        for i, row in enumerate(plan['rows']):
            if i < veto_count:
                row['text'] = 'I would work if income arrived.'
                row['claim']['text'] = 'I would work if money arrived.'
                row['request']['data']['SOURCE'] = row['text']
                row['request']['data']['TARGET']['text'] = row['claim']['text']
                row['request_sha256'] = digest(row['request'])
        labels = {rid: 'supported' if i < 19 else 'unsupported' for i, rid in enumerate(plan['evaluation_ids'])}
        write(root/'references.json', {'labels': labels, 'runtime_input': False})
        ref_hash = sha(root/'references.json')
        write(root/'reference-frozen.json', {'sha256': ref_hash})
        plan.update(membership_guard=guard.VERSION, reference_source=str(root),
                    inputs={str(root/'references.json'): ref_hash})
        return plan

    def test_five_blocked_positives_prove_model_independent_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = ceiling(self.plan(Path(tmp), 5))
            self.assertEqual(result['positive_retention_upper'], 14/19)
            self.assertTrue(result['cannot_pass']); self.assertEqual(result['new_model_calls'], 0)
            self.assertFalse(result['quality_gate_passed'])

    def test_passing_upper_bound_is_not_accuracy_or_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = ceiling(self.plan(Path(tmp), 3))
            self.assertEqual(result['positive_retention_upper'], 16/19)
            self.assertFalse(result['cannot_pass']); self.assertFalse(result['quality_gate_passed'])

    def test_unbound_references_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(Path(tmp), 5); plan['inputs'] = {}
            with self.assertRaisesRegex(ValueError, 'not bound'):
                ceiling(plan)
