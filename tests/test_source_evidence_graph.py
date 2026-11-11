"""Scripted source evidence tests; no semantic or model accuracy claim."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_evidence_graph as graph
from commentscope.factory.automatic_contract import digest


def observation_example(proposal):
    out=proposal['output']
    return dict(unit_observations=[dict(unit_id=u['local_id'],typing={k:deepcopy(u[k]) for k in graph.SEMANTIC_FIELDS},
        boundary_fidelity='pass',qualifiers_complete='pass',issue_codes=[]) for u in out['units']],
        observed_edges=deepcopy(out['edges']),coverage_observations=[dict(coverage_index=str(i),no_substantive_omission='pass',
        missing_refs=[],issue_codes=[]) for i in range(len(out['coverage']))],missing_units=[],scope_coverage='pass',
        ownership_coverage='pass',dependency_coverage='pass',issues=[],source_language='en')


def example(text='Adopt P because fairness matters.'):
    source = {'id': 's', 'text': text, 'parent': None}
    envelope = graph.envelope(source, snapshot_id='synthetic', snapshot_sha256=digest('synthetic'), language='en')
    def span(fragment):
        start = text.index(fragment)
        return {'source_id': 's', 'start': start, 'end': start+len(fragment)}
    units = []
    for lid, fragment in [('U1', 'Adopt P'), ('U2', 'fairness matters')]:
        refs = [span(fragment)]
        scope = {key: [] for key in graph.SCOPE_REFS}
        scope.update(subject_refs=refs, predicate_refs=refs, polarity='affirmative', change_or_state='neither')
        units.append(dict(local_id=lid, own_spans=refs, envelope_spans=[span(text)],
                          speech_act='preference', kind='value', commitment='endorsed',
                          epistemic='categorical', assertion_mode='assertion', scope=scope, interpretation='resolved'))
    output = dict(units=units, edges=[dict(local_id='E1', from_unit='U2', to_unit='U1',
        relation='reason_for', cue_refs=[span('because')], interpretation='resolved')],
        coverage=[dict(span=span(text), disposition='represented', unit_ids=['U1', 'U2'], reason_code='represented')], issues=[])
    proposal = graph.bind_proposal(envelope, {'output': output})
    observation = observation_example(proposal)
    return source, envelope, output, proposal, observation


class SourceEvidenceGraphTests(TestCase):
    def test_exact_source_and_independent_observation_are_required(self):
        _, env, _, proposal, output = example()
        request = graph.observation_request(proposal)
        self.assertNotIn('commitment', request['data']['UNITS'][0])
        self.assertNotIn('edges', request['data'])
        self.assertNotIn('CANDIDATES', request['data'])
        observed = graph.bind_observation(proposal, {'output': output})
        verified = graph.verify(proposal, observed)
        self.assertEqual(verified['status'], 'complete')
        self.assertEqual(graph.validate_verified(verified), verified)
        changed = deepcopy(verified); changed['proposal']['source']['text'] += 'changed'
        with self.assertRaises(ValueError): graph.validate_verified(changed)
        self.assertEqual(env['source']['text'], 'Adopt P because fairness matters.')

    def test_disagreement_missing_premise_and_scope_loss_hold_full_source(self):
        _, _, _, proposal, output = example()
        for mutate in [
            lambda x: x['unit_observations'][0]['typing'].update(kind='prediction'),
            lambda x: x.update(dependency_coverage='unknown'),
            lambda x: x['coverage_observations'][0].update(no_substantive_omission='fail'),
            lambda x: x['missing_units'].append({'own_spans': proposal['output']['units'][0]['own_spans'], 'obligation':'dependency'}),
            lambda x: x.update(observed_edges=[]),
        ]:
            value = deepcopy(output); mutate(value)
            result = graph.verify(proposal, graph.bind_observation(proposal, {'output':value}))
            self.assertEqual(result['status'], 'unresolved')

    def test_foreign_parent_evidence_unicode_and_uncovered_text_are_not_silently_fixed(self):
        _, env, output, _, _ = example()
        for mutate in [
            lambda x: x['units'][0]['own_spans'][0].update(source_id='parent'),
            lambda x: x['coverage'][0]['span'].update(end=10),
            lambda x: x['units'].append(deepcopy(x['units'][0])),
            lambda x: x['units'][0]['own_spans'][0].update(start=True),
        ]:
            value = deepcopy(output); mutate(value)
            with self.assertRaises(ValueError): graph.bind_proposal(env, {'output': value})
        _, _, _, proposal, _ = example('🙂 Adopt P because fairness matters.')
        self.assertEqual(graph.literal(proposal['envelope'], proposal['output']['units'][0]['own_spans']), 'Adopt P')

    def test_capacity_and_observation_coverage_are_closed(self):
        _, env, output, proposal, observed = example()
        invalid = deepcopy(output); invalid['units'] = [dict(output['units'][0], local_id=f'U{i}') for i in range(1,34)]
        with self.assertRaises(ValueError): graph.bind_proposal(env, {'output':invalid})
        for key in ['unit_observations','coverage_observations']:
            value=deepcopy(observed);value[key].pop()
            with self.assertRaises(ValueError): graph.bind_observation(proposal, {'output':value})

    def test_condition_and_dependency_cycle_cannot_be_dropped(self):
        _, env, output, _, _ = example()
        output['edges'] = [dict(local_id='E1',from_unit='U1',to_unit='U2',relation='required_premise_for',cue_refs=[],interpretation='resolved'),
                           dict(local_id='E2',from_unit='U2',to_unit='U1',relation='necessary_condition_for',cue_refs=[],interpretation='resolved')]
        p=graph.bind_proposal(env,{'output':output});o=graph.bind_observation(p,{'output':observation_example(p)})
        self.assertEqual(graph.verify(p,o)['status'],'unresolved')

    def test_schema_rejects_unknown_keys_empty_receipts_and_non_applicable_assertion(self):
        _, env, output, proposal, _ = example()
        for mutate in [lambda x:x.update(approved=True),lambda x:x['units'][0].update(kind='not_applicable')]:
            x=deepcopy(output);mutate(x)
            with self.assertRaises(ValueError):graph.bind_proposal(env,{'output':x})
        with self.assertRaises(ValueError):graph.bind_observation(proposal,{'output':{}})
