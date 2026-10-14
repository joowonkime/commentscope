from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from experiments import source_span_product_probe as probe
from tests import test_candidate_completion_pipeline as existing


class SpanRunner(existing.SyntheticRunner):
    reject_membership=False
    def call(self,stage,req,**kwargs):
        if stage=='source-span-selection':
            self.seq+=1
            hint=req['data']['RETRIEVAL_HINT']['text']
            sources=req['data']['SOURCES']
            nominees=[sid for sid,parts in sources.items() if hint in ''.join(r['text'] for r in parts)]
            row=next(r for r in sources[nominees[0]] if r['text'].strip()==hint)
            return {'errors':[],'output':{'status':'selected','span_id':row['id'],'nominated_source_ids':nominees}}
        if self.reject_membership and stage.startswith('core-') and stage!='core-kind':
            self.seq+=1
            return {'errors':[],'output':{'verdict':'unsupported','reason':'Synthetic rejection.'}}
        return super().call(stage,req,**kwargs)


class SourceSpanProductProbeTests(unittest.TestCase):
    def run_component(self,tmp,reject=False):
        root=Path(tmp);source=root/'source';directory=root/'span'
        existing.CandidateCompletionPipelineTests().run_synthetic(source,False)
        probe.prepare(directory,source)
        plan=probe.read_json(directory/'plan.json')
        self.assertEqual(plan['tasks'],probe.read_json(source/'candidate-queue.json'))
        budget=Mock();budget.summary.return_value={'remaining_seconds':9000,'charged_seconds':0}
        with patch.object(probe,'validate',return_value=source),patch.object(probe,'InferenceBudget',return_value=budget), \
             patch.object(probe.pipeline,'owned_server'),patch.object(probe.pipeline,'CompletionRunner',SpanRunner), \
             patch.object(SpanRunner,'reject_membership',reject):
            probe.execute(directory)
        return probe.read_json(directory/'completed.json'),directory

    def test_immutable_selection_reaches_full_pipeline_without_quality_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,directory=self.run_component(tmp)
            self.assertEqual(report['screened_inputs'],2);self.assertEqual(report['qualified_agents'],0)
            self.assertFalse(report['quality_gate_passed']);self.assertFalse(report['fresh_analysis'])
            self.assertEqual(len(report['selection_outcomes']),2)
            for p in probe.read_json(directory/'selected-queue.json'):
                self.assertEqual(len(p['sources']),6)
                self.assertFalse(p['semantic_approval'])
                self.assertEqual(p['claims']['C']['text'],p['selected_spans'][0]['text'])

    def test_original_author_and_nominations_cannot_bypass_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,directory=self.run_component(tmp,True)
            self.assertEqual(report['screened_inputs'],0)
            self.assertTrue(all(o['state']=='insufficient_core_support' for o in report['outcomes']))

    def test_rejects_changed_frozen_policy(self):
        limits=deepcopy(probe.pipeline.LIMITS);limits['analysis_seconds']=probe.SECONDS
        plan={'artifact_kind':probe.VERSION,'limits':limits,'source_span_contract':probe.selection.VERSION,
              'span_limits':probe.selection.LIMITS,'selection_seconds':probe.SELECTION_SECONDS,
              'selection_tokens':probe.selection.TOKENS,'fresh_analysis':False,'runtime_reference_labels':False}
        for mutation in ({'fresh_analysis':True},{'selection_seconds':1800},{'runtime_reference_labels':True}):
            with self.assertRaises(ValueError):probe.validate({**plan,**mutation})


if __name__=='__main__':unittest.main()
