"""Fidelity audit host controls, not a test of an actual model's accuracy."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_evidence_graph as g, source_evidence_requests as reqs
from commentscope.factory import source_evidence_adapter as adapter, cost_planning as cost
from commentscope.factory.automatic_contract import digest
from test_source_evidence_graph import example, observation_example
from test_source_evidence_pipeline import candidate_output
from test_minimal_factory import extraction, membership
from commentscope.factory import minimal_claims as mc


class SourceFidelityAuditTests(TestCase):
    def verify(self, proposal, output):
        return g.verify(proposal,g.bind_observation(proposal,{'output':output}))

    def test_every_semantic_and_missing_relation_obligation_must_pass(self):
        _,_,_,p,o=example()
        for field in ('boundary_fidelity','typing_fidelity','ownership_fidelity','modality_world_fidelity',
                      'scope_fidelity','qualifiers_complete','reasons_complete','conditions_complete',
                      'premises_complete','concessions_complete'):
            for verdict in ('fail','unknown','unassessed'):
                with self.subTest(field=field,verdict=verdict):
                    value=deepcopy(o);value['unit_observations'][0][field]=verdict
                    self.assertEqual(self.verify(p,value)['status'],'unresolved')
            value=deepcopy(o);del value['unit_observations'][0][field]
            with self.assertRaises(ValueError):self.verify(p,value)

    def test_no_facts_or_proposed_edges_does_not_waive_missing_premise_checks(self):
        _,env,out,_,_=example();out['edges']=[]
        p=g.bind_proposal(env,{'output':out});o=observation_example(p)
        self.assertEqual(self.verify(p,o)['status'],'complete')
        for mutate in (
            lambda x:x['unit_observations'][0].update(premises_complete='unknown'),
            lambda x:x.update(dependency_coverage='unassessed'),
            lambda x:x['missing_edges'].append(dict(from_unit='U2',to_unit='U1',
                relation='required_premise_for',cue_refs=[],interpretation='resolved')),
        ):
            value=deepcopy(o);mutate(value)
            self.assertEqual(self.verify(p,value)['status'],'unresolved')
            self.assertEqual(p['output']['edges'],[])

    def test_audit_inventory_rejects_duplicates_foreign_addresses_and_old_receipts(self):
        _,env,out,p,o=example()
        for version in ('source-evidence-graph-20261111-v1','source-evidence-graph-20261112-v2'):
            old=deepcopy(p);old['artifact_kind']=version+'/proposal'
            with self.assertRaises(ValueError):g.observation_request(old)
        for mutate in (
            lambda x:x['unit_observations'][1].update(unit_id='U1'),
            lambda x:x['edge_observations'][0].update(edge_id='E64'),
            lambda x:x['edge_observations'].clear(),
            lambda x:x.update(observed_edges=[]),
        ):
            value=deepcopy(o);mutate(value)
            with self.assertRaises(ValueError):self.verify(p,value)
        out['edges'][0]['local_id']='invented'
        with self.assertRaises(ValueError):g.bind_proposal(env,{'output':out})
        schema=g.observation_request(p)['schema']['properties']['issues']['items']['properties']['target_ids']['items']
        self.assertEqual(set(schema['enum']),{'s','U1','U2','E1'})

    def test_world_and_strength_are_orthogonal_without_annotator_equality(self):
        _,env,out,_,_=example()
        out['units'][0].update(world='desired',epistemic='categorical')
        # An alternate faithful span annotation is audited, not re-extracted.
        out['units'][0]['scope']['predicate_refs']=[]
        p=g.bind_proposal(env,{'output':out});o=observation_example(p)
        self.assertNotIn('typing',o['unit_observations'][0])
        self.assertEqual(self.verify(p,o)['status'],'complete')
        for world in ('unspecified','unknown'):
            value=deepcopy(out);value['units'][1].update(kind='fact',world=world)
            p=g.bind_proposal(env,{'output':value})
            self.assertEqual(self.verify(p,observation_example(p))['status'],'unresolved')
        value=deepcopy(out);value['units'][1]['epistemic']='desired'
        with self.assertRaises(ValueError):g.bind_proposal(env,{'output':value})

    def test_sparse_workload_covers_every_unit_edge_and_partition_without_pairs(self):
        _,env,out,_,_=example()
        workloads=[]
        for size in (2,29,30,32):
            value=deepcopy(out)
            value['units']+=[dict(deepcopy(out['units'][1]),local_id=f'U{i}') for i in range(3,size+1)]
            value['coverage'][0]['unit_ids']=[u['local_id'] for u in value['units']]
            p=g.bind_proposal(env,{'output':value});work=g.audit_workload(p,candidate_count=9)
            self.assertEqual(work['audit_verdicts'],10*size+1+1+3)
            self.assertEqual(work['candidate_calls'],2)
            self.assertEqual(work['source_calls'],2)
            self.assertFalse(work['semantic_approval']);workloads.append(work)
        self.assertEqual(workloads[2]['audit_verdicts']-workloads[1]['audit_verdicts'],10)
        self.assertNotIn('PAIRS',g.observation_request(p)['data'])


class FidelityCandidateAndCostTests(TestCase):
    def bind(self, source, env, out, candidate=None):
        p=g.bind_proposal(env,{'output':out})
        v=g.verify(p,g.bind_observation(p,{'output':observation_example(p)}))
        cs=mc.candidates(extraction([source],{'s':['Adopt P.']}))
        members=[membership([source],cs,[dict(source_id='s',candidate_id=cs[0]['id'])])]
        output=candidate_output(cs)
        if candidate:output['candidates'][0].update(candidate)
        return reqs.bind_candidates(v,cs,members,{'output':output})

    def test_asserted_nonactual_fact_never_reaches_existing_runtime(self):
        source,env,out,_,_=example()
        for world in ('desired','hypothetical'):
            value=deepcopy(out);value['units'][1].update(kind='fact',world=world)
            record=adapter.lower([self.bind(source,env,value)])
            self.assertEqual(record['status'],'unresolved')
            self.assertIn('nonactual_fact_unrepresentable',record['hold_reasons'])

    def test_reported_nonactual_context_is_not_promoted_or_needlessly_blocked(self):
        source,_,out,_,_=example('Adopt P because fairness matters. They imagine lower costs.')
        env=g.envelope(source,snapshot_id='synthetic',snapshot_sha256=digest('synthetic'),language='en')
        ref=dict(source_id='s',start=source['text'].index('They'),end=len(source['text']))
        context=deepcopy(out['units'][1])
        context.update(local_id='U3',own_spans=[ref],envelope_spans=[ref],kind='fact',
            speech_act='report',commitment='reported_only',world='hypothetical')
        context['scope'].update(subject_refs=[ref],predicate_refs=[ref]);out['units'].append(context)
        out['coverage'][0]['unit_ids'].append('U3')
        record=adapter.lower([self.bind(source,env,out)])
        self.assertEqual(record['status'],'complete')
        unit=record['units'][2]
        self.assertEqual(unit['runtime_exposure'],'scope_annotation_only')
        self.assertEqual(unit['kind'],'uncertain');self.assertEqual(unit['candidate_ids'],[])

    def test_existing_dependency_edge_is_selected_by_id_and_restored_by_host(self):
        source,env,out,_,_=example()
        out['units'][1].update(kind='fact',world='actual')
        edge=dict(local_id='E2',from_unit='U2',to_unit='U1',relation='required_premise_for',cue_refs=[],interpretation='resolved')
        out['edges'].append(edge)
        batch=self.bind(source,env,out,{'dependency_edge_ids':['E2']})
        self.assertEqual(batch['certificates'][0]['output']['dependency_edges'],[edge])
        self.assertEqual(adapter.lower([batch])['status'],'complete')
        for ids in ([],['E2','E2'],['E64']):
            with self.subTest(ids=ids):
                if ids==[]:
                    self.assertEqual(adapter.lower([self.bind(source,env,out,{'dependency_edge_ids':ids})])['status'],'unresolved')
                else:
                    with self.assertRaises(ValueError):self.bind(source,env,out,{'dependency_edge_ids':ids})

    def test_cost_profiles_require_matching_source_evidence_protocol(self):
        import test_factory_cost_plan as cf
        h=cf.CostPlanningTests();h.setUp();h.plan['source_evidence_protocol']=g.VERSION
        counts={**h.work['counts'],**dict.fromkeys(cost.GRAPH_STAGES,6)}
        for protocol in (None,'source-evidence-graph-20261112-v2',g.VERSION):
            profile=deepcopy(h.profile)
            for stage in cost.GRAPH_STAGES:
                profile['stages'][stage]=dict(calls=2,cost_usd='0.002',maximum_cost_usd='0.001',
                    deployment_sha256=digest(cost.deployment(h.plan,stage)),source_evidence_protocol=protocol)
            r=cost.estimate(h.plan,h.candidates,counts,[profile],available_usd='50',goal='development')
            if protocol==g.VERSION:self.assertFalse(set(cost.GRAPH_STAGES)&set(r['unknown_stages']))
            else:
                self.assertTrue(set(cost.GRAPH_STAGES)<=set(r['unknown_stages']))
                self.assertFalse(r['estimated_feasible']);self.assertIsNone(r['estimated_remaining_usd'])
