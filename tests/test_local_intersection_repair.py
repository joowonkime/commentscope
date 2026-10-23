"""Neighborhood provenance/anti-confirmation mechanics, not model quality."""
from copy import deepcopy
import unittest
from commentscope.factory import local_intersection_repair as repair,shared_claims
from commentscope.factory.automatic_contract import digest


class LocalIntersectionRepairTests(unittest.TestCase):
    def setUp(self):
        self.sources=[{'id':str(i),'text':text,'parent':None} for i,text in enumerate([
            'A thousand monthly would not make me quit.','Twelve thousand yearly would not make me quit.',
            'I dislike paid work.','An unrelated false nomination.'])]
        record=shared_claims.bind(self.sources,{'output':{'candidates':[
            {'text':"I would not quit for that much.",'nominees':['A0','A1','A2','A3']},
            {'text':'Workers should receive more pay.','nominees':['A0','A1','A2']}
        ]}},version=shared_claims.COMMON)
        self.candidates=shared_claims.candidates([record])

    def test_every_nominee_including_false_nomination_enters_once_without_old_text(self):
        groups=repair.neighborhoods(self.sources,self.candidates);self.assertEqual(len(groups),1)
        group=groups[0];self.assertEqual(group['sources'],self.sources)
        request=repair.request(group)
        self.assertEqual([x['ORIGINAL_SEGMENTS'][0]['text'] for x in request['data']['ORIGINALS']],
                         [s['text'] for s in self.sources])
        self.assertEqual(set(request['data']),{'ORIGINALS'})
        self.assertFalse(group['prior_nominees_are_support']);self.assertFalse(group['semantic_approval'])

    def test_changed_source_binding_or_duplicate_hypothesis_rejected(self):
        changed=deepcopy(self.candidates);changed[0]['nominees']['0']='0'*64
        with self.assertRaises(ValueError):repair.neighborhoods(self.sources,changed)
        with self.assertRaises(ValueError):repair.neighborhoods(self.sources,self.candidates*2)

    def test_new_intersection_is_still_an_unapproved_generated_hypothesis(self):
        group=repair.neighborhoods(self.sources,self.candidates)[0]
        result={'output':{'candidates':[{'text':'I would keep working for an additional thousand monthly.','nominees':['A0','A1']}]}}
        record=repair.bind(group,result)
        self.assertFalse(record['semantic_approval'])
        self.assertEqual(len(shared_claims.candidates([record])[0]['nominees']),2)


if __name__=='__main__':unittest.main()
