"""Veto counterexamples and exact v5 contracts; not semantic model scores."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import raw_membership as raw, raw_membership_verification as v
from commentscope.factory import membership_reference_guards as guards
from test_raw_membership import candidate, decision


class GroundedMembershipTests(TestCase):
    def proof(self, text, target=None, parent=None, origin=None, video=None):
        source = {'id': 'supporter', 'text': text, 'parent': parent}
        if video is not None: source['video_context'] = video
        origin = origin or source
        target = candidate(origin, target or text)
        record = raw.bind(source, target, {'output': decision()})
        route_req = v.route_request(target, origin, version=v.GROUNDED)
        route = v.bind_route(target, {'output': {
            'focus_token': next(iter(route_req['data']['FOCUS_TOKENS'])),
            'focus_domain': 'substantive_issue', 'role': 'subject_position',
            'interpretation': 'clear'}}, origin, version=v.GROUNDED)
        evidence = v.bind_evidence(record, {'output': {
            'reference_basis': 'supplied_context', 'target_alignment': 'aligned',
            'source_basis': 'own_assertion', 'verdict': 'fully_stated'}}, v.GROUNDED)
        return v.validate(v.assessment(record, route, evidence, version=v.GROUNDED))

    def test_timestamp_holds_origin_and_independent_source_without_claiming_irony(self):
        cited = '2:15 The old fee system is bad. The proposed fee is better.'
        for target in ['The old fee system is bad.', 'The proposed fee is better.']:
            with self.subTest(target=target):
                result = self.proof(cited, target)
                self.assertFalse(result['passed'])
                self.assertIn('timestamp_citation_without_local_own_stance', result['route']['guards'])
        result = self.proof('I support reconsidering fees.', 'The proposed fee is better.',
                           origin={'id': 'origin', 'text': cited, 'parent': None})
        self.assertFalse(result['route']['passed'])
        result = self.proof(cited, 'The proposed fee is better.',
                           origin={'id': 'origin', 'text': 'The proposed fee is better.', 'parent': None})
        self.assertTrue(result['route']['passed']); self.assertFalse(result['evidence_check']['passed'])

    def test_timestamp_explicit_local_stance_survives_but_remote_or_quoted_stance_does_not(self):
        for text in ['01:25 I agree that fee rebates should remain voluntary.',
                     '1:02:35 I do not agree with mandatory fees.']:
            self.assertTrue(self.proof(text)['passed'])
        text = 'I agree with park funding.\n\n2:15 Mandatory fees are better.'
        self.assertFalse(self.proof(text, 'Mandatory fees are better.')['passed'])
        text = '2:15 "I believe fees are better."'
        self.assertFalse(self.proof(text)['passed'])
        text = '2:15 The speaker discusses taxes.\n\nI support voluntary park fees.'
        self.assertTrue(self.proof(text, 'I support voluntary park fees.')['route']['passed'])

    def test_unaligned_free_candidate_cannot_escape_citation_hold(self):
        self.assertIn('timestamp_origin_assertion_unaligned',
                      self.proof('2:15 Mandatory fees are better.', 'Fees are preferable.')['route']['guards'])

    def test_missing_payment_comparator_is_a_hold_even_with_topic_title(self):
        video = {'artifact_kind': 'snapshot-video-context-20261017-v1', 'video_id': 'example',
                 'title': 'Public housing payments explained', 'primary_language': 'en'}
        result = self.proof('They already pay tenants more than that.', video=video)
        self.assertFalse(result['passed'])
        self.assertIn('payment_comparator_without_supplied_quantity', result['route']['guards'])
        self.assertIn('payment_comparator_without_supplied_quantity', result['evidence_check']['guards'])

    def test_amount_context_is_not_blocked_by_absence_guard(self):
        parent = {'id': 'p', 'text': 'The housing payment is eight hundred dollars.'}
        self.assertTrue(self.proof('They pay tenants more than that.', parent=parent)['passed'])
        for text in ['The payment is 800 dollars. They pay tenants more than that.',
                     'The payment is eight hundred dollars. They pay tenants more than that.',
                     'My rent is expensive; I earn more than that.']:
            self.assertFalse(guards.quantity_guards({'id': 'a', 'text': text, 'parent': None},
                         [{'start': 0, 'end': len(text), 'text': text}]))
        video = {'artifact_kind': 'snapshot-video-context-20261017-v1', 'video_id': 'example',
                 'title': 'The 800 dollar payment explained', 'primary_language': 'en'}
        self.assertTrue(self.proof('They pay tenants more than that.', video=video)['passed'])

    def test_vocative_focus_does_not_remove_or_rewrite_original_text(self):
        for text, excluded in [('Alex, your analysis is incomplete.', ['Alex']),
                               ('Dr Smith, you ignored the costs.', ['Dr', 'Smith']),
                               ('Canada, Mexico and France differ.', []),
                               ('The analysis is incomplete.', [])]:
            source = {'id': 's', 'text': text, 'parent': None}; target = candidate(source, text)
            req = v.route_request(target, source, version=v.GROUNDED)
            self.assertEqual(req['data']['CANDIDATE']['text'], text)
            tokens = list(req['data']['FOCUS_TOKENS'].values())
            for token in excluded: self.assertNotIn(token, tokens)
            if not excluded: self.assertEqual(tokens, [t['text'] for t in v.focus_tokens(target)])

    def test_directive_does_not_supply_unstated_forecast_but_explicit_reason_can(self):
        result = self.proof('We need more buses now!', 'More buses would reduce congestion.')
        self.assertIn('demand_does_not_state_a_forecast', result['evidence_check']['guards'])
        result = self.proof('We need more buses because they would reduce congestion.',
                            'More buses would reduce congestion.')
        self.assertNotIn('demand_does_not_state_a_forecast', result['evidence_check']['guards'])

    def test_video_metadata_is_from_supporting_source_and_never_candidate_origin(self):
        source = {'id': 's', 'text': 'That is too expensive.', 'parent': None,
                  'video_context': {'artifact_kind': 'snapshot-video-context-20261017-v1',
                    'video_id': 'source-video', 'title': 'Subway costs', 'primary_language': 'en'}}
        origin = {'id': 'o', 'text': 'Library fees are excessive.', 'parent': None,
                  'video_context': {**source['video_context'], 'video_id': 'other-video', 'title': 'Library fees'}}
        record = raw.bind(source, candidate(origin, origin['text']), {'output': decision()})
        req = v.evidence_request(record, v.GROUNDED)
        self.assertEqual(req['data']['VIDEO_CONTEXT_ONLY'], source['video_context'])
        self.assertNotIn('other-video', str(req['data']))
        self.assertNotIn('speech_use', req['schema']['properties'])

    def test_v4_cannot_substitute_for_v5_and_guards_cannot_be_erased(self):
        result = self.proof('3:20 The proposal is better.')
        changed = deepcopy(result); changed['route']['guards'] = []
        with self.assertRaises(ValueError): v.validate(changed)
        v4_route = v.bind_route(result['raw']['candidate'], {'output': result['route']['output']},
                               result['route']['origin'], version=v.FOCUSED)
        with self.assertRaises(ValueError):
            v.assessment(result['raw'], v4_route, result['evidence_check'], version=v.GROUNDED)
