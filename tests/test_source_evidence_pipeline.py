from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_evidence_graph as g, source_evidence_requests as reqs
from commentscope.factory import source_evidence_adapter as adapter, minimal_claims as mc
from commentscope.factory import argument_observations as obs, raw_membership_verification as verification
from commentscope.factory import cost_planning as cost, minimal_pipeline
from commentscope.providers import remote_verification
from test_source_evidence_graph import example, observation_example
from test_minimal_factory import extraction, membership
from test_jev_membership import JevRunner
import test_minimal_pipeline as fixture


def candidate_output(candidates):
    return {'candidates':[dict(candidate_id=c['id'],position_unit_ids=['U1'],alignment='supports_core',
        reason_unit_ids=['U2'],concession_unit_ids=[],essential_condition_unit_ids=[],dependency_edge_ids=[],core_required_fact_unit_ids=[],
        full_original_coverage='pass',ownership='pass',scope_preserved='pass',issue_codes=[]) for c in candidates]}

def scoped_output(candidates):
    output=candidate_output(candidates)
    for row in output['candidates']:
        row['candidate_original_coverage']=row.pop('full_original_coverage')
        row.update(reference_unit_ids=[],elaboration_unit_ids=[])
    return output


class CandidateEvidenceTests(TestCase):
    def setUp(self):
        source,_,_,p,o=example();self.verified=g.verify(p,g.bind_observation(p,{'output':o}))
        self.cs=mc.candidates(extraction([source],{'s':['Adopt P.']}))
        self.members=[membership([source],self.cs,[dict(source_id='s',candidate_id=self.cs[0]['id'])])]

    def bind(self,value):return reqs.bind_candidates(self.verified,self.cs,self.members,{'output':value})

    def test_represented_status_cannot_become_a_candidate_error_or_override_failure(self):
        value=candidate_output(self.cs);value['candidates'][0]['issue_codes']=['represented']
        self.assertEqual(adapter.lower([self.bind(value)])['status'],'complete')
        value['candidates'][0]['scope_preserved']='unknown'
        self.assertEqual(adapter.lower([self.bind(value)])['status'],'unresolved')
        value['candidates'][0]['scope_preserved']='pass'
        value['candidates'][0]['issue_codes'].append('scope_unresolved')
        self.assertEqual(adapter.lower([self.bind(value)])['status'],'unresolved')

    def test_literal_reason_and_provenance_reach_new_record(self):
        batch=self.bind(candidate_output(self.cs));record=adapter.lower([batch])
        self.assertEqual(record['status'],'complete');self.assertEqual(record['artifact_kind'],adapter.VERSION)
        self.assertEqual([u['text'] for u in record['units']],['Adopt P','fairness matters'])
        self.assertEqual(adapter.validate(record),record)
        bad=deepcopy(record);bad['units'][1]['text']='invented reason'
        with self.assertRaises(ValueError):adapter.validate(bad)
        data=reqs.candidate_request(self.verified,self.cs)['data']
        self.assertNotIn('supported',str(data))

    def test_reason_omission_scope_and_core_premise_promotion_hold(self):
        for mutate in [lambda x:x['candidates'][0].update(reason_unit_ids=[]),
                       lambda x:x['candidates'][0].update(scope_preserved='unknown')]:
            value=candidate_output(self.cs);mutate(value)
            self.assertEqual(adapter.lower([self.bind(value)])['status'],'unresolved')
        value=candidate_output(self.cs);value['candidates'][0]['core_required_fact_unit_ids']=['U2']
        with self.assertRaises(ValueError):self.bind(value)

    def test_stale_source_membership_missing_candidate_and_mixed_receipts_fail(self):
        value=candidate_output(self.cs);value['candidates']=[]
        with self.assertRaises(ValueError):self.bind(value)
        batch=self.bind(candidate_output(self.cs));bad=deepcopy(batch);bad['response']['candidates'][0]['alignment']='equivalent'
        with self.assertRaises(ValueError):reqs.validate_batch(bad)

    def test_local_factual_premise_stays_with_reason_and_cannot_be_removed(self):
        from commentscope.factory.automatic_contract import digest
        _,_,out,_,_=example()
        source={'id':'s','text':'Adopt P because fairness matters. Costs are high.','parent':None}
        env=g.envelope(source,snapshot_id='synthetic',snapshot_sha256=digest('synthetic'),language='en')
        fact=deepcopy(out['units'][1]);fact.update(local_id='U3',kind='fact',world='actual',speech_act='assertion')
        ref=dict(source_id='s',start=source['text'].index('Costs'),end=len(source['text']))
        fact.update(own_spans=[ref],envelope_spans=[ref]);fact['scope'].update(subject_refs=[ref],predicate_refs=[ref])
        out['units'].append(fact);out['coverage'][0]['span']['end']=len(source['text']);out['coverage'][0]['unit_ids'].append('U3')
        edge=dict(local_id='E2',from_unit='U3',to_unit='U2',relation='required_premise_for',cue_refs=[],interpretation='resolved')
        out['edges'].append(edge)
        p=g.bind_annotation(env,{'output':out});v=g.verify(p,g.bind_observation(p,{'output':observation_example(p)}))
        members=[membership([source],self.cs,[dict(source_id='s',candidate_id=self.cs[0]['id'])])]
        output=candidate_output(self.cs);output['candidates'][0]['dependency_edge_ids']=[edge['local_id']]
        b=reqs.bind_candidates(v,self.cs,members,{'output':output});record=adapter.lower([b])
        self.assertEqual(record['status'],'complete')
        self.assertEqual(record['units'][1]['requires'],['U3'])
        self.assertEqual(record['units'][2]['core_requires_for'],[])
        output['candidates'][0]['dependency_edge_ids']=[]
        self.assertEqual(adapter.lower([reqs.bind_candidates(v,self.cs,members,{'output':output})])['status'],'unresolved')

    def test_discontinuous_or_external_qualifier_is_held_instead_of_rewritten(self):
        _,env,out,_,_=example()
        ref=deepcopy(out['units'][0]['own_spans'][0]);ref['end']=5
        out['units'][0]['own_spans']=[ref,dict(source_id='s',start=6,end=7)]
        p=g.bind_annotation(env,{'output':out});v=g.verify(p,g.bind_observation(p,{'output':observation_example(p)}))
        b=reqs.bind_candidates(v,self.cs,self.members,{'output':candidate_output(self.cs)})
        record=adapter.lower([b]);self.assertEqual(record['status'],'unresolved')
        self.assertIn('unrepresentable_hold',record['hold_reasons'])

    def test_antecedent_is_scope_only_and_nested_condition_never_flattens(self):
        from commentscope.factory.automatic_contract import digest
        _,_,out,_,_=example()
        source={'id':'s','text':'Adopt P because fairness matters. If funded. Unless Q.','parent':None}
        env=g.envelope(source,snapshot_id='synthetic',snapshot_sha256=digest('synthetic'),language='en')
        for lid,fragment in [('U3','If funded.'),('U4','Unless Q.')]:
            ref=dict(source_id='s',start=source['text'].index(fragment),end=source['text'].index(fragment)+len(fragment))
            unit=deepcopy(out['units'][1]);unit.update(local_id=lid,kind='fact',world='hypothetical',assertion_mode='conditional_antecedent',own_spans=[ref],envelope_spans=[ref])
            unit['scope'].update(subject_refs=[ref],predicate_refs=[ref]);out['units'].append(unit)
        out['coverage'][0]['span']['end']=len(source['text']);out['coverage'][0]['unit_ids']+=['U3','U4']
        last=out['units'].pop();out['coverage'][0]['unit_ids'].remove('U4')
        first=dict(local_id='E2',from_unit='U3',to_unit='U1',relation='condition_for',cue_refs=[],interpretation='resolved')
        out['edges'].append(first)
        members=[membership([source],self.cs,[dict(source_id='s',candidate_id=self.cs[0]['id'])])]
        def lower():
            p=g.bind_annotation(env,{'output':out});v=g.verify(p,g.bind_observation(p,{'output':observation_example(p)}))
            value=candidate_output(self.cs);value['candidates'][0].update(essential_condition_unit_ids=[e['from_unit'] for e in out['edges'] if e['relation'] in g.CONDITION_RELATIONS],dependency_edge_ids=[e['local_id'] for e in out['edges'] if e['relation'] in g.CONDITION_RELATIONS])
            return adapter.lower([reqs.bind_candidates(v,self.cs,members,{'output':value})])
        simple=lower();self.assertEqual(simple['status'],'complete')
        self.assertEqual(simple['units'][2]['runtime_exposure'],'scope_annotation_only')
        self.assertEqual(simple['units'][0]['scope']['conditions'],'If funded.')
        out['units'].append(last);out['coverage'][0]['unit_ids'].append('U4')
        out['edges'].append(dict(first,local_id='E3',from_unit='U4',to_unit='U3'))
        nested=lower();self.assertIn('unrepresentable_hold',nested['hold_reasons']);self.assertEqual(nested['status'],'unresolved')


