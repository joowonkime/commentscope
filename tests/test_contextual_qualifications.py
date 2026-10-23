from copy import deepcopy
import unittest

from commentscope.factory import contextual_qualifications as cq, contextual_interpretation as ci
from commentscope.factory import contextual_propositions as cp, contextual_witness as cw
from commentscope.factory import explicit_discourse as ed, literal_discovery as ld
from commentscope.factory import minimal_claims as mc, minimal_membership as mm, candidate_consolidation as cc
from test_contextual_propositions import original,positive
from test_minimal_factory import membership


def fixture(text,sid='s',function='stance',scope='complete',authorship='author'):
    source=original(text,sid);graph=ed.parse(source)
    interpreted=[ci.bind(graph,n,{'output':{'function':function,'authorship':authorship,
        'topic_relation':'direct','scope':scope,'attribution_cue':'none'}}) for n in ld.roots(graph)]
    record=cp.assemble_interpreted(graph,interpreted)
    # A held original still supplies a candidate operand for adversarial controls.
    if not mc.candidates([record]):
        from test_contextual_propositions import selected
        candidates=mc.candidates([selected(source)])
    else:candidates=mc.candidates([record])
    candidate=next(c for c in candidates if c['meaning_context']['node_id']==ld.roots(graph)[0]['id'])
    return source,candidate,interpreted[0]


def proof(left,right,shape=None,checks=()):
    return cq.assessment(positive(left[0],right[1]),left[2],right[2],shape,checks)


def nomination(f):
    s,c,i=f;pairs=[{'source_id':s['id'],'candidate_id':c['id']}]
    value=membership([s],[c],pairs)['output']
    return mm.bind([s],[c],pairs,{'output':value},contextual_assessments=[proof(f,f)])


