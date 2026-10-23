from copy import deepcopy
import unittest
from commentscope.factory import argument_content as ac, minimal_claims as mc
from test_minimal_factory import extraction


class ContentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'s','text':'Adopt P. Fairness matters.','parent':None}
        self.value={'source_language':'en','status':'complete','units':[
            {'local_id':'U1','text':'Adopt P.','evidence_segment_ids':['S000']},
            {'local_id':'U2','text':'Fairness matters.','evidence_segment_ids':['S001']}]}
        self.record=ac.bind_extraction(self.source,{'output':self.value})
        self.candidate=mc.candidates(extraction([self.source],{'s':['Adopt P.']}))[0]

    def test_extraction_cannot_see_candidate_or_generate_type_role_scope(self):
        req=ac.extract_request(self.source)
        self.assertEqual(set(req['data']),{'ORIGINAL','PREVIOUS'})
        unit=req['schema']['properties']['units']['items']['properties']
        self.assertEqual(set(unit),{'local_id','text','evidence_segment_ids'})
        self.assertNotIn('POSITION',str(req['data']))

    def test_address_and_duplicate_errors_reject_complete_response(self):
        for mutation in (lambda v:v['units'][1].update(local_id='U1'),
                         lambda v:v['units'][1].update(evidence_segment_ids=['S999']),
                         lambda v:v['units'][1].update(text='x'*601)):
            value=deepcopy(self.value);mutation(value)
            with self.assertRaises(ValueError):ac.bind_extraction(self.source,{'output':value})
        changed=deepcopy(self.record);changed['source']['text']='Changed.'
        with self.assertRaises(ValueError):ac.validate_extraction(changed)

    def test_partial_supplement_preserves_prior_content_exactly_once(self):
        value=deepcopy(self.value);value['status']='partial';value['units']=value['units'][:1]
        first=ac.bind_extraction(self.source,{'output':value})
        final=ac.bind_extraction(self.source,{'output':{**self.value,'units':self.value['units'][1:]}},first)
        self.assertEqual(final['units'][0],first['units'][0]);ac.validate_extraction(final)
        with self.assertRaises(ValueError):ac.extract_request(self.source,final)
        with self.assertRaises(ValueError):ac.bind_extraction(self.source,{'output':self.value},first)

    def test_typing_sees_only_one_frozen_assertion(self):
        unit=self.record['units'][1];req=ac.type_request(self.record,unit)
        self.assertEqual(req['data'],{'TARGET_ASSERTION':'Fairness matters.'})
        typed=ac.bind_type(self.record,unit,{'output':{'kind':'value','subject_matter':'fairness','explicit_time_phrase_or_empty':'','explicit_condition_phrase_or_empty':''}})
        ac.validate_type(self.record,unit,typed)
        typed['output']['kind']='fact'
        with self.assertRaises(ValueError):ac.validate_type(self.record,unit,typed)

    def test_role_is_single_pair_and_cannot_rewrite_unit(self):
        unit=self.record['units'][0];req=ac.role_request(self.record,unit,self.candidate)
        self.assertEqual(req['data']['TARGET_UNIT_TO_CLASSIFY'],'Adopt P.')
        self.assertEqual(set(req['schema']['properties']),{'role','evidence_segment_ids'})
        role=ac.bind_role(self.record,unit,self.candidate,{'output':{'role':'core_restatement','evidence_segment_ids':['S000']}})
        ac.validate_role(self.record,unit,self.candidate,role)
        role['candidate_sha256']='changed'
        with self.assertRaises(ValueError):ac.validate_role(self.record,unit,self.candidate,role)

    def test_unbound_unit_or_parent_evidence_rejected(self):
        changed=deepcopy(self.record['units'][0]);changed['text']='Invented reason.'
        with self.assertRaises(ValueError):ac.type_request(self.record,changed)
        with self.assertRaises(ValueError):ac.bind_role(self.record,self.record['units'][0],self.candidate,
            {'output':{'role':'reason','evidence_segment_ids':['PARENT']}})


if __name__=='__main__':unittest.main()