class ScopedEvidenceTests(TestCase):
    def setUp(self):
        self.source,self.env,self.output,_,_=example('Adopt P because fairness matters. P is the local bus plan. More riders benefit.')
        for lid,text in [('U3','P is the local bus plan.'),('U4','More riders benefit.')]:
            start=self.source['text'].index(text)
            ref=dict(source_id='s',start=start,end=start+len(text))
            unit=deepcopy(self.output['units'][1])
            unit.update(local_id=lid,own_spans=[ref],envelope_spans=[ref])
            unit['scope'].update(subject_refs=[ref],predicate_refs=[ref])
            self.output['units'].append(unit)
            self.output['coverage'][0]['unit_ids'].append(lid)
        self.output['edges'].append(dict(local_id='E2',from_unit='U4',to_unit='U1',
                                          relation='elaborates',cue_refs=[],interpretation='resolved'))
        self.candidate={**mc.candidates(extraction([self.source],{'s':['Adopt P.']}))[0],'qualifications':[]}

    def bind(self, *, observe=None, edit=None, second_segment=False):
        proposal=g.bind_annotation(self.env,{'output':self.output})
        observation=observation_example(proposal)
        if observe:observe(observation)
        verified=g.verify(proposal,g.bind_observation(proposal,{'output':observation}))
        candidates=[self.candidate]
        pairs=[dict(source_id='s',candidate_id=self.candidate['id'])]
        evidence={'s':{'evidence_segment_ids':['S000','S001']}} if second_segment else None
        support=[membership([self.source],candidates,pairs,evidence)]
        response=scoped_output(candidates)
        row=response['candidates'][0]
        row['elaboration_unit_ids']=['U4']
        if edit:edit(row)
        return reqs.bind_candidates(verified,candidates,support,{'output':response})

    def test_only_local_unrelated_error_can_be_scoped_away(self):
        def fail_at(idx):return lambda o:o['unit_observations'][idx].update(typing_fidelity='fail')
        unrelated=self.bind(observe=fail_at(2))
        self.assertEqual(unrelated['verified']['status'],'unresolved')
        lowered=adapter.validate(adapter.lower([unrelated]))
        self.assertEqual(lowered['status'],'complete')
        self.assertEqual([u['local_id'] for u in lowered['units']],['U1','U2','U4'])
        self.assertEqual(lowered['units'][-1]['role'],'additional_position')
        for observation in (fail_at(1),fail_at(3),lambda o:o.update(dependency_coverage='unknown')):
            record=adapter.lower([self.bind(observe=observation)])
            self.assertEqual(record['status'],'unresolved')
            self.assertFalse(record['candidate_ids'])

    def test_reference_is_cited_context_and_never_becomes_a_core_fact(self):
        choose=lambda row:row.update(reference_unit_ids=['U3'])
        blocked=adapter.lower([self.bind(edit=choose)])
        self.assertIn('candidate_reference_unverified',blocked['hold_reasons'])
        accepted=adapter.lower([self.bind(edit=choose,second_segment=True)])
        self.assertEqual(accepted['status'],'complete')
        self.assertTrue(all(u['local_id']!='U3' and not u['core_requires_for'] for u in accepted['units']))
        blocked=adapter.lower([self.bind(edit=choose,second_segment=True,
                               observe=lambda o:o['unit_observations'][2].update(typing_fidelity='fail'))])
        self.assertIn('source_graph_unresolved',blocked['hold_reasons'])

    def test_omitting_connected_reason_or_elaboration_holds(self):
        for field in ('reason_unit_ids','elaboration_unit_ids'):
            record=adapter.lower([self.bind(edit=lambda row:row.update({field:[]}))])
            self.assertIn('candidate_inventory_incomplete',record['hold_reasons'])


