from copy import deepcopy
from unittest import TestCase

from commentscope.factory import raw_membership as raw, raw_membership_verification as v, minimal_membership as mm
from test_raw_membership import candidate, decision


class RawVerificationTests(TestCase):
    def setUp(self):
        self.source = {'id': 'a', 'text': 'The scheme would improve lives.', 'parent': None}
        self.target = candidate(self.source, 'The scheme would improve lives.')
        self.record = raw.bind(self.source, self.target, {'output': decision()})

    def route(self, role='subject_position'):
        return v.bind_route(self.target, {'output': {'role': role}})

    def evidence(self, verdict='fully_stated', basis='own_assertion'):
        return v.bind_evidence(self.record, {'output': {'verdict': verdict, 'source_basis': basis}})

    def test_missing_check_cannot_silently_retain_raw_approval(self):
        for route, evidence in [(None, None), (self.route(), None), (None, self.evidence())]:
            self.assertFalse(v.assessment(self.record, route, evidence)['passed'])

    def test_metadata_and_parent_only_assertion_are_separate_vetoes(self):
        self.assertFalse(v.assessment(self.record, self.route('publication_or_creator_metadata'), self.evidence())['passed'])
        self.assertFalse(v.assessment(self.record, self.route(), self.evidence(basis='parent_only'))['passed'])
        self.assertFalse(v.assessment(self.record, self.route(), self.evidence(basis='inferred_not_stated'))['passed'])

    def test_existing_modal_veto_applies_to_selected_own_evidence(self):
        self.target = candidate(self.source, 'The scheme must be introduced.')
        self.record = raw.bind(self.source, self.target, {'output': decision()})
        record = v.assessment(self.record, self.route(), self.evidence())
        self.assertFalse(record['passed'])
        self.assertIn('forecast_or_possibility_is_not_a_demand', record['evidence_check']['guards'])

    def test_both_checks_bind_exact_original_candidate_and_own_evidence(self):
        record = v.assessment(self.record, self.route(), self.evidence())
        self.assertTrue(record['passed'])
        batch = v.batch([self.source], [self.target], [record])
        self.assertEqual(mm.collect([self.source], [self.target], [batch])[0]['relation'], 'supported')
        changed = deepcopy(record); changed['raw']['source']['text'] = 'Different source.'
        with self.assertRaises(ValueError): v.validate(changed)
        changed = deepcopy(record); changed['route']['output']['role'] = 'social_only'
        with self.assertRaises(ValueError): v.validate(changed)

    def test_prior_decision_is_not_supplied_to_new_checks(self):
        self.assertEqual(set(v.route_request(self.target)['data']), {'CANDIDATE'})
        data = v.evidence_request(self.record)['data']
        self.assertNotIn('output', data); self.assertNotIn('relation', data)
        self.assertEqual(data['OWN_EVIDENCE'], self.record['evidence'])

    def test_uncertainty_and_missing_parent_still_withhold(self):
        for evidence in [self.evidence('unresolved'), self.evidence(basis='explicit_parent_endorsement')]:
            self.assertFalse(v.assessment(self.record, self.route(), evidence)['passed'])

    def test_parent_assertion_cannot_enter_own_evidence_check(self):
        self.source['parent'] = {'id': 'p', 'text': 'UNIQUE PARENT ASSERTION THAT MUST NOT BE EVIDENCE'}
        self.target = candidate(self.source, 'The scheme would improve lives.')
        self.record = raw.bind(self.source, self.target, {'output': decision()})
        data = v.evidence_request(self.record)['data']
        self.assertTrue(data['IS_REPLY'])
        self.assertNotIn('UNIQUE PARENT ASSERTION', str(data))
        self.assertFalse(v.assessment(self.record, self.route(), self.evidence(basis='explicit_parent_endorsement'))['passed'])

    def test_candidate_route_origin_is_exact_but_not_an_approval(self):
        route = v.bind_route(self.target, {'output': {'role': 'publication_or_creator_metadata'}}, self.source)
        self.assertEqual(route['origin'], self.source)
        self.assertFalse(route['passed'])
        wrong = deepcopy(self.source); wrong['text'] = 'Another origin.'
        with self.assertRaises(ValueError): v.route_request(self.target, wrong)

    def test_legacy_evidence_replays_but_cannot_approve_new_contract(self):
        evidence = v.bind_evidence(self.record, {'output': {'source_basis': 'own_assertion', 'verdict': 'fully_stated'}}, v.LEGACY)
        prior = v.assessment(self.record, self.route(), evidence, version=v.LEGACY)
        self.assertTrue(v.validate(prior)['passed'])
        with self.assertRaises(ValueError): v.assessment(self.record, self.route(), evidence)

    def test_assertion_veto_excludes_owned_concession_without_losing_true_forecast(self):
        for text, ids, expected in [
            ('I support mandatory safety reviews even though they may be expensive.', ['S000'], True),
            ('Safety reviews may improve lives.', ['S000'], False),
            ('Safety reviews should be mandatory. Reviews may improve lives.', ['S001'], False)]:
            source={'id':'a','text':text,'parent':None}
            target=candidate(source,'Safety reviews should be mandatory.')
            raw_record=raw.bind(source,target,{'output':decision(evidence_segment_ids=ids)})
            route=v.bind_route(target,{'output':{'role':'subject_position'}})
            value={'output':{'source_basis':'own_assertion','verdict':'fully_stated'}}
            evidence=v.bind_evidence(raw_record,value,v.CLAUSE_SCOPE)
            record=v.assessment(raw_record,route,evidence,version=v.CLAUSE_SCOPE)
            with self.subTest(text=text):
                self.assertEqual(v.validate(record)['passed'],expected)
                batch=v.batch([source],[target],[record],version=v.CLAUSE_SCOPE)
                self.assertEqual(mm.collect([source],[target],[batch])[0]['relation']=='supported',expected)
                legacy=v.bind_evidence(raw_record,value,v.LEGACY)
                self.assertFalse(v.assessment(raw_record,route,legacy,version=v.LEGACY)['passed'])
                with self.assertRaises(ValueError):v.assessment(raw_record,route,legacy,version=v.CLAUSE_SCOPE)
