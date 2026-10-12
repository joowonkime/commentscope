import unittest
from commentscope.factory import grounded_factory as g
from commentscope.agents.grounded_inputs import compile_inputs
from experiments.grounding_contract_demo import fixture


class GroundedFactoryTests(unittest.TestCase):
    def setup_data(self):
        f=fixture();claim={'id':'C','text':'The commenter favors safety reviews.','kind':'value',
                          'scope':{'entity':'commenter','time':'','conditions':''},'requires':[]}
        p={'id':'P','claims':{'C':claim},'sources':{'a':'I favor safety reviews.','b':'Reviews should be required.','c':'Safety checks please.'}}
        rows=[{'id':sid,'candidate_id':'P','source_id':sid,'claim':claim,'text':text,'request_sha256':'a'*64} for sid,text in p['sources'].items()]
        return p,rows,{sid:'supported' for sid in p['sources']},f

    def test_compile_has_no_reference_input_and_distinct_votes(self):
        p,rows,verdicts,f=self.setup_data()
        b=g.bundle([p],rows,verdicts,[],{},expires_at=f['expires_at'],model=f['model'])
        result=compile_inputs(b)
        self.assertEqual(result['profiles'][0]['model_core_support_count'],3)
        self.assertFalse(result['quality_gate_passed'])

    def test_factual_dependency_not_removed(self):
        p,rows,verdicts,f=self.setup_data()
        p['claims']['C']['requires']=['F1']
        p['claims']['F1']={'id':'F1','text':'Reviews prevent all accidents.','kind':'fact',
                          'scope':{'entity':'reviews','time':'','conditions':''},'requires':[]}
        details=g.detail_requests([p],rows,verdicts)
        self.assertEqual(len(details),3)
        b=g.bundle([p],rows,verdicts,details,{r['id']:'supported' for r in details},expires_at=f['expires_at'],model=f['model'])
        self.assertEqual(b['claims'][0]['requires'],['P:F1'])
        self.assertEqual(compile_inputs(b)['profiles'],[])

    def test_no_reason_inference_below_three(self):
        p,rows,v,f=self.setup_data();v['a']='unsupported'
        self.assertEqual(g.detail_requests([p],rows,v),[])
