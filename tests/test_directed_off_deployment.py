from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory import membership_policy
from commentscope.factory.claim_clusters import read_json
from commentscope.storage import write_json_exclusive as write
from experiments.directed_off_deployment import prepare,control_rows
import test_membership_policy


class DirectedOffDeploymentTests(unittest.TestCase):
    def parent(self):
        row=test_membership_policy.MembershipPolicyTests().row()
        return {'rows':[{**deepcopy(row),'id':f'J{i}'} for i in range(100)],'inputs':{},
                'evaluation_ids':[f'J{i}' for i in range(100)],
                'directionality_variant':'asymmetric-entailment-clarification-0.1',
                'runtime':{'reasoning':'on','context':4096,'gpu_layers':'all','reasoning_budget':256},
                'budget':{'reasoning_tokens':256}}

    def test_controls_and_non_thinking_settings_are_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=self.parent();write(root/'source'/'plan.json',parent)
            with patch('experiments.directed_off_deployment.validate'),patch('experiments.directed_off_deployment.code_hashes',return_value={}):
                prepare(root/'out',root/'source')
            plan=read_json(root/'out'/'plan.json')
            self.assertTrue(plan['plumbing_only']);self.assertEqual(len(plan['rows']),8)
            self.assertEqual(plan['runtime']['context'],4096)
            self.assertEqual(plan['runtime']['reasoning'],'off')
            self.assertEqual(plan['runtime']['reasoning_budget'],0)
            self.assertTrue(all(r['request']['max_tokens']==180 for r in plan['rows']))
            self.assertTrue(all(r['request']['system']==parent['rows'][0]['request']['system'] for r in plan['rows']))
            self.assertNotIn('expected',plan['rows'][0]['request']['data'])
            self.assertEqual(read_json(root/'source'/'plan.json'),parent)

    def test_full_trial_requires_controls_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write(root/'source'/'plan.json',self.parent())
            with patch('experiments.directed_off_deployment.verify_controls',side_effect=ValueError('Controls failed')):
                with self.assertRaisesRegex(ValueError,'Controls failed'):
                    prepare(root/'out',root/'source',root/'controls')
            self.assertFalse((root/'out').exists())

    def test_binary_control_balance_and_no_label_leak(self):
        policy=membership_policy.from_rows(self.parent()['rows']);policy['max_tokens']=180
        rows=control_rows(policy)
        self.assertEqual(sum(r['expected']=='supported' for r in rows),4)
        self.assertEqual(len({r['id'] for r in rows}),8)
        self.assertTrue(all(set(r['request']['data'])=={'SOURCE','TARGET'} for r in rows))
