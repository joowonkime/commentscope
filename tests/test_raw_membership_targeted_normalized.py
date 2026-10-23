"""Original offsets survive existing whitespace/NFC candidate normalization."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import minimal_claims as mc, substantive_target as st
from commentscope.factory import raw_membership_verification as v, contextual_engine as ce
from commentscope.factory.automatic_contract import digest
from test_contextual_propositions import selected, original
from test_raw_membership import candidate, decision


class NormalizedTargetTests(TestCase):
    result = {'output': {'target_address': 'SELF', 'target_content': 'public_issue_claim', 'target_closed': 'yes'}}
    content = {'output': {'assertion_kind': 'public_issue_claim', 'reference_target': 'named_or_context_resolved'}}

    def test_original_unicode_and_spacing_are_not_rewritten(self):
        source = original('Cafe\u0301  access should be free.')
        target = mc.candidates([selected(source)])[0]
        self.assertNotEqual(source['text'], target['text'])
        with self.assertRaises(ValueError): st.request(target, source)
        req = st.request(target, source, st.NORMALIZED)
        span = req['data']['TARGET_ADDRESSES'][0]['span']
        self.assertEqual(span, {'start': 0, 'end': len(source['text']), 'text': source['text']})
        self.assertEqual(req['data']['CANDIDATE']['text'], mc.normalize(source['text']))
        record = st.bind(target, source, self.result, st.NORMALIZED)
        self.assertEqual(st.validate(record), record)
        changed = deepcopy(record); changed['selected_target']['span']['text'] = target['text']
        with self.assertRaises(ValueError): st.validate(changed)
        changed = deepcopy(target); changed['text'] = 'Cafe access should be expensive.'
        with self.assertRaises(ValueError): st.request(changed, source, st.NORMALIZED)

    def test_unchanged_literal_requests_replay_but_target_versions_cannot_mix(self):
        source = original('Garden access should be free.'); target = candidate(source, source['text'])
        self.assertEqual(st.request(target, source), st.request(target, source, st.NORMALIZED))
        old = st.bind(target, source, self.result); new = st.bind(target, source, self.result, st.NORMALIZED)
        for version, proof in ((v.TARGETED, new), (v.TARGETED_NORMALIZED, old)):
            with self.assertRaises(ValueError):
                v.bind_route(target, self.content, source, version=version, target_check=proof)
        self.assertTrue(v.bind_route(target, self.content, source, version=v.TARGETED_NORMALIZED, target_check=new)['passed'])

    def test_engine_accepts_normalized_binding_and_keeps_existing_timestamp_hold(self):
        owner = self
        class Runner:
            def call(self, stage, request):
                if stage.startswith('raw-candidate-route'): value = owner.content
                elif stage.startswith('raw-candidate-target'): value = owner.result
                elif stage.startswith('raw-own-evidence'):
                    value = {'output': {'reference_basis': 'self_contained', 'target_alignment': 'aligned',
                                        'source_basis': 'own_assertion', 'verdict': 'fully_stated'}}
                else: value = {'output': decision()}
                return {**value, 'raw': 'authored contract fixture', 'errors': []}
        for text, expected in (('Garden access  should be free.', True), ('6:40  The current system is bad', False)):
            source = original(text); target = mc.candidates([selected(source)])[0]
            engine = ce.Engine([source], Runner(), lambda r: {'fits': True, 'request_sha256': digest(r)},
                               raw_membership=True, verification_contract=v.TARGETED_NORMALIZED)
            proof = v.validate(engine.raw_assessment(source['id'], target))
            self.assertEqual(proof['passed'], expected); self.assertFalse(engine.errors)
            if not expected: self.assertIn('timestamp_citation_without_local_own_stance', proof['route']['guards'])
