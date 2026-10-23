from copy import deepcopy
import unittest
from commentscope.factory import policy_stance_hypotheses as stance,shared_claims
from test_source_entailment import nli_response


class PolicyStanceHypothesesTests(unittest.TestCase):
    def setUp(self):
        self.sources=[{'id':str(i),'text':text,'parent':{'id':'parent','text':'Parent-only stance.'},
            'video_context':{'artifact_kind':'snapshot-video-context-20261017-v1',
                'video_id':'v','title':'Policy P Explained (PP)','primary_language':'en'}}
            for i,text in enumerate(['Policy P seems good.','Policy P seems bad.'])]
        self.request=stance.invocation(self.sources,'Policy P','PP')
        self.response=nli_response(self.request)
    def record(self):return stance.bind(self.sources,'Policy P','PP',self.response)

    def test_every_source_compared_to_both_candidates_without_parent_evidence(self):
        self.assertEqual(len(self.request['data']['cases']),4)
        for case in self.request['data']['cases']:
            sid=case['evidence'][0]['id'];original=next(s for s in self.sources if s['id']==sid)
            self.assertEqual(case['evidence'],[{'id':sid,'text':original['text']}])
            self.assertNotIn('Parent-only',str(case));self.assertIn('some circumstances',case['text'])

    def test_nominations_remain_hypotheses_and_all_originals_rebound(self):
        record=self.record();candidates=shared_claims.candidates([record])
        self.assertEqual(len(candidates),2);self.assertTrue(all(len(c['nominees'])==2 for c in candidates))
        self.assertFalse(record['semantic_approval'])
        self.assertEqual(shared_claims.for_scope([record],self.sources),[record])
        with self.assertRaises(ValueError):shared_claims.for_scope([record],self.sources[:1])

    def test_topic_and_alias_must_be_bound_to_same_video_metadata(self):
        with self.assertRaises(ValueError):stance.invocation(self.sources,'Other policy','PP')
        changed=deepcopy(self.sources);changed[0]['video_context']['video_id']='other'
        with self.assertRaises(ValueError):stance.invocation(changed,'Policy P','PP')

    def test_incomplete_or_modified_response_cannot_nominate(self):
        for mutate in [lambda r:r['results'].pop(),lambda r:r['results'].reverse(),
                       lambda r:r['results'][0]['pairs'][0]['scores'].update(entailment=.01)]:
            response=deepcopy(self.response);mutate(response)
            with self.assertRaises(ValueError):stance.bind(self.sources,'Policy P','PP',response)