class ContextualQualificationTests(unittest.TestCase):
    def test_identity_retains_conditions_without_model_shape_but_never_verifies_facts(self):
        for text in ('Adopt meal plans only if fees are waived.','If fees disappear, adopt meal plans.',
                     '추가 비용이 없을 때만 이 계획에 찬성합니다.'):
            f=fixture(text);a=proof(f,f);cq.validate(a)
            self.assertTrue(a['literal_identity']);self.assertTrue(a['passed'])
            self.assertFalse(a['factual_verification']);self.assertFalse(a['semantic_approval'])

    def test_identity_cannot_override_relevance_authorship_or_unresolved_scope(self):
        for kwargs in ({'function':'promotion'},{'function':'creator_or_platform'},
                       {'scope':'unresolved'},{'authorship':'unclear'}):
            f=fixture('Adopt meal plans.',**kwargs);a=proof(f,f)
            self.assertTrue(a['literal_identity']);self.assertFalse(a['passed'])

    def test_source_position_cannot_borrow_another_nodes_interpretation(self):
        f=fixture('Adopt meal plans. The broadcaster is famous.')
        g=ed.parse(f[0]);other=ci.bind(g,ld.roots(g)[1],{'output':{
            'function':'stance','authorship':'author','topic_relation':'direct','scope':'complete','attribution_cue':'none'}})
        with self.assertRaises(ValueError):cq.assessment(positive(f[0],f[1]),other,f[2])

    def test_cross_source_checks_are_required_and_other_reasons_are_not_shared(self):
        a=fixture('Require reviews because transparency matters.','a')
        b=fixture('Require reviews because safety matters.','b')
        self.assertFalse(proof(a,b)['passed'])
        shape=cq.bind_shape(b[1],{'output':{'status':'complete','qualifications':[]}})
        result=proof(a,b,shape);self.assertTrue(result['passed']);self.assertFalse(result['literal_identity'])
        self.assertEqual(shape['literal_inventory']['details'],[])
        req=cq.shape_request(b[1]);self.assertIn('because safety',str(req['data']['CANDIDATE']))
        self.assertNotIn('safety',req['data']['PROPOSITION'])

    def test_detail_check_is_bound_to_selected_position_and_context(self):
        a=fixture('Adopt meal plans only if fees are low. Fees are waived at another venue.','a')
        b=fixture('Adopt meal plans only if fees are waived.','b')
        req=cq.shape_request(b[1]);phrase=next(p for p in req['data']['PHRASES'] if p['text']=='only if fees are waived.')
        shape=cq.bind_shape(b[1],{'output':{'status':'complete','qualifications':[{'role':'condition','phrase_id':phrase['id']}]}})
        w=positive(a[0],b[1]);detail=shape['literal_inventory']['details'][0]
        request=cq.detail_request(w,shape,detail)
        self.assertEqual(request['data']['SOURCE_POSITION']['assertion']['text'],'Adopt meal plans only if fees are low.')
        check=cq.bind_detail(w,shape,detail,{'output':{'verdict':'absent'}})
        self.assertFalse(cq.assessment(w,a[2],b[2],shape,[check])['passed'])
        with self.assertRaises(ValueError):cq.assessment(w,a[2],b[2],shape,[check,check])
        changed=deepcopy(check);changed['witness_sha256']='other'
        with self.assertRaises(ValueError):cq.assessment(w,a[2],b[2],shape,[changed])

    def test_membership_requires_full_adapter_and_uses_exact_witness_evidence(self):
        f=fixture('Require reviews because safety matters.');s,c,_=f
        batch=nomination(f);row=mm.validate_batch(batch)[0]
        self.assertEqual(row['relation'],'supported');self.assertEqual(row['evidence'][0]['text'],'Require reviews')
        bare=mm.bind([s],[c],batch['pairs'],{'output':batch['output']})
        self.assertEqual(bare['memberships'][0]['relation'],'uncertain')
        bad=fixture('Require reviews.','other')
        with self.assertRaises(ValueError):mm.bind([s],[c],batch['pairs'],{'output':batch['output']},contextual_assessments=[proof(bad,bad)])

    def test_contextual_equivalence_requires_both_directions_and_exact_left_node(self):
        a=fixture('Require reviews because transparency matters.','a')
        b=fixture('Require reviews because safety matters.','b')
        ss=[a[0],b[0]];cs=[a[1],b[1]];batches=[nomination(a),nomination(b)]
        ids=sorted(c['id'] for c in cs);pairs=[{'a':ids[0],'b':ids[1]}]
        output={'decisions':[{'pair_id':'P1','relation':'equivalent'}]};directions=[]
        for left,right in ((a,b),(b,a)):
            shape=cq.bind_shape(right[1],{'output':{'status':'complete','qualifications':[]}})
            directions.append({'from_candidate_id':left[1]['id'],'to_candidate_id':right[1]['id'],'assessment':proof(left,right,shape)})
        half=cc.bind(ss,cs,batches,pairs,{'output':output},contextual_assessments=directions[:1])
        self.assertEqual(half['relations'][0]['relation'],'uncertain')
        full=cc.bind(ss,cs,batches,pairs,{'output':output},contextual_assessments=directions)
        self.assertEqual(full['relations'][0]['relation'],'equivalent')
        merged=cc.consolidate(ss,cs,batches,[full]);self.assertEqual(len(merged['candidates']),1)
        changed=deepcopy(directions);changed[0]['from_candidate_id']=changed[0]['to_candidate_id']
        with self.assertRaises(ValueError):cc.bind(ss,cs,batches,pairs,{'output':output},contextual_assessments=changed)

    def test_changed_parent_or_video_context_invalidates_assessment(self):
        a=fixture('This should start tomorrow.');result=proof(a,a)
        changed=deepcopy(result);changed['witness']['candidate']['meaning_context']['source']['parent']={'id':'p','text':'Another policy.'}
        with self.assertRaises(ValueError):cq.validate(changed)


if __name__=='__main__':unittest.main()
