"""Conditional qualification does not assert necessity or satisfied facts."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_evidence_graph as g,source_evidence_requests as reqs,source_evidence_adapter as adapter,minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from test_source_evidence_graph import example,observation_example
from test_source_evidence_pipeline import candidate_output
from test_contextual_qualifications import fixture,nomination


class SourceConditionQualificationTests(TestCase):
    def conditional(self,relation='condition_for',cue='If funded'):
        source={'id':'s','text':cue+', adopt P because fairness matters.','parent':None}
        _,_,out,_,_=example()
        def ref(part):
            i=source['text'].index(part);return dict(source_id='s',start=i,end=i+len(part))
        for u,part in zip(out['units'],['adopt P','fairness matters']):
            u['own_spans']=[ref(part)];u['envelope_spans']=[ref(source['text'])]
            u['scope'].update(subject_refs=[ref(part)],predicate_refs=[ref(part)])
        out['edges'][0]['cue_refs']=[ref('because')]
        u=deepcopy(out['units'][1]);u.update(local_id='U3',kind='fact',world='hypothetical',assertion_mode='conditional_antecedent',own_spans=[ref(cue)],envelope_spans=[ref(source['text'])])
        u['scope'].update(subject_refs=[ref(cue)],predicate_refs=[ref(cue)])
        out['units'].append(u);out['edges'].append(dict(local_id='E2',from_unit='U3',to_unit='U1',relation=relation,cue_refs=[],interpretation='resolved'))
        out['coverage'][0].update(span=ref(source['text']),unit_ids=['U1','U2','U3'])
        env=g.envelope(source,snapshot_id='synthetic',snapshot_sha256=digest('synthetic'),language='en')
        p=g.bind_annotation(env,{'output':out});v=g.verify(p,g.bind_observation(p,{'output':observation_example(p)}))
        f=fixture(source['text']);cs=[f[1]];members=[nomination(f)]
        response=candidate_output(cs);response['candidates'][0].update(essential_condition_unit_ids=['U3'],dependency_edge_ids=['E2'])
        return source,env,out,v,cs,members,response

    def test_neutral_condition_reaches_scope_without_necessary_upgrade_or_asserted_fact(self):
        _,_,_,v,cs,members,response=self.conditional()
        b=reqs.bind_candidates(v,cs,members,{'output':response});record=adapter.lower([b])
        self.assertEqual(record['status'],'complete')
        self.assertEqual(b['certificates'][0]['output']['dependency_edges'][0]['relation'],'condition_for')
        self.assertEqual(record['units'][0]['scope']['conditions'],'If funded')
        self.assertEqual(record['units'][2]['runtime_exposure'],'scope_annotation_only')
        self.assertEqual(record['units'][2]['kind'],'uncertain')
        self.assertEqual(g.closure(v['proposal']['output']['edges'],['U1']),{'U3'})

    def test_explicit_necessary_condition_stays_distinct(self):
        _,_,_,v,cs,members,response=self.conditional('necessary_condition_for','Only if funded')
        b=reqs.bind_candidates(v,cs,members,{'output':response})
        self.assertEqual(adapter.lower([b])['status'],'complete')
        self.assertEqual(b['certificates'][0]['output']['dependency_edges'][0]['relation'],'necessary_condition_for')

    def test_omitted_neutral_condition_or_edge_still_holds_whole_source(self):
        _,_,_,v,cs,members,response=self.conditional()
        for field in ('essential_condition_unit_ids','dependency_edge_ids'):
            bad=deepcopy(response);bad['candidates'][0][field]=[]
            self.assertEqual(adapter.lower([reqs.bind_candidates(v,cs,members,{'output':bad})])['status'],'unresolved')

    def test_unbound_antecedent_and_nested_mixed_qualifications_are_not_flattened(self):
        _,env,out,_,_,_,_=self.conditional();out['edges'].pop()
        p=g.bind_annotation(env,{'output':out});v=g.verify(p,g.bind_observation(p,{'output':observation_example(p)}))
        self.assertIn('unbound_conditional_antecedent',v['issues'])
        # Both conditional relations participate in cycle/closure checks.
        edges=[dict(local_id='E1',from_unit='U1',to_unit='U2',relation='condition_for',cue_refs=[],interpretation='resolved'),dict(local_id='E2',from_unit='U2',to_unit='U1',relation='necessary_condition_for',cue_refs=[],interpretation='resolved')]
        with self.assertRaises(ValueError):g.closure(edges,['U1'])

    def test_prior_protocol_cannot_be_relabelled_as_current_receipt(self):
        _,_,_,v,_,_,_=self.conditional()
        for version in ('source-evidence-graph-20261112-v3','source-evidence-graph-20261112-v4'):
            old=deepcopy(v['proposal']);old['artifact_kind']=version+'/proposal'
            with self.assertRaises(ValueError):g.observation_request(old)
