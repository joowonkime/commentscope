from copy import deepcopy
import unittest

from commentscope.factory import scoped_comparison as sc,contextual_qualifications as cq,contextual_witness as cw
from commentscope.factory import minimal_membership as mm,candidate_consolidation as cc
from test_contextual_dependencies import fixture,scope


def witness(a,b,relation='supported'):
    return sc.bind(a[1],b[0],b[1],{'output':{'relation':relation,'interpretation':'clear'}})


def complete(w,scope_verdict='compatible'):
    alignment=sc.bind_alignment(w,{'output':{'verdict':scope_verdict}})
    shape=sc.bind_shape(w['candidate'],w['candidate_scope'],{'output':{'status':'complete','qualifications':[]}})
    return sc.assessment(w,alignment,shape)


class ScopedComparisonTests(unittest.TestCase):
    def test_directive_prediction_and_condition_direction_guards_preserve_legacy_replay(self):
        cases=[('We need free garden access right now!','Garden access will become free.','supported','directive_is_not_a_prediction'),
               ('Garden access should be free.','Garden access should be free only if funding is secured.','conditional','candidate_condition_is_not_source_condition'),
               ('If lunch fees disappeared, I would start attending.','Lunch fees must disappear immediately.','opposed','modality_difference_does_not_establish_opposition')]
        for s,t,relation,guard in cases:
            a,b=fixture(s,'a'),fixture(t,'b');sa,sb=scope(*a),scope(*b);value={'relation':relation,'interpretation':'clear'}
            old=sc.bind(sa,b[0],sb,{'output':value},sc.BASE);sc.validate(old)
            self.assertEqual(old['relation'],relation)
            new=sc.bind(sa,b[0],sb,{'output':value});self.assertEqual(new['relation'],'uncertain')
            self.assertIn(guard,new['guards']);sc.validate(new)

    def test_disagreement_with_opponent_does_not_negate_following_own_stance(self):
        f=fixture('Library cards should remain optional.','f')
        m=fixture('Some people say "Library cards should be mandatory." I disagree: cards should remain optional.','m',1)
        left=(f[0],scope(*f));right=(m[0],scope(*m,links={'DISCOURSE':'C1'}))
        w=witness(left,right);cw.validate(w);a=complete(w);cq.validate(a)
        self.assertTrue(a['passed'])
        req=sc.request(left[1],right[0],right[1]);own=req['data']['CANDIDATE_POSITION']['DISCOURSE_OPERATOR']
        self.assertEqual(own['FOLLOWING_OWN_UTTERANCE'],'cards should remain optional.')
        self.assertNotIn('INTERPRETATION_CONTEXT_ONLY',str(req['data']))
        self.assertNotIn('OWNED_RELATIONS',str(req['data']))
        self.assertFalse(a['factual_verification'])

    def test_semantic_support_requires_independent_referent_alignment_and_qualifications(self):
        a=fixture('Garden access should be free.','a');b=fixture('Entry to the garden should cost nothing.','b')
        w=witness((a[0],scope(*a)),(b[0],scope(*b)))
        self.assertFalse(sc.assessment(w)['passed'])
        self.assertFalse(complete(w,'incompatible')['passed'])
        self.assertFalse(complete(w,'uncertain')['passed'])
        self.assertTrue(complete(w)['passed'])
        altered=deepcopy(complete(w));altered['alignment']['witness_sha256']='foreign'
        with self.assertRaises(ValueError):cq.validate(altered)

    def test_extra_source_reasons_never_enter_the_comparison_or_shape(self):
        a=fixture('Garden access should be free because education matters.','a')
        b=fixture('Entry to the garden should cost nothing because inclusion matters.','b')
        sa,sb=scope(*a),scope(*b)
        req=sc.request(sa,b[0],sb)
        self.assertNotIn('education',str(req['data']));self.assertNotIn('inclusion',str(req['data']))
        self.assertNotIn('inclusion',str(sc.shape_request(b[0],sb)['data']))

    def test_entire_assertion_cannot_be_its_own_reason_even_when_model_selects_it(self):
        b=fixture('Garden access should be free.');sb=scope(*b);req=sc.shape_request(b[0],sb)
        full=next(p for p in req['data']['PHRASES'] if p['text']==b[0]['text'])
        shape=sc.bind_shape(b[0],sb,{'output':{'status':'complete','qualifications':[{'role':'reason','phrase_id':full['id']}]}})
        self.assertFalse(shape['ready']);self.assertIn('entire_assertion_is_not_its_own_qualification',shape['guards'])
        w=witness((b[0],sb),(b[0],sb))
        self.assertFalse(sc.assessment(w,sc.bind_alignment(w,{'output':{'verdict':'compatible'}}),shape)['passed'])

    def test_conditions_and_time_cannot_disappear_behind_positive_model_relation(self):
        cases=[('Garden access should be free only if funding is secured.','Garden access should be free.'),
               ('Garden access will be free.','We need free garden access right now!')]
        for s,t in cases:
            a=fixture(s,'a');b=fixture(t,'b');w=witness((a[0],scope(*a)),(b[0],scope(*b)))
            self.assertEqual(w['relation'],'uncertain');self.assertFalse(complete(w)['passed'])

    def test_missing_detail_cannot_borrow_another_positions_reason(self):
        a=fixture('Offer lunch discounts. Open the park on Sunday because weekday shifts exclude workers.','a')
        b=fixture('Offer lunch discounts because weekday shifts exclude workers and because buses are costly.','b')
        sa,sb=scope(*a),scope(*b);w=witness((a[0],sa),(b[0],sb));req=sc.shape_request(b[0],sb)
        p=next(p for p in req['data']['PHRASES'] if p['text'].startswith('because weekday'))
        shape=sc.bind_shape(b[0],sb,{'output':{'status':'complete','qualifications':[{'role':'reason','phrase_id':p['id']}]}})
        d=shape['literal_inventory']['details'][0];request=sc.detail_request(w,shape,d)
        self.assertNotIn('weekday',str(request['data']['SOURCE_POSITION']))
        check=sc.bind_detail(w,shape,d,{'output':{'verdict':'absent','source_evidence_id':'none'}})
        self.assertFalse(sc.assessment(w,sc.bind_alignment(w,{'output':{'verdict':'compatible'}}),shape,[check])['passed'])

    def test_two_qualified_directions_are_required_for_semantic_merge(self):
        a=fixture('Garden access should be free.','a');b=fixture('Entry to the garden should cost nothing.','b')
        ss=[a[0]['meaning_context']['source'],b[0]['meaning_context']['source']];cs=[a[0],b[0]]
        nominations=mm.bind_contextual(ss,cs,[cq.assessment(cw.identity(s,c,i),i,i) for s,(c,i) in zip(ss,(a,b))])
        directions=[]
        for left,right in ((a,b),(b,a)):
            w=witness((left[0],scope(*left)),(right[0],scope(*right)))
            directions.append({'from_candidate_id':left[0]['id'],'to_candidate_id':right[0]['id'],'assessment':complete(w)})
        ids=sorted(c['id'] for c in cs);pairs=[{'a':ids[0],'b':ids[1]}]
        half=cc.bind_scoped_equivalence(ss,cs,[nominations],pairs,directions[:1])
        self.assertEqual(half['relations'][0]['relation'],'uncertain')
        full=cc.bind_scoped_equivalence(ss,cs,[nominations],pairs,directions)
        self.assertEqual(full['relations'][0]['relation'],'equivalent');self.assertNotIn('output',full)
        self.assertEqual(len(cc.consolidate(ss,cs,[nominations],[full])['candidates']),1)
        with self.assertRaises(ValueError):cc.bind_scoped_literal(ss,cs,[nominations],pairs,directions)


if __name__=='__main__':unittest.main()
