from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import Mock, patch

from experiments import common_position_probe as probe
from tests import test_candidate_completion_pipeline as existing


class CommonRunner(existing.SyntheticRunner):
    wrong_core=False
    def call(self,stage,req,**kwargs):
        if stage!='common-position':return super().call(stage,req,**kwargs)
        self.seq+=1
        core=req['data']['RETRIEVAL_HINT']['text']
        witnesses=[{'source_id':sid,'quote':core,'qualifications':[]}
                   for sid,text in req['data']['ORIGINAL_SOURCES'].items() if core in text]
        if self.wrong_core:core='Safety reviews should be required and voluntary.'
        return {'errors':[],'raw':'synthetic','output':{'status':'proposed','core':core,
            'scope':{'entity':'general','time':'','conditions':''},'witnesses':witnesses}}


class CommonPositionProbeTests(unittest.TestCase):
    def run_component(self,tmp,wrong=False):
        root=Path(tmp); source=root/'source'; directory=root/'common'
        existing.CandidateCompletionPipelineTests().run_synthetic(source,False)
        probe.prepare(directory,source)
        plan=probe.read_json(directory/'plan.json')
        self.assertEqual(plan['tasks'],probe.read_json(source/'candidate-queue.json'))
        self.assertFalse(plan['fresh_analysis']);self.assertEqual(plan['limits']['analysis_seconds'],2400)
        budget=Mock();budget.summary.return_value={'remaining_seconds':9000,'charged_seconds':0}
        with patch.object(probe,'validate',return_value=source),patch.object(probe,'InferenceBudget',return_value=budget), \
             patch.object(probe.pipeline,'owned_server'),patch.object(probe.pipeline,'CompletionRunner',CommonRunner), \
             patch.object(CommonRunner,'wrong_core',wrong):
            probe.execute(directory)
        return probe.read_json(directory/'completed.json'),directory

    def test_new_proposals_reach_unchanged_full_path_without_quality_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            r,d=self.run_component(tmp)
            self.assertEqual(r['screened_inputs'],2);self.assertEqual(r['qualified_agents'],0)
            self.assertFalse(r['fresh_analysis']);self.assertFalse(r['quality_gate_passed'])
            self.assertEqual(len(r['proposal_outcomes']),2)
            for p in probe.read_json(d/'common-queue.json'):
                self.assertEqual(len(p['sources']),6) # all opposing nominees retained
            self.assertTrue(all(o['state']=='screened_input' for o in r['outcomes']))

    def test_structurally_valid_witnesses_cannot_bypass_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            r,d=self.run_component(tmp,True)
            self.assertEqual(r['screened_inputs'],0)
            self.assertTrue(all(o['state']=='insufficient_core_support' for o in r['outcomes']))

    def test_rejects_fresh_label_and_changed_budget(self):
        limits=deepcopy(probe.pipeline.LIMITS);limits['analysis_seconds']=probe.SECONDS
        plan={'artifact_kind':probe.VERSION,'limits':limits,'common_position_contract':probe.common.VERSION,
              'generation_seconds':probe.GENERATION_SECONDS,'generation_tokens':probe.common.TOKENS,
              'fresh_analysis':False,'runtime_reference_labels':False}
        for changed in ({'fresh_analysis':True},{'generation_seconds':1800},{'runtime_reference_labels':True}):
            with self.assertRaises(ValueError):probe.validate({**plan,**changed})


if __name__=='__main__':unittest.main()
