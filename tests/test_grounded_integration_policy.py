from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory import membership_policy
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json
from commentscope.factory.scoped_discovery import judge_request
from commentscope.storage import write_json_exclusive as write
from experiments.directed_membership_probe import directed
from experiments.grounded_integration import prepare, type_claims


class GroundedIntegrationPolicyTests(unittest.TestCase):
    def plan(self):
        claim={'id':'C','text':'Safety reviews should be required.','kind':'fact',
               'scope':{'entity':'','time':'','conditions':''},'requires':[]}
        text='Safety reviews should be required. Caution is important.'
        sources={f's{i}':text for i in range(3)}
        proposal={'id':'C1','claims':{'C':claim},'sources':sources}
        rows=[]
        for sid in sources:
            req=directed(judge_request(text,claim)); req['max_tokens']=512
            rows.append({'id':sid,'candidate_id':'C1','source_id':sid,'text':text,
                         'claim':claim,'request':req,'request_sha256':digest(req)})
        return {'artifact_kind':'grounded-integration-0.2',
                'membership_policy':membership_policy.from_rows(rows),
                'rows':[{'id':'C1','proposal':proposal,'members':sources}],
                'core_rows':rows,'core_verdicts':{sid:'supported' for sid in sources}}

    def typed(self,plan):
        out=deepcopy(plan['rows'][0]['proposal']);out['claims']['C']['kind']='value'
        out['claims']['R1']={**deepcopy(out['claims']['C']),'id':'R1','text':'Caution is important.'}
        return out

    def test_typing_and_details_keep_evaluated_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=self.plan();write(root/'plan.json',plan)
            records={'C1':{'result':{'errors':[],'output':{}}}}
            with patch('experiments.grounded_integration.run_calls',return_value=records), \
                 patch('experiments.grounded_integration.typing.apply',return_value=self.typed(plan)):
                type_claims(root)
            output=read_json(root/'typed.json')
            self.assertEqual(len(output['detail_rows']),3)
            for row in output['core_rows']+output['detail_rows']:
                self.assertEqual(row['request']['system'],plan['membership_policy']['system'])
                self.assertEqual(row['request']['max_tokens'],512)
                self.assertEqual(row['request_sha256'],digest(row['request']))
            self.assertEqual(read_json(root/'plan.json'),plan)

    def test_typing_cannot_change_core_meaning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=self.plan();write(root/'plan.json',plan)
            typed=self.typed(plan);typed['claims']['C']['text']='Safety reviews should not be required.'
            with patch('experiments.grounded_integration.run_calls',return_value={'C1':{'result':{'errors':[],'output':{}}}}), \
                 patch('experiments.grounded_integration.typing.apply',return_value=typed):
                with self.assertRaisesRegex(ValueError,'membership target'):type_claims(root)
            self.assertFalse((root/'typed.json').exists())

    def test_policy_or_legacy_plan_rejected_before_any_call(self):
        for change in ('policy','version'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);plan=self.plan()
                if change=='policy':plan['membership_policy']['max_tokens']=180
                else:plan['artifact_kind']='grounded-integration-0.1'
                write(root/'plan.json',plan)
                with patch('experiments.grounded_integration.run_calls') as calls:
                    with self.assertRaises(ValueError):type_claims(root)
                    calls.assert_not_called()

    def test_incomplete_or_failed_gate_cannot_prepare(self):
        for passed,complete in [(False,True),(True,False)]:
            with self.subTest(passed=passed,complete=complete),tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'output'
                with patch('experiments.grounded_integration.checkpoint',return_value={
                        'development_gate_passed':passed,'all_relations_complete':complete}):
                    with self.assertRaisesRegex(ValueError,'Complete source fidelity gate'):
                        prepare(Path(tmp)/'source',out)
                self.assertFalse(out.exists())
