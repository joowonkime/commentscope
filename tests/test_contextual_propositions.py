from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from commentscope.factory import contextual_propositions as cp, contextual_witness as cw
from commentscope.factory import contextual_interpretation as ci
from commentscope.factory import minimal_claims as mc, minimal_membership as mm, explicit_discourse as ed
from commentscope.factory import literal_discovery as ld, owned_arguments as oa, candidate_consolidation as cc
from commentscope.factory.automatic_contract import digest
from experiments.minimal_discovery_probe import extract
from test_minimal_factory import membership


def selected(source,roles=None):
    graph=ed.parse(source);ids=[n['id'] for n in ld.roots(graph)]
    req=ld.selection_request(graph,ids)
    value={t['id']:{'role':(roles or {}).get(t['id'],'topic_position'),'speaker':'comment_author'} for t in req['data']['TARGETS']}
    return cp.assemble(graph,[ld.bind_selection(graph,ids,{'output':value})])


def original(text,sid='s',parent=None):return {'id':sid,'text':text,'parent':parent}


def positive(source,candidate,position='P1'):
    return cw.bind(source,candidate,{'output':{'position':position,'relation':'supported',
        'authorship':'asserted_or_endorsed','scope':'complete','topic':'relevant'}})


class ContextualPropositionTests(unittest.TestCase):
    def test_literal_rule_and_referent_are_not_conflated_across_topics(self):
        for topic in ('park fees','lab reviews','school meals','film ratings','road pricing'):
            r=selected(original(f'{topic} should be mandatory. This rule should start tomorrow.'))
            self.assertEqual(r['claims'][1]['text'],'This rule should start tomorrow.')
            candidates=mc.candidates([r]);c=next(c for c in candidates if c['text'].startswith('This'))
            p=mc.candidate_packet(c)['BOUND_MEANING']
            self.assertIn(f'{topic} should be mandatory.',p['INTERPRETATION_CONTEXT_ONLY']['comment_text'])
            self.assertNotIn('mandatory',p['assertion']['text'])
            self.assertTrue(p['context_is_not_an_asserted_conjunction']);cp.validate(r)

    def test_possession_complement_relative_and_typos_are_never_rewritten(self):
        texts=['Every gardener chooses their tools.','The truth is that most workers are tired.',
               'A policy that improves lives is needed.','Its not looking well.',
               '추가 비용이 없을 때만 이 계획에 찬성합니다.']
        for text in texts:
            r=selected(original(text));self.assertEqual(r['claims'][0]['text'],text)
            self.assertEqual(r['claims'][0]['evidence'][0]['text'],text)

    def test_setting_is_context_not_literal_assertion_or_evidence(self):
        r=selected(original('Moon Colony! Everyone has food. Taxes are low.'),{'N1':'framing_context'})
        c=mc.candidates([r])[0];p=mc.candidate_packet(c)['BOUND_MEANING']
        self.assertNotIn('Moon Colony',c['text'])
        self.assertEqual(p['INTERPRETATION_CONTEXT_ONLY']['setting_proposals'][0]['text'],'Moon Colony!')
        self.assertEqual(len(r['claims']),2)
        r=selected(original('Ban Cars! Build Trams.'))
        self.assertEqual(r['claims'][0]['text'],'Ban Cars!')

    def test_parent_is_never_reply_text_or_evidence_and_reference_only_is_held(self):
        parent={'id':'p','text':'Prices increase.'}
        r=selected(original('Deal with it.',parent=parent));c=r['claims'][0]
        self.assertEqual(c['text'],'Deal with it.')
        self.assertEqual(c['evidence'],[{'start':0,'end':13,'text':'Deal with it.'}])
        self.assertEqual(mc.candidate_packet(mc.candidates([r])[0])['BOUND_MEANING']['INTERPRETATION_CONTEXT_ONLY']['PARENT_CONTEXT_ONLY'],parent)
        for text in ('This','That!','It.'):
            r=selected(original(text,parent=parent));self.assertFalse(r['claims'])
            self.assertEqual(r['holds'][0]['reason'],'reference_without_independent_speech_act')

    def test_answer_condition_and_independent_request_are_not_asserted_as_core(self):
        r=selected(original('Do you want clean air? Reduce fares. If yes, adopt road pricing.'))
        c=next(c for c in mc.candidates([r]) if c['text'].startswith('If yes'))
        self.assertEqual(c['text'],'If yes, adopt road pricing.')
        b=c['meaning_context'];question=b['scope_inventory']['answer_condition']['question']
        self.assertEqual(question['text'],'Do you want clean air?')
        self.assertNotIn('Reduce fares',b['assertion']['text'])

    def test_reason_parent_fixed_while_context_is_not_membership_requirement(self):
        r=selected(original('Preserve the archive. Open on Sunday because weekdays are busy.'))
        c=next(c for c in mc.candidates([r]) if c['text']=='Open on Sunday')
        p=mc.candidate_packet(c)['BOUND_MEANING']
        self.assertEqual(p['OWNED_RELATIONS'][0]['ground']['text'],'because weekdays are busy.')
        self.assertNotIn('archive',c['text']);self.assertNotIn('weekdays',c['text'])

    def test_same_literal_different_context_cannot_reuse_identity_or_vote(self):
        a=selected(original('This is expensive.',parent={'id':'p','text':'Road pricing.'}))
        b=selected(original('This is expensive.',parent={'id':'p','text':'School meals.'}))
        ca=mc.candidates([a])[0];cb=mc.candidates([b])[0]
        self.assertEqual(ca['text'],cb['text']);self.assertNotEqual(ca['id'],cb['id'])
        self.assertNotEqual(ca['id'],mc.claim_id(ca['text']))
        witness=positive(a['source'],ca);changed=deepcopy(witness);changed['candidate']=cb
        with self.assertRaises(ValueError):cw.validate(changed)

    def test_source_node_condition_context_or_text_mutation_rejected(self):
        r=selected(original('Adopt the plan only if funded. Keep fees low.'));c=mc.candidates([r])[0]
        for mutate in (lambda x:x.update(text='An invented assertion.'),
                       lambda x:x['meaning_context']['source'].update(text='Other context.'),
                       lambda x:x['meaning_context'].update(node_id='invented'),
                       lambda x:x['meaning_context']['scope_inventory'].update(references=[]),
                       lambda x:x['meaning_context'].update(owned_edges=[])):
            changed=deepcopy(c);mutate(changed)
            if changed!=c:
                with self.assertRaises((ValueError,KeyError)):mc.validate_candidate(changed)

    def test_legacy_membership_cannot_approve_context_with_bare_text_qualification(self):
        r=selected(original('Adopt the plan.'));c=mc.candidates([r])[0]
        pairs=[{'source_id':'s','candidate_id':c['id']}]
        req=mm.membership_request([r['source']],[c],pairs)
        self.assertEqual(req['data']['PAIRS'][0]['CANDIDATE'],mc.candidate_packet(c))
        b=membership([r['source']],[c],pairs)
        self.assertEqual(b['memberships'][0]['relation'],'uncertain')
        self.assertIn('contextual_position_witness_unassessed',b['memberships'][0]['guards'])
        self.assertEqual(mm.collect([r['source']],[c],[b])[0]['relation'],'uncertain')
        with self.assertRaises(ValueError):cc.equivalence_request([r['source']],[c],[b],[{'a':c['id'],'b':c['id']}])
        core=oa.bind_core(c,{'output':{'kind':'value','entity':'plan','time_ids':[]}})
        self.assertIn('contextual_runtime_adapter_unassessed',core['hold_reasons'])

    def test_typed_position_guards_false_model_prediction_time_and_condition(self):
        target=mc.candidates([selected(original('We need the plan now.','target'))])[0]
        cases=[('The plan will raise prices.','forecast_or_possibility_is_not_a_demand'),
               ('We need the plan.','candidate_time_absent_from_position'),
               ('If funded, we need the plan now.','condition_presence_mismatch')]
        for text,guard in cases:
            w=positive(original(text),target)
            self.assertEqual(w['relation'],'uncertain');self.assertIn(guard,w['guards'])
            self.assertFalse(w['counted_support']);cw.validate(w)
        w=positive(original('We need the plan now.'),target,'unresolved')
        self.assertIn('no_own_position_witness',w['guards'])

    def test_same_author_cannot_transfer_a_different_position_into_self_nomination(self):
        for text in ('Some people say "Adopt road pricing." I disagree: keep roads free.',
                     'Adopt park fees. Accountability matters.',
                     'Require school meals. Keep film ratings voluntary.'):
            r=selected(original(text));c=next(c for c in mc.candidates([r]) if c['meaning_context']['node_id']==ld.roots(r['graph'])[0]['id'])
            w=positive(r['source'],c,'P2')
            self.assertEqual(w['relation'],'uncertain')
            self.assertIn('self_nomination_requires_original_assertion_node',w['guards'])
            cw.validate(w)
            changed=deepcopy(r['source']);changed['parent']={'id':'p','text':'Changed context.'}
            with self.assertRaises(ValueError):cw.request(changed,c)

    def test_contextual_probe_runs_real_comparison_interface_not_just_storage(self):
        class Runner:
            def __init__(self):self.calls=[]
            def call(self,stage,req):
                self.calls.append(req)
                if 'SOURCE_CONTEXT' in req['data']:
                    value={'function':'stance','authorship':'author','topic_relation':'direct','scope':'complete','attribution_cue':'none'}
                else:
                    self.assertion=req['data']['CANDIDATE']['BOUND_MEANING']['assertion']
                    pos=next(n['id'] for n in req['data']['POSITIONS'] if n['span']==self.assertion)
                    value={'position':pos,'relation':'supported','authorship':'asserted_or_endorsed','scope':'complete','topic':'relevant'}
                return {'output':value,'raw':'scripted','errors':[]}
        runner=Runner()
        with TemporaryDirectory() as tmp:
            result=extract(Path(tmp),runner,[original('Reviews are required. This rule should start tomorrow.')],
                inspect=lambda req:{'request_sha256':digest(req),'fits':True},mode='contextual')
        self.assertEqual(len(runner.calls),2);self.assertEqual(len(result['position_witnesses']),2)
        self.assertEqual(result['counted_contextual_supports'],0);self.assertFalse(result['quality_gate_passed'])
        self.assertEqual(result['extractions'][0]['claims'][1]['text'],'This rule should start tomorrow.')

    def test_all_fixed_positions_exist_before_relevance_and_failures_do_not_erase_neighbors(self):
        source=original('Meal planning takes time. Book an appointment with my adviser. I dislike waste.')
        graph=ed.parse(source);nodes=ld.roots(graph)
        records=[ci.bind(graph,n,{'output':{'function':'promotion' if i==1 else 'personal_experience',
            'authorship':'author','topic_relation':'indirect','scope':'complete','attribution_cue':'none'}}) for i,n in enumerate(nodes)]
        r=cp.assemble_interpreted(graph,records)
        self.assertEqual(len(r['position_bundles']),3);self.assertEqual(len(r['claims']),2)
        self.assertEqual(r['excluded_node_ids'],[nodes[1]['id']]);cp.validate(r)
        r=cp.assemble_interpreted(graph,records[:1]+records[2:])
        self.assertEqual(len(r['position_bundles']),3);self.assertEqual(len(r['claims']),2)
        self.assertEqual(r['holds'][0]['reason'],'unassessed_position');self.assertEqual(r['status'],'partial')

    def test_function_and_scope_cannot_be_overridden_by_generic_topic_yes(self):
        graph=ed.parse(original('A service testimonial.'));node=ld.roots(graph)[0]
        for role in ('promotion','creator_or_platform','conversation'):
            r=cp.assemble_interpreted(graph,[ci.bind(graph,node,{'output':{
                'function':role,'authorship':'author','topic_relation':'direct','scope':'complete','attribution_cue':'none'}})])
            self.assertFalse(mc.candidates([r]));self.assertEqual(r['status'],'non_substantive')
        r=cp.assemble_interpreted(graph,[ci.bind(graph,node,{'output':{
            'function':'stance','authorship':'author','topic_relation':'direct','scope':'unresolved','attribution_cue':'none'}})])
        self.assertFalse(r['claims']);self.assertEqual(r['status'],'unresolved')

    def test_interpretation_has_no_assertion_text_output_and_cannot_change_sources(self):
        graph=ed.parse(original('I dislike food waste.'));node=ld.roots(graph)[0]
        value={'function':'personal_experience','authorship':'author','topic_relation':'indirect','scope':'complete','attribution_cue':'none'}
        with self.assertRaises(ValueError):ci.bind(graph,node,{'output':{**value,'text':'I support another policy.'}})
        record=ci.bind(graph,node,{'output':value});changed=deepcopy(record);changed['node_id']='other'
        with self.assertRaises(ValueError):cp.assemble_interpreted(graph,[changed])


if __name__=='__main__':unittest.main()
