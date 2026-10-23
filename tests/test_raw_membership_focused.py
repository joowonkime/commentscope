"""Contract tests only; semantic success requires fresh local inference review."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import raw_membership as raw, raw_membership_verification as v
from test_raw_membership import candidate, decision


class FocusedMembershipTests(TestCase):
    def setUp(self):
        self.source = {'id': 'a', 'text': 'Housing support should be expanded.', 'parent': None}
        self.target = candidate(self.source, self.source['text'])
        self.raw = raw.bind(self.source, self.target, {'output': decision()})

    def route(self, **changes):
        output = {'focus_token': 'T1', 'focus_domain': 'substantive_issue', 'role': 'subject_position',
                  'interpretation': 'clear', **changes}
        return v.bind_route(self.target, {'output': output}, self.source, version=v.FOCUSED)

    def evidence(self, **changes):
        output = {'speech_use': 'literal_assertion', 'reference_basis': 'self_contained',
                  'target_alignment': 'aligned',
                  'source_basis': 'own_assertion', 'verdict': 'fully_stated', **changes}
        return v.bind_evidence(self.raw, {'output': output}, v.FOCUSED)

    def result(self, route=None, evidence=None):
        return v.assessment(self.raw, route or self.route(), evidence or self.evidence(), version=v.FOCUSED)

    def test_raw_copy_approval_cannot_override_metadata_speech_or_reference_holds(self):
        self.assertTrue(v.validate(self.result())['passed'])
        for change in ({'focus_domain': 'publication_or_creator'}, {'focus_domain': 'social_or_promotion'},
                       {'focus_domain': 'unclear'}, {'focus_token': 'unresolved'}, {'interpretation': 'uncertain'}):
            with self.subTest(change=change):
                result = self.result(route=self.route(**change))
                self.assertFalse(result['passed']); self.assertEqual(result['relation'], 'uncertain')
        for change in ({'speech_use': 'report_or_echo'}, {'speech_use': 'unclear'},
                       {'reference_basis': 'missing_or_ambiguous'},
                       {'target_alignment': 'different_target'}, {'target_alignment': 'unresolved'}):
            with self.subTest(change=change):
                result = self.result(evidence=self.evidence(**change))
                self.assertFalse(result['passed']); self.assertEqual(result['relation'], 'uncertain')

    def test_exact_origin_and_focus_address_are_required(self):
        with self.assertRaises(ValueError): v.route_request(self.target, version=v.FOCUSED)
        with self.assertRaises(ValueError): self.route(focus_token='T999')
        wrong = deepcopy(self.source); wrong['text'] = 'Different claim.'
        with self.assertRaises(ValueError): v.route_request(self.target, wrong, version=v.FOCUSED)
        changed = self.result(); changed['route']['output']['focus_domain'] = 'publication_or_creator'
        with self.assertRaises(ValueError): v.validate(changed)

    def test_new_checks_cannot_be_satisfied_by_legacy_checks(self):
        legacy_route = v.bind_route(self.target, {'output': {'role': 'subject_position'}})
        legacy_evidence = v.bind_evidence(self.raw, {'output': {'source_basis': 'own_assertion', 'verdict': 'fully_stated'}}, v.CLAUSE_SCOPE)
        self.assertTrue(v.validate(v.assessment(self.raw, legacy_route, legacy_evidence, version=v.CLAUSE_SCOPE))['passed'])
        with self.assertRaises(ValueError): self.result(route=legacy_route)
        with self.assertRaises(ValueError): self.result(evidence=legacy_evidence)
        for route, evidence in ((None, None), (self.route(), None), (None, self.evidence())):
            self.assertFalse(v.assessment(self.raw, route, evidence, version=v.FOCUSED)['passed'])

    def test_context_can_resolve_references_without_becoming_own_evidence(self):
        self.source['parent'] = {'id': 'p', 'text': 'The housing payment is 800 dollars.'}
        self.source['text'] = 'My rent is more than that.'
        self.target = candidate(self.source, self.source['text'])
        self.raw = raw.bind(self.source, self.target, {'output': decision()})
        self.assertTrue(self.result(evidence=self.evidence(reference_basis='supplied_context'))['passed'])
        data = v.evidence_request(self.raw, v.FOCUSED)['data']
        self.assertEqual(data['PARENT_REFERENCE_ONLY'], self.source['parent'])
        self.assertEqual(data['OWN_EVIDENCE'], self.raw['evidence'])
        self.assertNotIn('relation', data); self.assertNotIn('output', data)
        self.assertFalse(self.result(evidence=self.evidence(source_basis='parent_only'))['passed'])

    def test_clause_modal_guard_survives_new_semantic_fields(self):
        for text, expected in [('Housing support may improve lives.', False),
                               ('I support mandatory housing support even though it may be expensive.', True)]:
            self.source['text'] = text
            self.target = candidate(self.source, 'Housing support should be mandatory.')
            self.raw = raw.bind(self.source, self.target, {'output': decision()})
            with self.subTest(text=text): self.assertEqual(self.result()['passed'], expected)

    def test_engine_dispatches_both_focused_contracts_and_keeps_rejected_evidence(self):
        from commentscope.factory.contextual_engine import Engine
        from commentscope.factory.automatic_contract import digest
        class Runner:
            def __init__(self): self.calls = []
            def call(inner, stage, request):
                inner.calls.append(request)
                if 'relation' in request['schema']['properties']: value = decision()
                elif 'focus_token' in request['schema']['properties']:
                    value = {'focus_token': 'T1', 'focus_domain': 'substantive_issue', 'role': 'subject_position', 'interpretation': 'clear'}
                else:
                    value = {'speech_use': 'unclear', 'reference_basis': 'self_contained',
                             'target_alignment': 'aligned',
                             'source_basis': 'own_assertion', 'verdict': 'fully_stated'}
                return {'output': value, 'raw': 'authored contract fixture', 'errors': []}
        runner = Runner(); saved = {}
        engine = Engine([self.source], runner, lambda r: {'fits': True, 'request_sha256': digest(r)},
                        lambda name, value: saved.update({name: value}),
                        raw_membership=True, verification_contract=v.FOCUSED)
        proof = engine.raw_assessment(self.source['id'], self.target)
        self.assertFalse(proof['passed']); self.assertEqual(proof['relation'], 'uncertain')
        self.assertEqual(proof['route']['artifact_kind'], v.FOCUSED+'-route')
        self.assertEqual(proof['evidence_check']['artifact_kind'], v.FOCUSED+'-evidence')
        self.assertEqual(len(runner.calls), 3)
        self.assertTrue(any(name.startswith('raw-comparisons/') for name in saved))
        self.assertEqual(engine.raw_assessment(self.source['id'], self.target), proof)
        self.assertEqual(len(runner.calls), 3)

    def test_independent_evidence_never_receives_candidate_origin_assertions(self):
        from test_contextual_engine import ContextualEngineTests
        engine, scopes = ContextualEngineTests().representative_fixture()
        target = next(c for c in engine.candidates if scopes[c['id']]['ready'])
        source = {'id': 'independent-author', 'text': 'Garden access should be free.', 'parent': None}
        record = raw.bind(source, target, {'output': decision()})
        req = v.evidence_request(record, v.FOCUSED, candidate_scope=scopes[target['id']])
        self.assertEqual(req['data']['CANDIDATE'], {'text': target['text'], 'world': 'actual'})
        self.assertNotIn('BOUND_MEANING', str(req['data']))
        self.assertNotIn('candidate_scope', req['data'])
        self.assertNotIn('ORIGIN_CONTEXT_ONLY', req['data'])
        changed = deepcopy(scopes[target['id']]); changed['text'] = 'A different claim.'
        with self.assertRaises(ValueError): v.evidence_request(record, v.FOCUSED, candidate_scope=changed)

    def test_unclosed_cross_source_target_cannot_be_reinterpreted_as_own_referent(self):
        from test_contextual_engine import ContextualEngineTests
        engine, scopes = ContextualEngineTests().representative_fixture()
        target = next(c for c in engine.candidates if not scopes[c['id']]['ready'])
        source = {'id': 'different-parent', 'text': 'It should be free.',
                  'parent': {'id': 'library-parent', 'text': 'Library access should be free.'}}
        record = raw.bind(source, target, {'output': decision()})
        value = self.evidence(reference_basis='supplied_context')['output']
        proof = v.bind_evidence(record, {'output': value}, v.FOCUSED, candidate_scope=scopes[target['id']])
        self.assertFalse(proof['passed'])
        self.assertIn('cross_source_candidate_requires_unavailable_origin_context', proof['guards'])
        own = target['meaning_context']['source']
        own_record = raw.bind(own, target, {'output': decision()})
        own_proof = v.bind_evidence(own_record, {'output': value}, v.FOCUSED, candidate_scope=scopes[target['id']])
        self.assertTrue(own_proof['passed'])
        self.assertEqual(v.evidence_request(own_record, v.FOCUSED, candidate_scope=scopes[target['id']])['data']['PARENT_REFERENCE_ONLY'], own['parent'])
