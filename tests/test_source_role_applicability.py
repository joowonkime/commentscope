"""Role applicability never waives original-content fidelity or factual checks."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_evidence_graph as g, source_evidence_requests as reqs
from commentscope.factory import source_evidence_adapter as adapter, minimal_claims as mc
from test_source_evidence_graph import example, observation_example
from test_source_evidence_pipeline import candidate_output
from test_minimal_factory import extraction, membership


def context_example():
    source,env,out,_,_=example('Adopt P because fairness matters. What next?')
    start=source['text'].index('What');ref=dict(source_id='s',start=start,end=len(source['text']))
    u=deepcopy(out['units'][1]);u.update(local_id='U3',kind='not_applicable',speech_act='question',
        assertion_mode='question',commitment='unclear',epistemic='not_applicable',world='actual',
        own_spans=[ref],envelope_spans=deepcopy(out['units'][0]['envelope_spans']))
    u['scope'].update(subject_refs=[],predicate_refs=[],polarity='unresolved')
    out['units'].append(u);out['coverage'][0]['unit_ids'].append('U3')
    return source,env,out


def verify(env,out,mutate=None):
    p=g.bind_annotation(env,{'output':out});o=observation_example(p)
    if mutate:mutate(o)
    return g.verify(p,g.bind_observation(p,{'output':o}))


class SourceRoleApplicabilityTests(TestCase):
    def test_nonpropositional_question_keeps_raw_unknowns_without_blocking_own_claims(self):
        _,env,out=context_example();before=deepcopy(out);v=verify(env,out)
        self.assertEqual(v['status'],'complete')
        self.assertEqual(v['proposal']['output'],before)
        self.assertEqual(v['verification_policy'],g.VERIFICATION_POLICY)
        q=v['unit_applicability']['U3']
        self.assertEqual(q['role'],'nonpropositional_context')
        self.assertEqual(q['not_applicable_fields'],['commitment','polarity'])
        self.assertEqual(v['unit_applicability']['U1']['not_applicable_fields'],[])

    def test_rhetorical_value_and_ambiguous_real_assertion_keep_their_vetoes(self):
        _,env,out=context_example()
        for changes in (dict(kind='value',epistemic='categorical'),
                        dict(kind='mixed',epistemic='categorical'),
                        dict(kind='fact',epistemic='categorical',speech_act='assertion',assertion_mode='assertion')):
            bad=deepcopy(out);bad['units'][2].update(changes)
            self.assertEqual(verify(env,bad)['status'],'unresolved')
        for key,value in (('commitment','unclear'),('interpretation','unresolved'),('world','unknown'),('speech_act','unresolved')):
            bad=deepcopy(out);bad['units'][0][key]=value
            self.assertEqual(verify(env,bad)['status'],'unresolved')

    def test_nonproposition_still_requires_every_fidelity_obligation(self):
        _,env,out=context_example()
        for field in g.UNIT_CHECKS:
            for verdict in ('fail','unknown','unassessed'):
                with self.subTest(field=field,verdict=verdict):
                    def mutate(o):o['unit_observations'][2][field]=verdict
                    self.assertEqual(verify(env,out,mutate)['status'],'unresolved')

    def test_missing_content_and_unknown_global_scope_still_hold_source(self):
        _,env,out=context_example()
        for mutate in (lambda o:o.update(scope_coverage='unknown'),
                       lambda o:o['coverage_observations'][0].update(no_substantive_omission='fail'),
                       lambda o:o['missing_units'].append(dict(own_spans=out['units'][2]['own_spans'],obligation='interpretation'))):
            self.assertEqual(verify(env,out,mutate)['status'],'unresolved')

    def test_contextual_links_are_retained_but_argumentative_links_are_not_waived(self):
        _,env,out=context_example()
        for relation in ('elaborates','reported_by'):
            linked=deepcopy(out);linked['edges'].append(dict(local_id='E2',from_unit='U2',to_unit='U3',relation=relation,cue_refs=[],interpretation='resolved'))
            self.assertEqual(verify(env,linked)['status'],'complete')
        for relation in ('reason_for','required_premise_for','condition_for','necessary_condition_for','concession_to','opposes','unresolved'):
            linked=deepcopy(out);linked['edges'].append(dict(local_id='E2',from_unit='U3',to_unit='U1',relation=relation,cue_refs=[],interpretation='resolved'))
            self.assertEqual(verify(env,linked)['status'],'unresolved')

    def test_conditional_antecedent_unclear_is_not_reinterpreted_as_inapplicable(self):
        from test_source_condition_qualification import SourceConditionQualificationTests
        _,env,out,_,_,_,_=SourceConditionQualificationTests().conditional()
        out['units'][2]['commitment']='unclear';v=verify(env,out)
        self.assertEqual(v['status'],'unresolved')
        self.assertEqual(v['unit_applicability']['U3']['not_applicable_fields'],[])

    def test_inconsistent_nonproposition_and_stale_policy_are_rejected(self):
        _,env,out=context_example()
        for changes in (dict(epistemic='categorical'),dict(commitment='endorsed'),dict(assertion_mode='quoted_content')):
            bad=deepcopy(out);bad['units'][2].update(changes)
            self.assertEqual(verify(env,bad)['status'],'unresolved')
        v=verify(env,out)
        for mutate in (lambda x:x.pop('verification_policy'),
                       lambda x:x.update(verification_policy='old-policy'),
                       lambda x:x['unit_applicability']['U3']['not_applicable_fields'].clear()):
            bad=deepcopy(v);mutate(bad)
            with self.assertRaises(ValueError):g.validate_verified(bad)

    def test_nonproposition_cannot_be_position_reason_or_runtime_claim(self):
        source,env,out=context_example();v=verify(env,out)
        cs=mc.candidates(extraction([source],{'s':['Adopt P.']}))
        members=[membership([source],cs,[dict(source_id='s',candidate_id=cs[0]['id'])])]
        value=candidate_output(cs)
        normal=adapter.lower([reqs.bind_candidates(v,cs,members,{'output':value})])
        self.assertEqual(normal['status'],'complete')
        q=normal['units'][2];self.assertEqual(q['candidate_ids'],[])
        self.assertEqual(q['runtime_exposure'],'scope_annotation_only')
        for field in ('position_unit_ids','reason_unit_ids','core_required_fact_unit_ids'):
            bad=deepcopy(value);bad['candidates'][0][field]=['U3']
            try:record=adapter.lower([reqs.bind_candidates(v,cs,members,{'output':bad})])
            except ValueError:continue
            self.assertEqual(record['status'],'unresolved')
