from copy import deepcopy
import unittest

from commentscope.factory import minimal_membership as mm, minimal_agents as ma
from commentscope.factory import scoped_comparison as sc, scoped_qualification_evidence as qe
from commentscope.factory.automatic_contract import digest
from test_scoped_qualification_evidence import reason_case


def proved(text):
    witness,shape,detail=reason_case(text,source_mode='source_contribution')
    evidence=qe.eligible(witness['source_scope'],'reason')[0]
    check=sc.bind_detail(witness,shape,detail,{'output':{'verdict':'present','source_evidence_id':evidence['id']}})
    return sc.assessment(witness,sc.bind_alignment(witness,{'output':{'verdict':'compatible'}}),shape,[check])


class ContextualMembershipEvidenceTests(unittest.TestCase):
    def test_own_attached_reason_survives_membership_and_core_citation(self):
        proof=proved('Library cards should remain optional because access and flexibility matter.')
        w=proof['witness'];source=w['source'];target=w['candidate']
        batch=mm.bind_contextual([source],[target],[proof]);row=mm.validate_batch(batch)[0]
        self.assertEqual(row['relation'],'supported');self.assertEqual(len(row['evidence']),2)
        self.assertEqual(row['evidence'][1]['text'],'because access and flexibility matter.')
        core={'id':'core','text':target['text'],'kind':'value',
              'scope':{'entity':'','time':'','conditions':''},'requires':[]}
        citation=ma.relation(core,source,row['evidence'],digest(row))
        self.assertEqual(citation['span']['text'],source['text'])
        self.assertEqual(len(mm.collect([source],[target],[batch])),1)

    def test_old_batch_replays_exactly_and_contained_detail_is_not_duplicated(self):
        proof=proved('Library cards should remain optional because access and flexibility matter.')
        w=proof['witness'];source=w['source'];target=w['candidate']
        old=mm.bind_contextual([source],[target],[proof],version=mm.LEGACY_CONTEXTUAL)
        self.assertEqual(mm.validate_batch(old)[0]['evidence'],w['evidence'])
        self.assertNotEqual(old,mm.bind_contextual([source],[target],[proof]))
        complete=proved('Library cards should remain voluntary because access matters and because flexibility matters.')
        self.assertEqual(mm.contextual_evidence(complete),complete['witness']['evidence'])

    def test_other_position_reason_and_changed_source_cannot_enter_citation(self):
        w,shape,detail=reason_case('Library cards should remain optional. Museum tickets should be free because access matters and because flexibility matters.',source_mode='source_contribution')
        check=sc.bind_detail(w,shape,detail,{'output':{'verdict':'present','source_evidence_id':'none'}})
        held=sc.assessment(w,sc.bind_alignment(w,{'output':{'verdict':'compatible'}}),shape,[check])
        self.assertFalse(held['passed']);self.assertEqual(mm.contextual_evidence(held),w['evidence'])
        self.assertNotIn('Museum',str(mm.contextual_evidence(held)))
        changed=deepcopy(held);changed['checks'][0]['evidence']=[{'start':38,'end':123,'text':w['source']['text'][38:123]}]
        with self.assertRaises(ValueError):mm.contextual_evidence(changed)
        proof=proved('Library cards should remain optional because access and flexibility matter.')
        w=proof['witness'];source=deepcopy(w['source']);source['text']+=' Different context.'
        with self.assertRaises(ValueError):mm.bind_contextual([source],[w['candidate']],[proof])
        batch=mm.bind_contextual([w['source']],[w['candidate']],[proof])
        batch['memberships'][0]['evidence']=deepcopy(w['evidence'])
        with self.assertRaises(ValueError):mm.validate_batch(batch)


if __name__=='__main__':unittest.main()
