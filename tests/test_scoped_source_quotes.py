"""Literal qualification transfer, not model or semantic accuracy tests."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_evidence_graph as g, source_evidence_requests as reqs
from commentscope.factory import source_evidence_adapter as adapter, minimal_claims as mc
from commentscope.factory import scoped_source_quotes as surface
from test_source_evidence_graph import example, observation_example
from test_source_evidence_pipeline import candidate_output
from test_minimal_factory import extraction, membership


def record(text, *, qualifier='I hope', field='modality_refs', kind='value', fail=False, candidate_fail=False, sid='s'):
    source, env, output, _, _ = example(text)
    source['id']=sid
    for u in output['units']:
        for refs in [u['own_spans'],u['envelope_spans'],*[u['scope'][f] for f in g.SCOPE_REFS]]:
            for ref in refs:ref['source_id']=sid
    for edge in output['edges']:
        for ref in edge['cue_refs']:ref['source_id']=sid
    for row in output['coverage']:row['span']['source_id']=sid
    env=g.envelope(source,snapshot_id=env['snapshot_id'],snapshot_sha256=env['snapshot_sha256'],language='en')
    unit = output['units'][0]
    if kind == 'prediction':
        unit.update(kind=kind, speech_act='assertion', world='hypothetical', epistemic='possible')
    elif kind == 'fact':
        unit.update(kind=kind, speech_act='assertion', world='actual')
    ref = dict(source_id=sid, start=text.index(qualifier), end=text.index(qualifier)+len(qualifier))
    unit['scope'][field] = [ref]
    proposal = g.bind_annotation(env, {'output':output})
    observed = observation_example(proposal)
    if fail:observed['unit_observations'][0]['scope_fidelity'] = 'fail'
    verified = g.verify(proposal, g.bind_observation(proposal, {'output':observed}))
    candidates = mc.candidates(extraction([source], {sid:['Adopt P.']}))
    members = [membership([source], candidates, [dict(source_id=sid,candidate_id=candidates[0]['id'])])]
    output = candidate_output(candidates)
    if candidate_fail:output['candidates'][0]['scope_preserved']='fail'
    batch = reqs.bind_candidates(verified, candidates, members, {'output':output})
    return adapter.lower([batch])


class ScopedSourceQuoteTests(TestCase):
    def test_shared_hope_is_preserved_with_visible_omission_and_exact_fragments(self):
        r = record('I hope Q succeeds and Adopt P because fairness matters.')
        self.assertEqual(r['status'], 'complete')
        u = r['units'][0]
        self.assertEqual(u['text'], 'I hope […] Adopt P')
        self.assertEqual([e['text'] for e in u['evidence']], ['I hope','Adopt P'])
        self.assertNotIn('Q succeeds', u['text'])
        self.assertEqual(u['surface']['artifact_kind'], surface.VERSION)
        self.assertEqual(adapter.validate(r), r)

    def test_adjacent_qualifier_and_overlapping_refs_do_not_duplicate_source(self):
        r = record('I hope Adopt P because fairness matters.')
        self.assertEqual(r['units'][0]['text'], 'I hope Adopt P')
        r = record('Adopt P because fairness matters.',qualifier='Adopt',field='quantifier_refs')
        self.assertEqual(r['units'][0]['text'], 'Adopt P')
        self.assertEqual(len(r['units'][0]['evidence']),1)

    def test_prediction_negation_and_unicode_addresses_are_retained(self):
        r = record('🙂 would Q change and Adopt P because fairness matters.',qualifier='would',kind='prediction')
        self.assertEqual(r['units'][0]['text'], 'would […] Adopt P')
        self.assertEqual(r['units'][0]['evidence'][0]['start'],2)
        r = record('not Q but Adopt P because fairness matters.',qualifier='not',field='polarity_refs')
        self.assertEqual(r['units'][0]['text'], 'not […] Adopt P')

    def test_parent_qualifier_and_discontinuous_own_assertion_are_rejected(self):
        _, env, out, _, _ = example()
        unit = out['units'][0]
        unit['scope']['modality_refs'] = [dict(source_id='parent',start=0,end=1)]
        with self.assertRaises(ValueError):surface.quote(env,unit)
        unit['scope']['modality_refs'] = []
        unit['own_spans'] = [dict(source_id='s',start=0,end=5),dict(source_id='s',start=6,end=7)]
        with self.assertRaises(ValueError):surface.quote(env,unit)

    def test_noncontiguous_fact_and_overlong_surface_stay_held(self):
        r = record('I hope Q succeeds and Adopt P because fairness matters.',kind='fact')
        self.assertEqual(r['status'],'unresolved')
        self.assertIn('unrepresentable_hold',r['hold_reasons'])
        r = record('x'*601+' and Adopt P because fairness matters.',qualifier='x'*601)
        self.assertEqual(r['status'],'unresolved')

    def test_surface_and_evidence_mutations_and_prior_artifacts_are_rejected(self):
        r = record('I hope Q and Adopt P because fairness matters.')
        for mutate in (
            lambda x:x['units'][0].update(text='Adopt P'),
            lambda x:x['units'][0]['evidence'].pop(),
            lambda x:x['units'][0]['surface']['qualifier_refs'].clear(),
            lambda x:x.update(artifact_kind=g.VERSION+'/arguments'),
        ):
            bad=deepcopy(r);mutate(bad)
            with self.assertRaises(ValueError):adapter.validate(bad)

    def test_qualifiers_after_claim_remain_in_source_order(self):
        r = record('Adopt P perhaps because fairness matters.',qualifier='perhaps')
        self.assertEqual(r['units'][0]['text'],'Adopt P perhaps')

    def test_semantic_veto_is_never_cleared_by_surface_rendering(self):
        r = record('I hope Adopt P because fairness matters.',fail=True)
        self.assertEqual(r['status'],'unresolved')
        r = record('I hope Adopt P because fairness matters.',candidate_fail=True)
        self.assertEqual(r['status'],'unresolved')
        self.assertIn('candidate_obligations_unresolved',r['hold_reasons'])

    def test_compiler_preserves_shared_qualifier_and_individual_source_counts(self):
        from dataclasses import replace
        from pathlib import Path
        from commentscope.ingestion import load_snapshot
        from commentscope.factory import source_arguments as sa, minimal_agents as ma, argument_observations as obs
        from experiments.grounding_contract_demo import MODEL
        records=[record('I hope Q'+str(i)+' and Adopt P because fairness matters.',sid='s'+str(i)) for i in range(3)]
        sources=[r['source'] for r in records]
        candidates=mc.candidates(extraction(sources,{s['id']:['Adopt P.'] for s in sources}))
        members=[membership(sources,candidates,[dict(source_id=s['id'],candidate_id=candidates[0]['id']) for s in sources])]
        core=sa.bind_core(candidates[0],{'output':dict(kind='value',scope=dict(entity='P',time='',conditions=''))})
        check=obs.bind_core(core,{'output':{'observations':[dict(actual_kind='value',time_ids=[],entity_fidelity='yes',conditions_fidelity='yes',basis='Source assertion.')]}})
        audit=adapter.audit(records,[core],[check])
        template=load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        snapshot=replace(template,usage=replace(template.usage,expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(template.comments[0],comment_id=s['id'],text_original=s['text'],parent_id=None) for s in sources))
        out=ma.prepare(snapshot,candidates,members,records,[core],[audit],model=MODEL)
        profile=out['compiled']['profiles'][0]
        qualified=[r for r in profile['prompt_entries'] if r['text']=='I hope […] Adopt P']
        self.assertEqual(profile['model_core_support_count'],3)
        self.assertEqual(len(qualified),3)
        self.assertTrue(all(r['member_source_count']==1 for r in qualified))
        self.assertTrue(all(r['epistemic_status']=='attributed_value_not_verified_fact' for r in qualified))
        self.assertFalse(out['runtime_verified'])

    def test_condition_annotation_transfers_its_own_qualifiers_to_dependent_scope(self):
        from test_source_condition_qualification import SourceConditionQualificationTests
        h=SourceConditionQualificationTests()
        source,env,out,_,cs,members,response=h.conditional(cue='If perhaps funded')
        def ref(part):
            start=source['text'].index(part)
            return dict(source_id='s',start=start,end=start+len(part))
        u=out['units'][2]
        u.update(kind='prediction',speech_act='assertion',epistemic='possible',own_spans=[ref('funded')])
        u['scope'].update(modality_refs=[ref('perhaps')],world_refs=[ref('If')])
        p=g.bind_annotation(env,{'output':out})
        v=g.verify(p,g.bind_observation(p,{'output':observation_example(p)}))
        lowered=adapter.lower([reqs.bind_candidates(v,cs,members,{'output':response})])
        self.assertEqual(lowered['status'],'complete')
        self.assertEqual(lowered['units'][0]['scope']['conditions'],'If perhaps funded')
        self.assertEqual(lowered['units'][2]['runtime_exposure'],'scope_annotation_only')
