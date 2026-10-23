import unittest
from commentscope.factory import perspective_typing as t


class TypingTests(unittest.TestCase):
    def fixture(self):
        return {'id':'P','claims':{'C':{'id':'C','text':'The commenter would continue working with UBI.',
                'kind':'fact','scope':{'entity':'','time':'','conditions':''},'requires':[]}},
                'sources':{'s':'I would still work. I enjoy my job.'}}

    def test_core_never_rewritten_and_prediction_not_fact(self):
        p=self.fixture();out=t.apply(p,{'status':'classified','kind':'future_expectation','details':[],'required_fact_ids':[]},p['sources'])
        self.assertEqual(out['claims']['C']['text'],p['claims']['C']['text'])
        self.assertEqual(out['claims']['C']['kind'],'prediction')

    def test_required_fact_kept_not_invented(self):
        p=self.fixture();v={'status':'classified','kind':'future_expectation','details':[{'id':'D1','kind':'empirical_description','source_id':'s','quote':'I enjoy my job.'}],'required_fact_ids':['D1']}
        out=t.apply(p,v,p['sources']);self.assertEqual(out['claims']['C']['requires'],['R1'])
        self.assertEqual(out['claims']['R1']['text'],'I enjoy my job.')
        v['details'][0]['source_id']='outsider'
        with self.assertRaises(ValueError):t.apply(p,v,p['sources'])

    def test_unknown_kind_or_dropped_dependency_rejected(self):
        p=self.fixture()
        with self.assertRaises(ValueError):t.apply(p,{'status':'classified','kind':'normative_preference','details':[],'required_fact_ids':['D1']},p['sources'])
        self.assertIsNone(t.apply(p,{'status':'defer','reason':'essential_grounds_overflow'},p['sources']))
