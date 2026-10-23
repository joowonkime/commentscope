from copy import deepcopy
import unittest
from commentscope.factory import proposition_requirements as pr, proposition_fidelity as pf


class QualificationTests(unittest.TestCase):
    source={'id':'s','text':'Adopt P because fairness matters.','parent':None}
    text='Adopt P because fairness matters.'
    def shape(self):
        pid=next(p['id'] for p in pf.phrases(self.text) if p['text']=='because fairness matters.')
        return pr.bind_shape(self.text,{'output':{'status':'complete','qualifications':[{'role':'reason','phrase_id':pid}]}})
    def test_candidate_only_inventory_cannot_contain_source_text(self):
        req=pr.shape_request(self.text)
        self.assertEqual(set(req['data']),{'PROPOSITION','PHRASES'})
        self.assertNotIn('source_id',str(req['data']))
        shape=self.shape();self.assertEqual(shape['details'][0]['phrase']['text'],'because fairness matters.')
        detail=pr.detail_request(self.source,shape,shape['details'][0])
        self.assertNotIn('CANDIDATE_CONTEXT_ONLY',detail['data'])
        self.assertEqual(detail['data']['DETAIL']['text'],'because fairness matters.')

    def test_nested_duplicate_addresses_keep_full_text_and_raw_output(self):
        value={'status':'complete','qualifications':[{'role':'reason','phrase_id':p['id']}
            for p in pf.phrases(self.text) if p['text'] in ('because fairness matters.','fairness matters.','matters.')]}
        shape=pr.bind_shape(self.text,{'output':value})
        self.assertEqual(len(shape['details']),1)
        self.assertEqual(shape['details'][0]['phrase']['text'],'because fairness matters.')
        self.assertEqual(shape['output'],value)
        self.assertEqual(len(shape['subsumed_detail_ids']),2)
    def test_missing_unknown_or_duplicate_check_never_approves(self):
        shape=self.shape();detail=shape['details'][0]
        self.assertFalse(pr.complete(self.source,shape,[]))
        for verdict in ('absent','uncertain','present'):
            check=pr.bind_detail(self.source,shape,detail,{'output':{'verdict':verdict,'source_segment_ids':[]}})
            self.assertFalse(pr.complete(self.source,shape,[check]))
        check=pr.bind_detail(self.source,shape,detail,{'output':{'verdict':'present','source_segment_ids':['S000']}})
        self.assertTrue(pr.complete(self.source,shape,[check]))
        with self.assertRaises(ValueError):pr.complete(self.source,shape,[check,check])
        changed=deepcopy(check);changed['source']['text']='Other.'
        with self.assertRaises(ValueError):pr.complete(self.source,shape,[changed])
    def test_uncertain_inventory_is_not_an_empty_approved_inventory(self):
        shape=pr.bind_shape('Adopt P.',{'output':{'status':'uncertain','qualifications':[]}})
        self.assertFalse(pr.complete(self.source,shape,[]))
        shape=pr.bind_shape('Adopt P.',{'output':{'status':'complete','qualifications':[]}})
        self.assertTrue(pr.complete(self.source,shape,[]))
        self.assertFalse(shape['semantic_approval'])
    def test_inventory_mutation_and_unbound_phrase_fail(self):
        shape=self.shape();shape['details'][0]['phrase']['text']='Invented reason.'
        with self.assertRaises(ValueError):pr.validate_shape(shape)
        with self.assertRaises(ValueError):pr.bind_shape(self.text,{'output':{'status':'complete','qualifications':[{'role':'reason','phrase_id':'P999'}]}})


if __name__=='__main__':unittest.main()
