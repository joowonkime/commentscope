from copy import deepcopy
import unittest
from commentscope.factory import policy_attitude as attitude


class PolicyAttitudeTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'a','text':'Policy P could be good if C, but could be bad if D.',
            'parent':{'id':'parent','text':'A parent says P is always good.'}}
        self.value={'evaluation':'mixed','target':'topic_policy','authorship':'own_evaluation',
            'favorable_segment_ids':['S000'],'unfavorable_segment_ids':['S000'],
            'favorable_force':'possible_or_conditional','unfavorable_force':'possible_or_conditional'}

    def test_no_desired_candidate_supplied_and_conditions_remain_in_own_evidence(self):
        request=attitude.request(self.source,'Policy P')
        self.assertEqual(set(request['data']),{'ORIGINAL','TOPIC_POLICY'})
        bound=attitude.bind(self.source,'Policy P',{'output':self.value})
        self.assertEqual(bound['passed_polarities'],['favorable','unfavorable'])
        self.assertEqual(bound['evidence']['favorable'][0]['text'],self.source['text'])
        self.assertFalse(bound['semantic_approval'])

    def test_other_target_voice_or_missing_own_evidence_cannot_approve(self):
        for changes in [{'target':'other_target'},{'authorship':'quoted_or_other_voice'},
                        {'evaluation':'not_stated'},{'favorable_segment_ids':[],'unfavorable_segment_ids':[]}]:
            value={**deepcopy(self.value),**changes}
            self.assertFalse(attitude.bind(self.source,'Policy P',{'output':value})['passed_polarities'])

    def test_proof_and_evidence_addresses_are_fixed(self):
        bound=attitude.bind(self.source,'Policy P',{'output':self.value});bound['source']['text']='Changed.'
        with self.assertRaises(ValueError):attitude.validate(bound)
        value={**self.value,'favorable_segment_ids':['PARENT']}
        with self.assertRaises(ValueError):attitude.bind(self.source,'Policy P',{'output':value})
