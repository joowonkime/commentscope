"""Review-before-count invariants; toy compile is not real product validation."""
from copy import deepcopy
import json,unittest
from commentscope.factory import source_closed_policy as closed,reviewed_source_admission as gate
from commentscope.factory.automatic_contract import digest
from commentscope.providers import local_nli
from experiments.grounding_contract_demo import MODEL
from test_source_closed_policy import SourceClosedPolicyTests,ClosingRunner
from test_source_entailment import nli_response

class ReviewedAdmissionTests(unittest.TestCase):
    setUp=SourceClosedPolicyTests.setUp

    def process(self,verdicts):
        saved={};seen=[];runner=ClosingRunner()
        def save(name,value):
            if name in saved:self.assertEqual(saved[name],value)
            saved[name]=deepcopy(value)
        def reviewer(accepted,status):
            prefix=accepted['candidate_id']+'/'+accepted['source_id']
            artifacts={k:saved[k+'/'+prefix] for k in gate.KINDS}
            packet=gate.packet(accepted,artifacts,{k+'/'+prefix:digest(v) for k,v in artifacts.items()})
            verdict=verdicts[min(len(seen),len(verdicts)-1)];seen.append(accepted['source_id'])
            review=None if verdict is None else {k:deepcopy(packet[k]) for k in (
                'source_id','candidate_id','source_sha256','draft_sha256','files_sha256','runtime_input','human_approved')}
            if review is not None:review.update(verdict=verdict,notes='review-witness-never-model-input')
            return packet,review
        out=closed.process(self.snapshot,self.record,[(self.req,self.res)],runner,
            lambda req:{'request_sha256':digest(req),'fits':True},nli_response,
            model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION},save=save,
            review_source=reviewer,require_direct_review=True)
        return out,seen,runner

    def test_failed_source_never_fills_slot_and_order_continues_to_three_passes(self):
        out,seen,runner=self.process(['fail','pass'])
        self.assertEqual(len(seen),4);self.assertEqual(len(out['accepted']),3)
        self.assertNotIn(seen[0],{a['source_id'] for a in out['accepted']})
        self.assertEqual([r['verdict'] for r in out['direct_source_reviews']],['fail','pass','pass','pass'])
        self.assertEqual(out['agent_inputs']['compiled']['profiles'][0]['model_core_support_count'],3)
        self.assertTrue(out['review_before_count']);self.assertFalse(out['quality_gate_passed'])
        self.assertNotIn('review-witness-never-model-input',json.dumps(runner.calls))

    def test_unreviewed_or_uncertain_sources_count_zero(self):
        for verdict in (None,'uncertain'):
            out,seen,_=self.process([verdict])
            self.assertEqual(len(seen),4);self.assertFalse(out['accepted'])
            self.assertFalse(out['agent_inputs']['compiled']['profiles'])

    def test_required_gate_cannot_be_enabled_without_reviewer(self):
        with self.assertRaises(ValueError):
            closed.process(self.snapshot,self.record,[(self.req,self.res)],ClosingRunner(),
                lambda req:{'request_sha256':digest(req),'fits':True},nli_response,
                model={**MODEL,'name':local_nli.MODEL,'revision':local_nli.REVISION},require_direct_review=True)

    def test_review_for_another_source_draft_or_files_is_rejected(self):
        accepted={'source_id':'own1','candidate_id':'core1','draft_sha256':'a'*64}
        packet={'artifact_kind':gate.VERSION+'-packet','accepted_sha256':digest(accepted),
            'source_id':'own1','candidate_id':'core1','source_sha256':'b'*64,'draft_sha256':'a'*64,
            'files_sha256':{str(i):'c'*64 for i in range(4)},'runtime_input':False,'human_approved':False}
        base={k:deepcopy(packet[k]) for k in ('source_id','candidate_id','source_sha256','draft_sha256','files_sha256','runtime_input','human_approved')}
        base['verdict']='pass'
        self.assertTrue(gate.bind(accepted,packet,base)['countable'])
        for key,value in (('source_id','other'),('draft_sha256','d'*64),('files_sha256',{}),('runtime_input',True),('human_approved',True)):
            with self.subTest(key=key),self.assertRaises(ValueError):gate.bind(accepted,packet,{**base,key:value})

if __name__=='__main__':unittest.main()