class GraphRunner(JevRunner):
    def __init__(self,*,bad_graph=False,drop_reason=False,veto=False):
        super().__init__(veto=veto);self.bad_graph=bad_graph;self.drop_reason=drop_reason;self.proposals={}
    def call(self,stage,request):
        data=request['data'];system=request['system']
        if system.startswith(g.PROPOSE):
            packet=data['ORIGINAL'];text=''.join(s['text'] for s in packet['ORIGINAL_SEGMENTS']);sid=packet['source_id']
            source={'id':sid,'text':text,'parent':packet['PARENT_CONTEXT_ONLY']}
            # Authored fixture for this small corpus, never a semantic heuristic in production.
            _,_,out,_,_=example()
            a,b=text.split(' because ')
            def span(part):return dict(source_id=sid,start=text.index(part),end=text.index(part)+len(part))
            for unit,part in zip(out['units'],[a,b]):
                unit['own_spans']=[span(part)];unit['envelope_spans']=[span(text)]
                unit['scope'].update(subject_refs=[span(part)],predicate_refs=[span(part)])
            out['edges'][0]['cue_refs']=[span('because')]
            out['coverage'][0]['span']=span(text)
            self.proposals[sid]=out
            value=g.anchors.encode(g.envelope(source,snapshot_id='synthetic',snapshot_sha256=g.digest('synthetic')),out)
        elif system.startswith(g.OBSERVE):
            sid=data['ORIGINAL']['source_id'];value=observation_example({'output':self.proposals[sid]})
            if self.bad_graph:value['dependency_coverage']='unknown'
        elif system.startswith(reqs.SYSTEM):
            output=scoped_output if data.get('EVIDENCE_PROTOCOL')==reqs.SCOPED_BATCH else candidate_output
            value=output(data['CANDIDATES'])
            if self.drop_reason:value['candidates'][0]['reason_unit_ids']=[]
        else:return super().call(stage,request)
        self.calls.append((stage,request));return {'output':value,'raw':'synthetic fixture','errors':[]}


