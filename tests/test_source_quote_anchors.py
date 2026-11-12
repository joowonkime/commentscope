"""Exact quote addressing and closed proposal typing without model calls."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_quote_anchors as a,source_evidence_graph as g
from commentscope.factory.automatic_contract import digest


class ExactQuoteTests(TestCase):
    def env(self,text,parent=None):
        return g.envelope(dict(id='own',text=text,parent=parent),snapshot_id='synthetic',snapshot_sha256=digest('synthetic'))

    def test_unicode_occurrences_and_overlapping_matches_are_exact(self):
        env=self.env('🙂가나다 가나 e\u0301 aaa')
        self.assertEqual(a.resolve(env,dict(quote='가나',occurrence=1)),dict(source_id='own',start=5,end=7))
        self.assertEqual(a.resolve(env,dict(quote='aa',occurrence=1)),dict(source_id='own',start=12,end=14))
        with self.assertRaises(ValueError):a.resolve(env,dict(quote='é',occurrence=0))

    def test_unit_scope_occurrences_are_local_and_parent_is_reference_only(self):
        env=self.env('P likes P. P rejects P.',dict(id='parent',text='UBI reduces poverty.'))
        own=[dict(source_id='own',start=11,end=23)]
        self.assertEqual(a.resolve(env,dict(quote='P',occurrence=0,origin='unit'),own=own)['start'],11)
        self.assertEqual(a.resolve(env,dict(quote='UBI',occurrence=0,origin='parent'),own=own,reference=True)['source_id'],'parent')
        with self.assertRaises(ValueError):a.resolve(env,dict(quote='UBI',occurrence=0,origin='parent'),own=own)
        with self.assertRaises(ValueError):a.resolve(env,dict(quote='UBI',occurrence=0))

    def test_missing_quote_bad_occurrence_and_undeclared_fields_are_rejected(self):
        env=self.env('Do not adopt P.')
        for anchor in (dict(quote='adopt Q',occurrence=0),dict(quote='adopt P',occurrence=2),dict(quote='adopt P',occurrence=-1),dict(quote='adopt P',occurrence=True),dict(quote='',occurrence=0),dict(quote='adopt P',occurrence=0,start=7)):
            with self.subTest(anchor=anchor),self.assertRaises(ValueError):a.resolve(env,anchor)

    def test_roundtrip_retains_wire_provenance_and_host_addresses(self):
        from test_source_evidence_graph import example
        _,env,out,proposal,_=example()
        self.assertIn('wire_output',proposal)
        self.assertEqual(a.encode(env,proposal['output']),proposal['wire_output'])
        self.assertEqual(g.bind_proposal(env,{'output':proposal['wire_output']}),proposal)
        changed=deepcopy(proposal);changed['output']['units'][0]['own_spans'][0]['start']+=1
        with self.assertRaises(ValueError):g.validate_proposal(changed)

    def test_schema_does_not_allow_host_rejected_typing_combinations(self):
        from test_source_evidence_graph import example
        _,env,_,proposal,_=example();request=g.proposal_request(env)
        for field,value in (('epistemic','not_applicable'),('assertion_mode','non_assertive')):
            invalid=deepcopy(proposal['wire_output']);invalid['units'][0]['typing'][field]=value
            with self.assertRaises(ValueError):g.check(request['schema'],invalid)

    def test_full_coverage_uses_host_selector_and_cannot_borrow_parent(self):
        from test_source_evidence_graph import example
        _,env,_,proposal,_=example();wire=deepcopy(proposal['wire_output'])
        self.assertEqual(wire['coverage'][0]['span'],{'whole_source':'own'})
        wire['coverage'][0]['span']={'whole_source':'parent'}
        with self.assertRaises(ValueError):g.bind_proposal(env,{'output':wire})

    def test_dependency_choices_exclude_reason_and_example_edges(self):
        from test_source_evidence_pipeline import CandidateEvidenceTests
        from commentscope.factory import source_evidence_requests as reqs
        h=CandidateEvidenceTests();h.setUp();request=reqs.candidate_request(h.verified,h.cs)
        self.assertEqual(request['schema']['properties']['candidates']['items']['properties']['dependency_edge_ids']['maxItems'],0)

    def test_wire_uses_quotes_and_rejects_generated_numeric_addresses(self):
        from test_source_evidence_graph import example
        _,env,_,proposal,_=example();wire=deepcopy(proposal['wire_output']);unit=wire['units'][0]
        self.assertEqual(unit['own_spans'][0],dict(q='Adopt P',n=0))
        unit['own_spans']=[dict(source_id='s',start=0,end=7)]
        with self.assertRaises(ValueError):g.bind_proposal(env,{'output':wire})

    def test_wire_parent_reference_roundtrip_cannot_become_an_own_assertion(self):
        from test_source_evidence_graph import example
        _,_,out,proposal,_=example();wire=deepcopy(proposal['wire_output'])
        env=self.env('Adopt P because fairness matters.',dict(id='p',text='Adopt Q.'))
        wire['units'][0]['own_spans'][0]['q']='Adopt Q.'
        with self.assertRaises(ValueError):g.bind_proposal(env,{'output':wire})
        wire=deepcopy(proposal['wire_output']);wire['units'][0]['scope']['referent_refs']=[dict(q='Adopt Q.',n=0,o='parent')]
        bound=g.bind_proposal(env,{'output':wire})
        self.assertEqual(bound['output']['units'][0]['scope']['referent_refs'],[dict(source_id='p',start=0,end=8)])
        wire['units'][0]['scope']['predicate_refs']=[dict(q='Adopt Q.',n=0,o='parent')]
        with self.assertRaises(ValueError):g.bind_proposal(env,{'output':wire})
