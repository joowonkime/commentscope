from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.claim_clusters import read_json
from commentscope.storage import write_json_exclusive as write
from experiments.larger_membership_deployment import prepare,MODEL
import test_directed_off_deployment


class LargerMembershipDeploymentTests(unittest.TestCase):
    def parent(self):
        plan=test_directed_off_deployment.DirectedOffDeploymentTests().parent()
        plan.update(models={'baseline':{'name':'8B'}},model={'name':'8B','runtime_sha256':'unchanged'},server={})
        return plan

    def test_full_comparison_preserves_all_semantic_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=self.parent();write(root/'source'/'plan.json',parent)
            for name in ('plan','completed','report'):write(root/'controls'/(name+'.json'),{})
            with patch('experiments.larger_membership_deployment.validate'), \
                 patch('experiments.larger_membership_deployment.verify_controls') as controls, \
                 patch('experiments.larger_membership_deployment.code_hashes',return_value={}):
                prepare(root/'out',root/'source',root/'controls')
            plan=read_json(root/'out'/'plan.json')
            self.assertEqual(plan['rows'],parent['rows'])
            self.assertEqual(plan['evaluation_ids'],parent['evaluation_ids'])
            self.assertEqual(plan['runtime']['reasoning_budget'],256)
            self.assertEqual(plan['runtime']['gpu_layers'],28)
            self.assertEqual(plan['model']['weights_sha256'],MODEL['sha256'])
            self.assertEqual(plan['model']['runtime_sha256'],'unchanged')
            self.assertFalse(plan['plumbing_only']);controls.assert_called_once()
            self.assertEqual(read_json(root/'source'/'plan.json'),parent)

    def test_no_controls_means_only_eight_synthetic_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write(root/'source'/'plan.json',self.parent())
            with patch('experiments.larger_membership_deployment.validate'),patch('experiments.larger_membership_deployment.code_hashes',return_value={}):
                prepare(root/'out',root/'source')
            plan=read_json(root/'out'/'plan.json')
            self.assertEqual(len(plan['rows']),8);self.assertTrue(plan['plumbing_only'])
            self.assertTrue(all(r['request']['max_tokens']==512 for r in plan['rows']))

    def test_wrong_mode_or_duplicate_evaluation_rejected(self):
        for changed in ('mode','ids'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);parent=self.parent()
                if changed=='mode':parent['runtime']['reasoning']='off'
                else:parent['evaluation_ids']=['J0']*100
                write(root/'source'/'plan.json',parent)
                with self.assertRaises(ValueError):prepare(root/'out',root/'source')
                self.assertFalse((root/'out').exists())
