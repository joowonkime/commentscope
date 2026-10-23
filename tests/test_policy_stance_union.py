from copy import deepcopy
import unittest
from commentscope.factory import policy_stance_hypotheses as stance,policy_stance_union as union,shared_claims
from test_source_entailment import nli_response


class PolicyStanceUnionTests(unittest.TestCase):
    def setUp(self):
        self.sources=[{'id':str(i),'text':'Policy P could be good.','parent':None,
            'video_context':{'artifact_kind':'snapshot-video-context-20261017-v1','video_id':'v',
                'title':'Policy P Explained PP','primary_language':'en'}} for i in range(3)]
        self.parts=[self.part(self.sources[:1]),self.part(self.sources[1:])]
    def part(self,sources):
        request=stance.invocation(sources,'Policy P','PP')
        return stance.bind(sources,'Policy P','PP',nli_response(request))

    def test_disjoint_batches_cover_every_original_without_synthetic_joint_request(self):
        record=union.combine(self.parts,self.sources)
        self.assertFalse(record['synthetic_joint_request']);self.assertFalse(record['semantic_approval'])
        self.assertEqual(shared_claims.for_scope([record],self.sources),[record])
        self.assertEqual([len(c['nominees']) for c in shared_claims.candidates([record])],[3,3])
        self.assertEqual(record['parts'],self.parts)

    def test_duplicate_missing_or_changed_original_is_rejected(self):
        for parts in [self.parts+self.parts[:1],self.parts[:1]]:
            with self.assertRaises(ValueError):union.combine(parts,self.sources)
        record=union.combine(self.parts,self.sources);record['sources'][0]['text']='Changed.'
        with self.assertRaises(ValueError):union.validate(record)

    def test_source_order_can_change_without_changing_any_original_or_reusing_votes(self):
        record=union.combine(self.parts,list(reversed(self.sources)))
        self.assertEqual({s['id'] for s in record['sources']},{'0','1','2'})
        self.assertEqual([len(c['nominees']) for c in union.candidates(record)],[3,3])
