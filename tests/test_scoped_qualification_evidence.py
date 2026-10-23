from copy import deepcopy
import unittest

from commentscope.factory import scoped_qualification_evidence as qe,scoped_comparison as sc
from commentscope.factory import candidate_consolidation as cc, minimal_membership as mm
from commentscope.factory import contextual_qualifications as cq, contextual_witness as cw
from test_contextual_dependencies import fixture,scope


def reason_case(source_text,version=sc.VERSION,source_mode='candidate_assertion'):
    a=fixture(source_text,'source')
    b=fixture('Library cards should remain optional because access matters and because flexibility matters.','target')
    sa,sb=scope(*a),scope(*b)
    w=sc.bind(sa,b[0],sb,{'output':{'relation':'supported','interpretation':'clear'}},version,source_mode=source_mode)
    req=sc.shape_request(b[0],sb)
    phrase=next(p for p in req['data']['PHRASES'] if p['text'].startswith('because access'))
    shape=sc.bind_shape(b[0],sb,{'output':{'status':'complete','qualifications':[{'role':'reason','phrase_id':phrase['id']}]}})
    return w,shape,shape['literal_inventory']['details'][0]


class ScopedQualificationEvidenceTests(unittest.TestCase):
    def test_candidate_only_reason_cannot_be_approved_without_source_address(self):
        w,shape,detail=reason_case('Library cards should remain optional. Museum tickets should be free because access matters and because flexibility matters.')
        req=sc.detail_request(w,shape,detail)
        self.assertEqual(req['data']['SOURCE_QUALIFICATION_EVIDENCE'],[])
        self.assertEqual(req['schema']['properties']['source_evidence_id']['enum'],['none'])
        check=sc.bind_detail(w,shape,detail,{'output':{'verdict':'present','source_evidence_id':'none'}})
        self.assertEqual(check['verdict'],'uncertain');self.assertEqual(check['evidence'],[])
        self.assertFalse(sc.assessment(w,sc.bind_alignment(w,{'output':{'verdict':'compatible'}}),shape,[check])['passed'])
        with self.assertRaises(ValueError):sc.bind_detail(w,shape,detail,{'output':{'verdict':'present','source_evidence_id':'E1'}})

    def test_coordinated_source_reason_has_one_complete_original_address(self):
        w,shape,detail=reason_case('Library cards should remain voluntary because access matters and because flexibility matters.')
        evidence=qe.eligible(w['source_scope'],'reason')
        self.assertEqual(len(evidence),1)
        self.assertEqual(evidence[0]['span']['text'],'because access matters and because flexibility matters.')
        self.assertEqual(evidence[0]['syntax_proof']['kind'],'coordinated_explicit_reasons')
        check=sc.bind_detail(w,shape,detail,{'output':{'verdict':'present','source_evidence_id':evidence[0]['id']}})
        self.assertEqual(check['evidence'],[evidence[0]['span']])
        assessment=sc.assessment(w,sc.bind_alignment(w,{'output':{'verdict':'compatible'}}),shape,[check])
        self.assertTrue(assessment['passed']);sc.validate_assessment(assessment)
        changed=deepcopy(check);changed['selected_source_evidence']['span']['text']='Other reason.'
        with self.assertRaises(ValueError):sc.assessment(w,assessment['alignment'],shape,[changed])

    def test_separately_attached_ground_is_available_only_for_qualified_target(self):
        w,shape,detail=reason_case('Library cards should remain optional because access and flexibility matter.',source_mode='source_contribution')
        evidence=qe.eligible(w['source_scope'],'reason')
        self.assertEqual(evidence[0]['syntax_proof']['kind'],'original_owned_edge')
        self.assertIn('because access and flexibility matter.',str(sc.request(w['source_scope'],w['candidate'],w['candidate_scope'],source_mode='source_contribution')['data']['SOURCE_OWNED_QUALIFICATIONS']))
        self.assertNotIn('flexibility',sc.own_text(w['source_scope']))
        bare=fixture('Library cards should remain optional.','bare')
        req=sc.request(w['source_scope'],bare[0],scope(*bare))
        self.assertNotIn('SOURCE_OWNED_QUALIFICATIONS',req['data'])
        self.assertNotIn('flexibility',str(req['data']))

    def test_personal_reason_support_cannot_be_used_as_proposition_equivalence(self):
        text='Library cards should remain optional because access and flexibility matter.'
        w,shape,detail=reason_case(text,source_mode='source_contribution')
        source_ground=qe.eligible(w['source_scope'],'reason')[0]
        detail_check=sc.bind_detail(w,shape,detail,{'output':{'verdict':'present','source_evidence_id':source_ground['id']}})
        proof=sc.assessment(w,sc.bind_alignment(w,{'output':{'verdict':'compatible'}}),shape,[detail_check])
        self.assertTrue(proof['passed'])
        bare,interpretation=fixture(text,'source');target=w['candidate']
        sources=[bare['meaning_context']['source'],target['meaning_context']['source']];candidates=[bare,target]
        target_i=w['candidate_scope']['interpretation']
        nominations=mm.bind_contextual(sources,candidates,[cq.assessment(cw.identity(s,c,i),i,i)
            for s,c,i in zip(sources,candidates,[interpretation,target_i])])
        ids=sorted(c['id'] for c in candidates)
        with self.assertRaises(ValueError):cc.bind_scoped_equivalence(sources,candidates,[nominations],
            [{'a':ids[0],'b':ids[1]}],[{'from_candidate_id':bare['id'],'to_candidate_id':target['id'],'assessment':proof}])
        strict,shape,detail=reason_case(text)
        req=sc.detail_request(strict,shape,detail)
        self.assertEqual(req['data']['SOURCE_QUALIFICATION_EVIDENCE'],[])
        self.assertEqual(sc.request(strict['source_scope'],strict['candidate'],strict['candidate_scope'])['data']['SOURCE_OWNED_QUALIFICATIONS'],[])
        self.assertNotEqual(w,strict)

    def test_roles_parent_and_discourse_target_cannot_donate_evidence(self):
        pair=fixture('School meals should be free although funding is limited.','s');s=scope(*pair)
        self.assertEqual(qe.eligible(s,'reason'),[]);self.assertEqual(len(qe.eligible(s,'concession')),1)
        pair=fixture('People say "School meals should be free because access matters." I disagree: meals should cost money.','s',1)
        self.assertEqual(qe.eligible(scope(*pair,links={'DISCOURSE':'C1'}),'reason'),[])
        pair=fixture('Library cards should remain optional.','s',parent={'id':'p','text':'Library cards should remain optional because access matters.'})
        self.assertEqual(qe.eligible(scope(*pair),'reason'),[])

    def test_ambiguous_nested_negated_or_mixed_operators_are_not_coordinated_reasons(self):
        for text in [
            'Cards should be optional because meals are free because funding is secure.',
            'Cards should be optional not because access matters and because flexibility matters.',
            'Cards should be optional because access matters although flexibility matters.',
            'Cards should be optional because if access matters funding follows and because flexibility matters.',
        ]:
            pair=fixture(text);self.assertEqual(qe.eligible(scope(*pair),'reason'),[],text)

    def test_old_detail_contract_remains_replayable_and_new_contract_demands_witness(self):
        text='Library cards should remain optional.'
        old,shape,detail=reason_case(text,sc.NOMINAL)
        check=sc.bind_detail(old,shape,detail,{'output':{'verdict':'present'}})
        self.assertEqual(check['artifact_kind'],sc.BASE+'-detail')
        assessment=sc.assessment(old,sc.bind_alignment(old,{'output':{'verdict':'compatible'}}),shape,[check])
        self.assertTrue(assessment['passed']);sc.validate_assessment(assessment)
        current,shape,detail=reason_case(text)
        with self.assertRaises(ValueError):sc.bind_detail(current,shape,detail,{'output':{'verdict':'present'}})


if __name__=='__main__':unittest.main()
