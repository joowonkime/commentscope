from copy import deepcopy
import math
import unittest
from commentscope.factory import nli_fact_records as n
from commentscope.factory import fact_checks as f
from commentscope.providers.local_nli import MODEL, REVISION
from experiments.grounding_contract_demo import fixture


class NLIFactRecordTests(unittest.TestCase):
    def fixture(self):
        b=fixture(); check=b['checks'][0]
        claim=next(c for c in b['claims'] if c['id']==check['claim_id'])
        packet=f.packet(claim,b['documents'],check['selections'],b['expires_at'])
        model={'name':MODEL,'revision':REVISION,'weights_sha256':'a'*64,'runtime_sha256':'b'*64}
        rows=[]
        prob=math.exp(4)/(math.exp(4)+2)
        for e in packet['evidence']:
            rows.append({'id':e['id'],'errors':[],'raw':[4.,0.,0.],
                         'scores':{'entailment':prob,'neutral':(1-prob)/2,'contradiction':(1-prob)/2},
                         'relation':'supports','input_tokens':40})
        result={'id':claim['id'],'pairs':rows,'state':'supported','supporting_ids':[e['id'] for e in packet['evidence']],'refuting_ids':[]}
        response={'metadata':{'model':MODEL,'revision':REVISION,'threshold':.8,'local_files_only':True,
                             'id2label':{'0':'entailment','1':'neutral','2':'contradiction'}},'results':[result]}
        return packet,model,response

    def test_round_trip_and_no_generative_provenance(self):
        p,m,r=self.fixture(); record=n.records([p],m,r)[0]
        self.assertTrue(n.validate_record(record,p,m))
        self.assertNotIn('raw',record)
        self.assertNotIn('choices',record)

    def test_changed_claim_document_or_case_fails(self):
        p,m,r=self.fixture(); record=n.records([p],m,r)[0]
        for field in ['packet_sha256','case','model']:
            changed=deepcopy(record); changed[field]={}
            with self.subTest(field=field),self.assertRaises(ValueError): n.validate_record(changed,p,m)

    def test_changed_logits_or_aggregation_fails(self):
        p,m,r=self.fixture()
        r['results'][0]['pairs'][0]['raw']=[0.,4.,0.]
        with self.assertRaises(ValueError): n.records([p],m,r)
        p,m,r=self.fixture(); r['results'][0]['state']='refuted'
        with self.assertRaises(ValueError): n.records([p],m,r)

    def test_empty_packet_is_unassessed(self):
        p,m,r=self.fixture(); p['evidence']=[]
        r['results'][0].update(pairs=[],state='unassessed',supporting_ids=[])
        record=n.records([p],m,r)[0]
        self.assertFalse(n.validate_record(record,p,m))

    def test_cannot_forge_llm_as_classifier(self):
        p,m,r=self.fixture(); m['name']='Qwen'
        with self.assertRaises(ValueError): n.records([p],m,r)
