"""v6 evidence boundary and strict prior-contract separation."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import raw_membership as raw, raw_membership_verification as v
from test_raw_membership import candidate, decision


class AlignedMembershipTests(TestCase):
    def setUp(self):
        self.source = {'id': 'a', 'text': 'They pay tenants more than that.', 'parent': None,
            'video_context': {'artifact_kind': 'snapshot-video-context-20261017-v1',
                             'video_id': 'example', 'title': 'Housing payments', 'primary_language': 'en'}}
        self.target = candidate(self.source, self.source['text'])
        self.raw = raw.bind(self.source, self.target, {'output': decision()})
        self.route_output = {'focus_token': 'T3', 'focus_domain': 'substantive_issue',
                             'role': 'subject_position', 'interpretation': 'clear'}
        self.evidence_output = {'reference_basis': 'self_contained', 'target_alignment': 'aligned',
                                'source_basis': 'own_assertion', 'verdict': 'fully_stated'}

    def test_independent_metadata_omission_preserves_raw_origin_parent_and_own_text(self):
        parent = {'id': 'p', 'text': 'The payment is eight hundred dollars.'}
        self.source['parent'] = parent; target = candidate(self.source, self.source['text'])
        proposal = raw.bind(self.source, target, {'output': decision()})
        req = v.evidence_request(proposal, v.ALIGNED)
        self.assertEqual(req['data']['OWN_CONTEXT'], self.source['text'])
        self.assertEqual(req['data']['PARENT_REFERENCE_ONLY'], parent)
        self.assertNotIn('VIDEO_CONTEXT_ONLY', req['data'])
        self.assertIn('Housing payments', str(raw.request(self.source, target)['data']))
        self.assertIn('Housing payments', str(v.route_request(target, self.source, version=v.ALIGNED)['data']))
        self.assertEqual(v.route_request(target, self.source, version=v.ALIGNED),
                         v.route_request(target, self.source, version=v.GROUNDED))
        self.assertNotEqual(req, v.evidence_request(proposal, v.GROUNDED))

    def test_missing_quantity_veto_remains_despite_positive_new_model_fields(self):
        route = v.bind_route(self.target, {'output': self.route_output}, self.source, version=v.ALIGNED)
        evidence = v.bind_evidence(self.raw, {'output': self.evidence_output}, v.ALIGNED)
        proof = v.validate(v.assessment(self.raw, route, evidence, version=v.ALIGNED))
        self.assertFalse(proof['passed'])
        self.assertIn('payment_comparator_without_supplied_quantity', route['guards'])
        self.assertIn('payment_comparator_without_supplied_quantity', evidence['guards'])
        changed = deepcopy(proof); changed['evidence_check']['guards'] = []
        with self.assertRaises(ValueError): v.validate(changed)

    def test_v5_artifacts_cannot_substitute_for_v6_even_with_equal_outputs(self):
        old_route = v.bind_route(self.target, {'output': self.route_output}, self.source, version=v.GROUNDED)
        new_route = v.bind_route(self.target, {'output': self.route_output}, self.source, version=v.ALIGNED)
        old_evidence = v.bind_evidence(self.raw, {'output': self.evidence_output}, v.GROUNDED)
        new_evidence = v.bind_evidence(self.raw, {'output': self.evidence_output}, v.ALIGNED)
        for route, evidence in [(old_route, new_evidence), (new_route, old_evidence)]:
            with self.subTest(route=route['artifact_kind'], evidence=evidence['artifact_kind']):
                with self.assertRaises(ValueError): v.assessment(self.raw, route, evidence, version=v.ALIGNED)