class SourceEvidencePipelineTests(TestCase):
    def setUp(self):self.h=fixture.MinimalPipelineTests();self.h.setUp()
    def process(self,runner):
        from commentscope.factory import jev_membership
        return self.h.process(runner,discovery_mode='shared',membership_mode='raw',verification_contract=verification.FULL_SCOPE,
            argument_audit_protocol=obs.SHARED_TYPED_CHAT,agent_source_policy='candidate_verified_subset',
            membership_judge_protocol=jev_membership.VERSION,source_evidence_protocol=g.VERSION)

    def test_new_graph_replaces_scalar_extraction_and_preserves_two_agents_with_own_reasons(self):
        runner=GraphRunner();result=self.process(runner)
        self.assertEqual(result['errors'],[])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']),2)
        self.assertEqual(len(result['arguments']),6)
        for profile in result['agent_inputs']['compiled']['profiles']:
            self.assertEqual(profile['model_core_support_count'],3)
            self.assertTrue(any('matters' in row['text'] for row in profile['prompt_entries']))
        stages=[s for s,_ in runner.calls]
        self.assertFalse(any(s.startswith(('argument-node-metadata','shared-owned-position','argument-owner','argument-dependency','argument-audit')) for s in stages))
        self.assertTrue(any(s.startswith('raw-own-evidence') for s in stages))
        self.assertEqual(sum(s.startswith('source-evidence-proposal') for s in stages),6)
        self.assertEqual(sum(s.startswith('source-evidence-observation') for s in stages),6)
        self.assertEqual(sum(s.startswith('source-evidence-candidates') for s in stages),6)
        inventories=[v for k,v in self.h.saved.items() if k.startswith('source-evidence-workloads/')]
        self.assertEqual(len(inventories),6)
        self.assertTrue(all(r['audit_verdicts']==25 for r in inventories))
        self.assertFalse(result['quality_gate_passed'])

    def test_registered_qualified_mining_reaches_compiled_source_reasons(self):
        from commentscope.agents import seed_policy
        from commentscope.factory import jev_membership, perspective_mining, shared_claims
        from tools.prepared_video_trial import SEARCH
        class QualifiedRunner(GraphRunner):
            def call(self,stage,request):
                if request['system'].startswith(shared_claims.SCOPED_SYSTEM):
                    grouped={}
                    for row in request['data']['ORIGINALS']:
                        text=row['ORIGINAL_SEGMENTS'][0]['text'].split(' because ')[0].rstrip('.')+'.'
                        grouped.setdefault(text,[]).append(row['author_id'])
                    self.calls.append((stage,request))
                    return {'output':{'candidates':[dict(text=text,nominees=authors,assertion_kind='value',qualifications=[])
                            for text,authors in grouped.items()]},'raw':'synthetic fixture','errors':[]}
                return super().call(stage,request)
        result=self.h.process(QualifiedRunner(),discovery_mode='shared',membership_mode='raw',verification_contract=verification.FULL_SCOPE,
            argument_audit_protocol=obs.SHARED_TYPED_CHAT,agent_source_policy='candidate_verified_subset',
            membership_judge_protocol=jev_membership.VERSION,source_evidence_protocol=g.VERSION,
            membership_evidence_protocol=verification.QUALIFIED_CONTEXT,
            membership_search_policy=SEARCH,admission_policy=seed_policy.POLICY)
        self.assertEqual(SEARCH['version'],perspective_mining.QUALIFIED)
        self.assertFalse(result['errors'])
        self.assertTrue(all('qualifications' in c for c in result['candidates']))
        profiles=result['agent_inputs']['compiled']['profiles']
        self.assertEqual(len(profiles),2)
        self.assertTrue(all(any('matters' in e['text'] for e in p['prompt_entries']) for p in profiles))

    def test_unresolved_source_or_omitted_reason_cannot_be_rescued_by_subset_policy(self):
        for runner in [GraphRunner(bad_graph=True),GraphRunner(drop_reason=True),GraphRunner(veto=True)]:
            self.h.saved={};result=self.process(runner)
            self.assertFalse(result['agent_inputs']['compiled']['profiles'])

    def test_unknown_protocol_rejected_before_callbacks(self):
        runner=GraphRunner()
        with self.assertRaises(ValueError):self.h.process(runner,source_evidence_protocol='unknown')
        self.assertEqual(runner.calls,[])

    def test_explicit_graph_cost_caps_and_registered_routes(self):
        self.assertEqual(remote_verification.role('source-evidence-proposal-'+'a'*20),'generation')
        self.assertEqual(remote_verification.role('source-evidence-observation-'+'a'*20),'verification')
        legacy=cost.CallLimits(dict.fromkeys(cost.STAGES,0))
        with self.assertRaises(cost.CostPlanError):legacy.admit('source-evidence-proposal',{})
        limits=cost.CallLimits(dict.fromkeys((*cost.STAGES,*cost.GRAPH_STAGES),1))
        limits.admit('source-evidence-proposal',{});limits.admit('source-evidence-proposal',{})
        with self.assertRaises(cost.CostPlanError):limits.admit('source-evidence-proposal',{'changed':True})

    def test_new_stages_cannot_borrow_old_profiles_or_hide_unknown_counts(self):
        import test_factory_cost_plan as cf
        h=cf.CostPlanningTests();h.setUp();h.plan['source_evidence_protocol']=g.VERSION
        counts={**h.work['counts'],**dict.fromkeys(cost.GRAPH_STAGES,6)}
        result=cost.estimate(h.plan,h.candidates,counts,[h.profile],available_usd='50',goal='development')
        self.assertTrue(set(cost.GRAPH_STAGES)<=set(result['unknown_stages']))
        self.assertFalse(result['estimated_feasible'])

    def test_all_new_requests_compile_through_real_strict_wire_schema_without_network(self):
        from commentscope.providers.openrouter import Client
        from commentscope.factory import shared_claims
        source,env,_,p,o=example();v=g.verify(p,g.bind_observation(p,{'output':o}))
        cs=mc.candidates(extraction([source],{'s':['Adopt P.']}))
        scoped_candidates=[{**c,'qualifications':[]} for c in cs]
        for request in [g.proposal_request(env),g.observation_request(p),reqs.candidate_request(v,cs),
                        reqs.candidate_request(v,scoped_candidates),
                        shared_claims.request([source],version=shared_claims.SCOPED_MINING)]:
            capacity=Client(remote_verification.SOL).measure(request)
            self.assertTrue(capacity['fits'])
            self.assertFalse(capacity['native_tokenization'])
