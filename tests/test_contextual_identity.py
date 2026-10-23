from copy import deepcopy
import unittest

from commentscope.factory import contextual_interpretation as ci, contextual_witness as cw
from commentscope.factory import contextual_qualifications as cq, contextual_propositions as cp
from commentscope.factory import source_attribution as attribution, explicit_discourse as ed, literal_discovery as ld
from test_contextual_qualifications import fixture
from test_contextual_propositions import original


def value(**changes):
    return {'function':'stance','authorship':'author','topic_relation':'direct','scope':'complete',
            'attribution_cue':'none',**changes}


class ContextualIdentityTests(unittest.TestCase):
    def test_grammatical_actors_cannot_be_named_as_speakers_without_original_cue(self):
        for text in ('Several towns fund night buses.','Children need free meals.',
                     'The school closes tomorrow.','작은 도시는 무료 버스를 운영한다.'):
            g=ed.parse(original(text));n=ld.roots(g)[0];req=ci.request(g,n)
            self.assertTrue(all('other' not in b['properties']['authorship']['enum']
                                for b in req['schema']['anyOf']))
            with self.assertRaises(ValueError):ci.bind(g,n,{'output':value(authorship='other')})
            with self.assertRaises(ValueError):ci.bind(g,n,{'output':value(function='reported_view')})
            r=ci.bind(g,n,{'output':value()});self.assertEqual(r['literal_author_source_id'],'s')

    def test_other_speech_binds_cue_but_a_quoted_title_or_first_person_does_not_force_transfer(self):
        for text in ('Some people say "Cards must be mandatory."','My neighbor said cards must be mandatory.'):
            g=ed.parse(original(text));n=ld.roots(g)[0];cues=attribution.cues(g,n)
            r=ci.bind(g,n,{'output':value(function='reported_view',authorship='other',attribution_cue=cues[0]['id'])})
            self.assertEqual(ci.decision(g,n,r)['authorship'],'reported')
            with self.assertRaises(ValueError):ci.bind(g,n,{'output':value(authorship='other')})
        for text in ('Look at the study "Urban Gardens".','I believe garden fees should be waived.'):
            g=ed.parse(original(text));n=ld.roots(g)[0];self.assertTrue(attribution.cues(g,n))
            r=ci.bind(g,n,{'output':value()});self.assertEqual(ci.decision(g,n,r)['authorship'],'asserted')

    def test_unresolved_scope_cannot_be_silently_recast_as_irrelevance(self):
        g=ed.parse(original('Not really.'));n=ld.roots(g)[0]
        r=ci.bind(g,n,{'output':value(topic_relation='unrelated',scope='unresolved')})
        self.assertEqual(ci.decision(g,n,r)['contribution'],'uncertain')
        extracted=cp.assemble_interpreted(g,[r]);self.assertEqual(extracted['status'],'unresolved')
        self.assertEqual(len(extracted['position_bundles']),1)

    def test_literal_identity_is_deterministic_and_not_a_synthetic_model_response(self):
        for text in ('Look at the study "Urban Gardens".','Now I am not sure.',
                     'If fees are waived, I would join.','학교 급식은 자율에 맡겨야 합니다.'):
            s,c,i=fixture(text);w=cw.identity(s,c,i);cw.validate(w)
            self.assertNotIn('output',w);self.assertNotIn('request_sha256',w)
            self.assertEqual(w['model_calls'],0);self.assertEqual(w['relation'],'supported')
            self.assertFalse(w['semantic_approval']);self.assertFalse(w['factual_verification'])
            a=cq.assessment(w,i,i);self.assertTrue(a['passed']);cq.validate(a)

    def test_identity_cannot_approve_bad_interpretation_or_cross_source_context(self):
        for kwargs in ({'scope':'unresolved'},{'function':'creator_or_platform'},{'authorship':'unclear'}):
            s,c,i=fixture('Public gardens should be free.',**kwargs)
            w=cw.identity(s,c,i);self.assertEqual(w['relation'],'uncertain');self.assertFalse(cq.assessment(w,i,i)['passed'])
        s,c,i=fixture('This rule should begin tomorrow.')
        for field,val in (('id','different'),('parent',{'id':'p','text':'A different rule.'})):
            changed=deepcopy(s);changed[field]=val
            with self.assertRaises(ValueError):cw.identity(changed,c,i)
        w=cw.identity(s,c,i);changed=deepcopy(w);changed['proof']['node_id']='other'
        with self.assertRaises(ValueError):cw.validate(changed)

    def test_previous_interpretation_contract_stays_replayable(self):
        g=ed.parse(original('Cities fund parks.'));n=ld.roots(g)[0]
        output={k:v for k,v in value(authorship='other').items() if k!='attribution_cue'}
        r=ci.bind(g,n,{'output':output},ci.LEGACY)
        self.assertEqual(ci.decision(g,n,r)['authorship'],'reported')
        self.assertEqual(r['artifact_kind'],ci.LEGACY)
        with self.assertRaises(ValueError):ci.bind(g,n,{'output':output})

    def test_cross_source_reference_scope_is_not_proved_by_identical_pronoun_text(self):
        from commentscope.factory import minimal_claims as mc
        from test_contextual_propositions import positive
        def interpreted(subject,sid):
            g=ed.parse(original(subject+' should be free. This rule should begin tomorrow.',sid))
            records=[ci.bind(g,n,{'output':value()}) for n in ld.roots(g)]
            r=cp.assemble_interpreted(g,records)
            c=next(c for c in mc.candidates([r]) if c['text'].startswith('This rule'))
            return g['source'],c,records[1]
        left=interpreted('Archive access','a')
        for subject in ('Road tolls','Archive access'):
            right=interpreted(subject,'b');w=positive(left[0],right[1],'P2')
            shape=cq.bind_shape(right[1],{'output':{'status':'complete','qualifications':[]}})
            a=cq.assessment(w,left[2],right[2],shape)
            self.assertFalse(a['passed']);self.assertIn('cross_source_reference_scope_unassessed',a['guards'])
            # Same-referent positive is deliberately unassessed too: a hold is
            # not a completed context resolver and cannot claim coverage success.
            cq.validate(a)
        w=cw.identity(left[0],left[1],left[2]);self.assertTrue(cq.assessment(w,left[2],left[2])['passed'])


if __name__=='__main__':unittest.main()
