from copy import deepcopy
import unittest

from commentscope.factory import minimal_claims as mc, raw_membership as raw
from commentscope.factory import raw_membership_verification as v
from test_minimal_factory import extraction


class MembershipEvidenceBasisTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 's', 'text': 'I support longer library hours even though staffing may be expensive.', 'parent': None}
        self.target = mc.candidates(extraction([self.source], {'s': ['I support longer library hours']}))[0]
        self.proof = raw.bind(self.source, self.target, {'output': {
            'relation': 'supported', 'authorship': 'asserted_or_endorsed', 'candidate_interpretation': 'clear',
            'scope_preserved': 'yes', 'contribution': 'substantive', 'evidence_segment_ids': ['S000']}})
        self.value = {'reference_basis': 'self_contained', 'target_alignment': 'aligned',
                      'source_basis': 'own_assertion', 'verdict': 'fully_stated',
                      'basis': 'The author explicitly supports longer library hours despite a staffing-cost concession.'}

    def bind(self, value):
        return v.bind_evidence(self.proof, {'output': value}, v.FULL_SCOPE, protocol=v.EXPLAINED)

    def test_complete_evidence_and_concession_are_preserved_with_an_explained_verdict(self):
        request = v.evidence_request(self.proof, v.FULL_SCOPE, protocol=v.EXPLAINED)
        self.assertEqual(request['data']['OWN_CONTEXT'], self.source['text'])
        self.assertIn('even though staffing may be expensive.', str(request['data']['OWN_EVIDENCE']))
        self.assertIn('basis', request['schema']['required'])
        evidence = self.bind(self.value)
        self.assertTrue(evidence['passed'])
        self.assertEqual(evidence['output']['basis'], self.value['basis'])
        self.assertEqual(evidence['protocol'], v.EXPLAINED)

    def test_explanation_never_overrides_negative_or_missing_author_support(self):
        for change in ({'verdict': 'extra_assertion'}, {'verdict': 'unresolved'},
                       {'source_basis': 'parent_only'}, {'source_basis': 'explicit_parent_endorsement'},
                       {'target_alignment': 'different_target'}, {'reference_basis': 'missing_or_ambiguous'}):
            evidence = self.bind({**self.value, **change})
            self.assertFalse(evidence['passed'])

    def test_forecast_to_demand_guard_still_vetoes_a_positive_model_and_explanation(self):
        source = {'id': 'forecast', 'text': 'Library staffing may cost more.', 'parent': None}
        # The existing modal veto recognizes explicit should/ought demands;
        # it is deliberately not a universal imperative classifier.
        target = mc.candidates(extraction([source], {'forecast': ['Library hours should be extended.']}))[0]
        proof = raw.bind(source, target, {'output': self.proof['output']})
        evidence = v.bind_evidence(proof, {'output': self.value}, v.FULL_SCOPE, protocol=v.EXPLAINED)
        self.assertFalse(evidence['passed'])
        self.assertIn('forecast_or_possibility_is_not_a_demand', evidence['guards'])

    def test_exact_assessment_binding_rejects_changed_explanation_or_protocol(self):
        route = v.bind_route(self.target, {'output': {'focus_token': 'T4', 'focus_domain': 'substantive_issue',
            'role': 'subject_position', 'interpretation': 'clear'}}, self.source, version=v.FULL_SCOPE)
        evidence = self.bind(self.value)
        record = v.assessment(self.proof, route, evidence, version=v.FULL_SCOPE)
        v.validate(record)
        for change in (lambda e: e['output'].update(basis='Changed after binding.'),
                       lambda e: e.update(protocol='unknown')):
            changed = deepcopy(record); change(changed['evidence_check'])
            with self.assertRaises(ValueError):
                v.validate(changed)

    def test_missing_unknown_or_unbounded_basis_and_wrong_contract_are_rejected(self):
        for change in (lambda r: r.pop('basis'), lambda r: r.update(basis=None),
                       lambda r: r.update(basis=' '), lambda r: r.update(basis=' '*240+'x')):
            value = deepcopy(self.value); change(value)
            with self.assertRaises(ValueError):
                self.bind(value)
        for version, protocol in ((v.FULL_SCOPE, 'unknown'), (v.VERSION, v.EXPLAINED)):
            with self.assertRaises(ValueError):
                v.evidence_request(self.proof, version, protocol=protocol)

    def test_legacy_evidence_format_is_unchanged_and_keeps_its_guards(self):
        value = {k: val for k, val in self.value.items() if k != 'basis'}
        request = v.evidence_request(self.proof, v.FULL_SCOPE)
        self.assertNotIn('basis', request['schema']['properties'])
        evidence = v.bind_evidence(self.proof, {'output': value}, v.FULL_SCOPE)
        self.assertNotIn('protocol', evidence)
        self.assertTrue(evidence['passed'])
