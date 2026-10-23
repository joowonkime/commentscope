from copy import deepcopy
import unittest

from commentscope.factory import contextual_dependencies as cd, contextual_propositions as cp
from commentscope.factory import contextual_interpretation as ci, contextual_witness as cw, contextual_qualifications as cq
from commentscope.factory import explicit_discourse as ed, literal_discovery as ld, minimal_claims as mc
from commentscope.factory import minimal_membership as mm, candidate_consolidation as cc
from test_contextual_propositions import original
from test_contextual_identity import value


def fixture(text,sid='s',index=0,parent=None):
    graph=ed.parse(original(text,sid,parent));nodes=ld.roots(graph)
    records=[ci.bind(graph,n,{'output':value()}) for n in nodes]
    extracted=cp.assemble_interpreted(graph,records)
    candidate=next(c for c in mc.candidates([extracted]) if c['meaning_context']['node_id']==nodes[index]['id'])
    return candidate,records[index]


def scope(candidate,interpretation,links=None,**changes):
    bundle=candidate['meaning_context']
    return cd.bind(bundle,interpretation,{'output':{'links':links or {},
        'scope':'complete','speech':'literal','world':'actual','closure':'complete',**changes}})


class ContextualDependencyTests(unittest.TestCase):
    def test_unbound_disagreement_operator_cannot_hide_different_quoted_context(self):
        a=fixture('Some people say "Library cards should be mandatory." I disagree: cards should remain optional.','a',1)
        b=fixture('Some people say "Transit cards should be mandatory." I disagree: cards should remain optional.','b',1)
        def old_guarded(pair):
            return cd.bind(pair[0]['meaning_context'],pair[1],{'output':{
                'links':{},'scope':'complete','speech':'literal','world':'actual','closure':'complete'}},cd.GUARDED)
        sa,sb=old_guarded(a),old_guarded(b)
        self.assertIn('discourse_target_dependency_unassessed',sa['guards'])
        self.assertFalse(cd.literal_equivalence(sa,sb)['equivalent'])
        self.assertFalse(cq.assessment(cw.scoped_identity(sa,b[0],sb),a[1],b[1])['passed'])
        old=cd.bind(a[0]['meaning_context'],a[1],{'output':sa['output']},cd.ADDRESSED)
        cd.validate(old);self.assertTrue(old['ready'])

    def test_addressed_discourse_keeps_the_following_own_stance_and_quoted_target_separate(self):
        from commentscope.factory import source_discourse_acts as acts
        a=fixture('Some people say "Library cards should be mandatory." I disagree: cards should remain optional.','a',1)
        with self.assertRaises(ValueError):scope(*a)
        sa=scope(*a,links={'DISCOURSE':'C1'});self.assertTrue(sa['ready'])
        packet=cd.packet(sa)
        self.assertEqual(packet['DISCOURSE_OPERATOR']['FOLLOWING_OWN_UTTERANCE'],'cards should remain optional.')
        self.assertEqual(packet['dependencies'][0]['role'],'discourse_target')
        self.assertIn('mandatory',packet['dependencies'][0]['context'])
        self.assertNotIn('mandatory',packet['DISCOURSE_OPERATOR']['FOLLOWING_OWN_UTTERANCE'])
        body=acts.structure(a[0]['meaning_context'])['following_own_utterance'];text=a[0]['meaning_context']['source']['text']
        self.assertEqual(body['text'],text[body['start']:body['end']])
        b=fixture('Some people say "Transit cards should be mandatory." I disagree: cards should remain optional.','b',1)
        self.assertFalse(cd.literal_equivalence(sa,scope(*b,links={'DISCOURSE':'C1'}))['equivalent'])
        for prefix,relation in [('I agree:','agree'),('I do not agree:','not_agree'),("We don't disagree:",'not_disagree')]:
            c=fixture('Some people say "Cards should be optional." '+prefix+' cards should be optional.','s',1)
            self.assertEqual(acts.structure(c[0]['meaning_context'])['relation'],relation)

    def test_new_contract_cannot_create_an_unanchored_context_link_and_legacy_replays(self):
        c,i=fixture('Garden access should be free.')
        current=scope(c,i);bundle=c['meaning_context']
        self.assertNotIn('additional_context',cd.request(bundle,i)['schema']['properties'])
        with self.assertRaises(ValueError):scope(c,i,additional_context=[])
        old=cd.bind(bundle,i,{'output':{**current['output'],'additional_context':[]}},cd.LEGACY)
        cd.validate(old);self.assertEqual(old['artifact_kind'],cd.LEGACY)
        self.assertIn('another indispensable',cd.request(bundle,i)['system'])

    def test_same_assertion_different_personal_reasons_is_retained_without_model_comparison(self):
        a=fixture('Garden access should be free because education matters.','a')
        b=fixture('Garden access should be free because inclusion matters.','b')
        sa,sb=scope(*a),scope(*b);proof=cd.literal_equivalence(sa,sb)
        self.assertTrue(proof['equivalent']);self.assertEqual(proof['model_calls'],0)
        self.assertNotIn('education',str(cd.packet(sa)));self.assertNotIn('inclusion',str(cd.packet(sb)))
        self.assertIn('education',str(sa['bundle']['owned_edges'])+str(sa['bundle']['source']))
        w=cw.scoped_identity(sa,b[0],sb);cw.validate(w)
        assessment=cq.assessment(w,a[1],b[1]);cq.validate(assessment)
        self.assertTrue(assessment['passed']);self.assertFalse(assessment['literal_identity'])
        self.assertNotIn('output',w);self.assertFalse(w['factual_verification'])
        with self.assertRaises(ValueError):
            cq.assessment(w,a[1],b[1],cq.bind_shape(b[0],{'output':{'status':'complete','qualifications':[]}}))

    def test_reference_positive_and_negative_across_different_sources_and_topics(self):
        for topic,other in [('Archive access','Road tolls'),('School meals','Lab reviews'),('Train rides','Park fees')]:
            a=fixture(topic+' should be free. This rule should begin tomorrow.','a',1)
            same=fixture(topic+' should be free. This rule should begin tomorrow.','b',1)
            different=fixture(other+' should be free. This rule should begin tomorrow.','c',1)
            sa=scope(*a,links={'R1':'C1'})
            for b,expected in ((same,True),(different,False)):
                sb=scope(*b,links={'R1':'C1'});w=cw.scoped_identity(sa,b[0],sb)
                self.assertEqual(cq.assessment(w,a[1],b[1])['passed'],expected)
                self.assertEqual(w['relation'],'supported' if expected else 'uncertain')
            self.assertEqual(sa['bundle']['assertion']['text'],'This rule should begin tomorrow.')
            self.assertFalse(cd.packet(sa)['dependencies'][0]['asserted_separately'])

    def test_missing_foreign_self_and_nested_reference_addresses_cannot_pass(self):
        a=fixture('Garden access should be free. This rule should start tomorrow.','a',1)
        for links in ({},{'R1':'C999'},{'R1':'none'}):
            with self.assertRaises(ValueError):scope(*a,links=links)
        held=scope(*a,links={'R1':'unresolved'});self.assertFalse(held['ready'])
        inv=cd.inventory(a[0]['meaning_context'])
        self.assertTrue(all(c['span']!=a[0]['meaning_context']['assertion'] for c in inv['choices']))
        nested=fixture('This rule should start tomorrow. It should last forever.','b',1)
        self.assertFalse(scope(*nested,links={'R1':'C1'})['ready'])

    def test_equal_strings_cannot_bypass_irony_unresolved_world_or_independent_authorship(self):
        a=fixture('Garden access should be free.','a');b=fixture('Garden access should be free.','b')
        sa=scope(*a)
        for changes in ({'speech':'nonliteral'},{'scope':'unresolved'},{'closure':'unresolved'},{'world':'unclear'}):
            sb=scope(*b,**changes);self.assertFalse(cd.literal_equivalence(sa,sb)['equivalent'])
        bundle=b[0]['meaning_context'];graph=ed.parse(bundle['source']);node=ld.roots(graph)[0]
        bad=ci.bind(graph,node,{'output':value(authorship='unclear')})
        self.assertFalse(scope(b[0],bad)['ready'])

    def test_answer_question_and_fictional_heading_are_indispensable_nonasserted_scope(self):
        left=fixture('Do you want clean air? If yes, adopt road pricing.','a',1)
        right=fixture('Do you want cheaper fuel? If yes, adopt road pricing.','b',1)
        a=scope(*left,links={'ANSWER':'C1'},world='hypothetical')
        b=scope(*right,links={'ANSWER':'C1'},world='hypothetical')
        self.assertFalse(cd.literal_equivalence(a,b)['equivalent'])
        self.assertEqual(cd.packet(a)['dependencies'][0]['role'],'answer_condition')
        f=fixture('Moon Colony! Everyone has food.','f',1)
        real=fixture('Everyone has food.','r')
        sf=scope(*f,links={'SETTING':'C1'},world='fictional')
        self.assertFalse(cd.literal_equivalence(sf,scope(*real))['equivalent'])
        self.assertNotIn('Moon Colony',cd.packet(sf)['assertion'])

    def test_parent_reference_is_not_reply_evidence_and_tampering_is_rejected(self):
        a=fixture('This rule should begin tomorrow.',parent={'id':'p','text':'Archive access should be free.'})
        sa=scope(*a,links={'R1':'C1'});cd.validate(sa)
        self.assertEqual(sa['links'][0]['context']['origin'],'parent')
        self.assertEqual(sa['bundle']['assertion']['text'],'This rule should begin tomorrow.')
        for mutate in (lambda r:r['links'][0]['context']['span'].update(text='Road tolls should be free.'),
                       lambda r:r['bundle']['source']['parent'].update(text='Different.'),
                       lambda r:r['output'].update(world='fictional')):
            changed=deepcopy(sa);mutate(changed)
            with self.assertRaises(ValueError):cd.validate(changed)

    def test_typed_equivalence_replays_and_requires_both_directions(self):
        a=fixture('Garden access should be free because education matters.','a')
        b=fixture('Garden access should be free because inclusion matters.','b')
        sources=[a[0]['meaning_context']['source'],b[0]['meaning_context']['source']];cs=[a[0],b[0]]
        nominations=mm.bind_contextual(sources,cs,[cq.assessment(cw.identity(s,c,i),i,i) for s,(c,i) in zip(sources,(a,b))])
        directions=[]
        for left,right in ((a,b),(b,a)):
            w=cw.scoped_identity(scope(*left),right[0],scope(*right))
            directions.append({'from_candidate_id':left[0]['id'],'to_candidate_id':right[0]['id'],
                               'assessment':cq.assessment(w,left[1],right[1])})
        ids=sorted(c['id'] for c in cs);pairs=[{'a':ids[0],'b':ids[1]}]
        partial=cc.bind_scoped_literal(sources,cs,[nominations],pairs,directions[:1])
        self.assertEqual(partial['relations'][0]['relation'],'uncertain')
        complete=cc.bind_scoped_literal(sources,cs,[nominations],pairs,directions)
        self.assertNotIn('output',complete);self.assertEqual(complete['model_calls'],0)
        merged=cc.consolidate(sources,cs,[nominations],[complete]);self.assertEqual(len(merged['candidates']),1)
        self.assertTrue(merged['final_wording_reassessment_required'])
        changed=deepcopy(complete);changed['relations'][0]['relation']='different'
        with self.assertRaises(ValueError):cc.consolidate(sources,cs,[nominations],[changed])


if __name__=='__main__':unittest.main()
