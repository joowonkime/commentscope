from copy import deepcopy
import unittest
from unittest.mock import patch

from experiments import raw_candidates_probe as p
from commentscope.factory import raw_candidates as r
from commentscope.factory.automatic_contract import digest


class RawProbeTests(unittest.TestCase):
    def plan(self):
        return p.make_plan('tests/fixtures/synthetic-snapshot.json', 64)

    def test_plan_is_deterministic_and_revalidates(self):
        plan=self.plan()
        self.assertEqual(plan,self.plan())
        p.check(plan)
        self.assertFalse(plan['quality_gate_passed'])
        self.assertEqual(plan['reference_pairs_evaluation_only'],[])

    def test_expiry_metadata_cannot_be_relabelled(self):
        plan=self.plan();plan['expires_at']='2099-01-01T00:00:00Z'
        with self.assertRaises(ValueError):p.check(plan)

    def test_cache_bound_to_exact_text_revision_and_vector_result(self):
        contract=p.vector_contract(self.plan())
        vectors=[[1.,0.] for _ in contract['texts']]
        stored={'input':contract,'vectors':vectors,'vectors_sha256':digest(vectors)}
        p.validate_vectors(stored,contract)
        for change in ['text','revision','vector']:
            bad=deepcopy(stored)
            if change=='text':bad['input']['texts'][0]+='changed'
            elif change=='revision':bad['input']['embedding']['revision']='different'
            else:bad['vectors'][0]=[0.,1.]
            with self.assertRaises(ValueError):p.validate_vectors(bad,contract)

    def test_retrieval_and_queue_are_separate_and_missing_sources_stay_denominator(self):
        bundle={'candidates':{'a':[{'source_id':'b'}],'b':[]},'queue':{'pairs':[]}}
        pairs=[{'pair_id':'one','source_ids':['a','b']},{'pair_id':'two','source_ids':['a','missing']}]
        result=p.evaluate(bundle,pairs)
        self.assertEqual((result['known_pairs'],result['source_exposed'],result['queued_pairs']),(2,1,0))
        self.assertFalse(result['records'][1]['both_sources_preserved'])

    def test_no_model_call_in_plan_or_cached_vector_validation(self):
        with patch.object(p,'embed',side_effect=AssertionError('Unexpected inference')):
            plan=self.plan();p.check(plan)
            contract=p.vector_contract(plan);vectors=[[1.] for _ in contract['texts']]
            p.validate_vectors({'input':contract,'vectors':vectors,'vectors_sha256':digest(vectors)},contract)

    def test_report_escapes_untrusted_source_text(self):
        plan=self.plan();value=plan['registry']
        value['sources'][0]['text']='<script>alert(1)</script>'
        value['sources'][0]['source_digest']=digest(value['sources'][0]['text'])
        bundle=r.build(value,[[1.] for s in value['sources'] if s['indexable']])
        page=p.render({'registry':value,'bundle':bundle,'evaluation':{},'measurements':{}})
        self.assertNotIn('<script>',page)
        self.assertIn('&lt;script&gt;',page)


if __name__=='__main__':unittest.main()
