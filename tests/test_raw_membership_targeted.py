"""Opt-in eligibility boundaries; authored outputs are not semantic evidence."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import raw_membership as raw, raw_membership_verification as v
from commentscope.factory import substantive_contribution as sc, substantive_target as st
from commentscope.factory import contextual_engine as ce, minimal_pipeline
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate, decision


class TargetedMembershipTests(TestCase):
    def setUp(self):
        self.source = {'id': 'a', 'text': 'Garden access should be free.', 'parent': None}
        self.target = candidate(self.source, self.source['text'])
        self.content = {'output': {'assertion_kind': 'public_issue_claim',
                                   'reference_target': 'named_or_context_resolved'}}
        self.target_result = {'output': {'target_address': 'SELF', 'target_content': 'public_issue_claim',
                                        'target_closed': 'yes'}}
        self.evidence = {'output': {'reference_basis': 'self_contained', 'target_alignment': 'aligned',
                                   'source_basis': 'own_assertion', 'verdict': 'fully_stated'}}

    def route(self):
        return v.bind_route(self.target, self.content, self.source, version=v.TARGETED,
                            target_check=st.bind(self.target, self.source, self.target_result))

    def proof(self, source=None, evidence=None):
        proposal = raw.bind(source or self.source, self.target, {'output': decision()})
        check = v.bind_evidence(proposal, evidence or self.evidence, v.TARGETED)
        return v.assessment(proposal, self.route(), check, version=v.TARGETED)

    def test_requests_preserve_original_v2_target_v1_and_aligned_v6_evidence(self):
        self.assertEqual(v.route_request(self.target, self.source, version=v.TARGETED),
                         sc.request(self.target, self.source, sc.CONTENT))
        proposal = raw.bind(self.source, self.target, {'output': decision()})
        self.assertEqual(v.evidence_request(proposal, v.TARGETED), v.evidence_request(proposal, v.ALIGNED))
        self.assertTrue(v.validate(self.proof())['passed'])
        for mode in ('free', 'contextual'):
            with self.assertRaises(ValueError):
                minimal_pipeline.process(None, None, None, None, None, model=None,
                    discovery_mode=mode, membership_mode='scoped', verification_contract=v.TARGETED)

    def test_missing_or_failed_target_cannot_retain_positive_proposal(self):
        proposal = raw.bind(self.source, self.target, {'output': decision()})
        route = v.bind_route(self.target, self.content, self.source, version=v.TARGETED)
        self.assertFalse(v.assessment(proposal, route, version=v.TARGETED)['passed'])
        self.target_result['output']['target_closed'] = 'no'
        self.assertFalse(v.validate(self.proof())['passed'])
        self.target_result['output']['target_closed'] = 'yes'
        self.evidence['output']['source_basis'] = 'parent_only'
        self.assertFalse(v.validate(self.proof())['passed'])

    def test_foreign_target_proof_tampering_and_v6_v7_mixing_are_rejected(self):
        route = self.route(); proposal = raw.bind(self.source, self.target, {'output': decision()})
        changed = deepcopy(route); changed['target_check']['selected_target']['span']['text'] = 'Fabricated'
        with self.assertRaises(ValueError): v.assessment(proposal, changed, version=v.TARGETED)
        other = {**self.source, 'id': 'other'}; other_candidate = candidate(other, other['text'])
        foreign = st.bind(other_candidate, other, self.target_result)
        with self.assertRaises(ValueError):
            v.bind_route(self.target, self.content, self.source, version=v.TARGETED, target_check=foreign)
        old_route = v.bind_route(self.target, {'output': {'focus_token': 'T1', 'focus_domain': 'substantive_issue',
            'role': 'subject_position', 'interpretation': 'clear'}}, self.source, version=v.ALIGNED)
        old_evidence = v.bind_evidence(proposal, self.evidence, v.ALIGNED)
        new_evidence = v.bind_evidence(proposal, self.evidence, v.TARGETED)
        for routing, evidence, version in ((old_route, new_evidence, v.TARGETED),
                (route, old_evidence, v.TARGETED), (route, new_evidence, v.ALIGNED)):
            with self.assertRaises(ValueError): v.assessment(proposal, routing, evidence, version=version)

    def test_parent_address_never_closes_another_sources_omitted_target(self):
        self.source = {'id': 'a', 'text': 'Sounds reasonable.',
                       'parent': {'id': 'p', 'text': 'Garden access should be free.'}}
        self.target = candidate(self.source, self.source['text'])
        self.target_result['output']['target_address'] = 'PARENT'
        self.assertTrue(v.validate(self.proof())['passed'])
        other = {'id': 'b', 'text': 'Sounds reasonable.',
                 'parent': {'id': 'q', 'text': 'Garden access should be expensive.'}}
        proof = v.validate(self.proof(other))
        self.assertFalse(proof['passed'])
        self.assertIn('cross_source_selected_target_requires_unavailable_origin_context', proof['guards'])
        data = v.evidence_request(proof['raw'], v.TARGETED)['data']
        self.assertEqual(data['PARENT_REFERENCE_ONLY'], other['parent'])
        self.assertNotIn(self.source['parent']['text'], str(data))

    def test_engine_caches_target_check_and_stops_on_excluded_contribution(self):
        owner = self
        class Runner:
            def __init__(self, exclude=False): self.calls = []; self.exclude = exclude
            def call(self, stage, request):
                self.calls.append(stage)
                if stage.startswith('raw-candidate-route'):
                    value = deepcopy(owner.content)
                    if self.exclude: value['output']['assertion_kind'] = 'media_activity_or_identity_only'
                elif stage.startswith('raw-candidate-target'): value = owner.target_result
                elif stage.startswith('raw-own-evidence'): value = owner.evidence
                else: value = {'output': decision()}
                return {**value, 'raw': 'authored contract fixture', 'errors': []}
        other = {**self.source, 'id': 'b'}
        for exclude in (False, True):
            runner = Runner(exclude)
            engine = ce.Engine([self.source, other], runner,
                lambda r: {'fits': True, 'request_sha256': digest(r)}, raw_membership=True,
                verification_contract=v.TARGETED)
            for source in (self.source, other):
                result = engine.support(source['id'], self.target)
                self.assertEqual(result['accepted'], not exclude)
                self.assertIsNotNone(result['batch'])
            self.assertFalse(engine.errors)
            self.assertEqual(sum(s.startswith('raw-candidate-route') for s in runner.calls), 1)
            self.assertEqual(sum(s.startswith('raw-candidate-target') for s in runner.calls), 0 if exclude else 1)
            # Identical full evidence requests reuse one response, while each
            # assessment binds its own source/proposal separately.
            self.assertEqual(sum(s.startswith('raw-own-evidence') for s in runner.calls), 0 if exclude else 1)
            if not exclude:
                self.assertEqual(len({p['evidence_check']['raw_sha256'] for p in engine._raw_comparisons.values()}), 2)
