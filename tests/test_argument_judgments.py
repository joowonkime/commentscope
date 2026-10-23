from copy import deepcopy
import unittest
from commentscope.factory import argument_content as ac, argument_judgments as aj
from test_argument_content import ContentBoundaryTests


class JudgmentTests(unittest.TestCase):
    def setUp(self):
        f=ContentBoundaryTests();f.setUp()
        self.record=f.record;self.unit=f.record['units'][1];self.candidate=f.candidate

    def test_explanation_does_not_change_target_or_prove_semantics(self):
        req=aj.role_request(self.record,self.unit,self.candidate)
        self.assertEqual(list(req['schema']['properties'])[0],'explanation')
        self.assertEqual(req['data']['TARGET'],'Fairness matters.')
        result=aj.bind(self.record,self.unit,{'output':{'explanation':'Offers fairness as a reason.',
            'role':'reason','evidence_segment_ids':['S001']}},self.candidate)
        self.assertFalse(result['semantic_approval'])
        aj.validate(self.record,self.unit,result,self.candidate)
        result['unit_id']='changed'
        with self.assertRaises(ValueError):aj.validate(self.record,self.unit,result,self.candidate)

    def test_type_sees_only_target_and_cannot_silently_change_kind(self):
        req=aj.type_request(self.record,self.unit)
        self.assertEqual(req['data'],{'TARGET':self.unit['text']})
        value={'explanation':'A value without explicit scope restrictions.','kind':'value',
            'subject_matter':'fairness','explicit_time_phrase_or_empty':'','explicit_condition_phrase_or_empty':''}
        result=aj.bind(self.record,self.unit,{'output':value});aj.validate(self.record,self.unit,result)
        changed=deepcopy(result);changed['output']['kind']='fact'
        with self.assertRaises(ValueError):aj.validate(self.record,self.unit,changed)

    def test_unknown_evidence_role_and_failed_output_rejected(self):
        value={'explanation':'Reason.','role':'reason','evidence_segment_ids':['S001']}
        for change in ({'role':'invented'},{'evidence_segment_ids':['PARENT']},{'explanation':''}):
            with self.assertRaises(ValueError):aj.bind(self.record,self.unit,{'output':{**value,**change}},self.candidate)
        with self.assertRaises(ValueError):aj.bind(self.record,self.unit,{'errors':['timeout'],'output':value},self.candidate)
