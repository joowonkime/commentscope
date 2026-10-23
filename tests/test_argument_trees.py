from copy import deepcopy
import unittest
from commentscope.factory import argument_trees as at


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'s','text':'Adopt P. Start now because fairness matters.','parent':None}
        self.value={'source_language':'en','status':'complete','positions':[
            {'local_id':'N1','text':'Adopt P.','authorship':'asserted','evidence_segment_ids':['S000'],'grounds':[]},
            {'local_id':'N2','text':'Start P now.','authorship':'asserted','evidence_segment_ids':['S001'],'grounds':[
                {'local_id':'N3','text':'Fairness matters.','relation':'justification','evidence_segment_ids':['S001']}]}], 'additions':[]}

    def test_no_candidate_or_fact_result_can_choose_ground_parent(self):
        req=at.request(self.source)
        self.assertEqual(set(req['data']),{'ORIGINAL','PREVIOUS'})
        record=at.bind(self.source,{'output':self.value});at.validate(record)
        self.assertFalse(record['semantic_approval'])
        self.assertFalse(record['positions'][0]['grounds'])
        self.assertEqual(record['positions'][1]['grounds'][0]['text'],'Fairness matters.')
        changed=deepcopy(record);changed['positions'][0]['grounds']=changed['positions'][1].pop('grounds')
        with self.assertRaises(ValueError):at.validate(changed)

    def test_unknown_duplicate_evidence_authorship_or_relation_rejects_whole_tree(self):
        for modify in (lambda v:v['positions'][1]['grounds'][0].update(local_id='N1'),
                       lambda v:v['positions'][1]['grounds'][0].update(evidence_segment_ids=['PARENT']),
                       lambda v:v['positions'][0].update(authorship='invented'),
                       lambda v:v['positions'][1]['grounds'][0].update(relation='fact_verified')):
            value=deepcopy(self.value);modify(value)
            with self.assertRaises(ValueError):at.bind(self.source,{'output':value})

    def test_supplement_can_add_ground_without_rewriting_prior_position(self):
        first=deepcopy(self.value);first['status']='partial';first['positions'][1]['grounds']=[]
        prior=at.bind(self.source,{'output':first})
        extra={**self.value,'positions':[],'additions':[{'position_local_id':'N2','grounds':self.value['positions'][1]['grounds']}]}
        record=at.bind(self.source,{'output':extra},prior);at.validate(record)
        self.assertEqual(record['positions'][1]['id'],prior['positions'][1]['id'])
        self.assertEqual(len(record['positions'][1]['grounds']),1)
        with self.assertRaises(ValueError):at.request(self.source,record)
        extra['additions'][0]['position_local_id']='N99'
        with self.assertRaises(ValueError):at.bind(self.source,{'output':extra},prior)

    def test_all_nodes_share_capacity_and_ids_across_passes(self):
        value=deepcopy(self.value);value['positions'][1]['grounds']=[
            {**value['positions'][1]['grounds'][0],'local_id':f'N{i}'} for i in range(3,18)]
        with self.assertRaises(ValueError):at.bind(self.source,{'output':value})
        value=deepcopy(self.value);value['status']='partial';prior=at.bind(self.source,{'output':value})
        with self.assertRaises(ValueError):at.bind(self.source,{'output':self.value},prior)

    def test_changed_raw_response_or_source_cannot_rebind(self):
        for modify in (lambda r:r['output'].update(status='unresolved'),lambda r:r['source'].update(text='Changed.')):
            record=at.bind(self.source,{'output':self.value});modify(record)
            with self.assertRaises(ValueError):at.validate(record)
