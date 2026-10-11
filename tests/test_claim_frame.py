from copy import deepcopy
import json
import unittest

from commentscope.factory import claim_frame as f
from commentscope.factory.automatic import checked_call


def unit(uid, text):
    return {'claim_id': uid, 'statement': text, 'spans': [{'text': text}]}


def frame(**changes):
    return {'status': 'atomic', 'scope': 'population', 'time': 'timeless', 'commitment': 'normative',
            'condition': 'none', 'condition_quotes': [], **changes}


def result(value):
    return {'output': value, 'errors': []}


class FrameTests(unittest.TestCase):
    def test_shape_and_exact_condition_quotes(self):
        self.assertEqual(f.validate(frame(), ['text']), [])
        self.assertEqual(f.validate(frame(condition='explicit', condition_quotes=['If rent rises']),
                                    ['If rent rises, help is needed.']), [])
        for value in [None, {}, frame(condition='explicit'), frame(condition_quotes=['invented']),
                      frame(scope='all'), frame(condition='explicit', condition_quotes=['invented'])]:
            self.assertTrue(f.validate(value, ['text']))

    def test_hard_mismatches(self):
        for key, value in [('scope', 'self'), ('time', 'future'), ('commitment', 'prediction'), ('condition', 'explicit')]:
            self.assertIn(key+'_mismatch', f.mismatch(frame(), frame(**{key:value})))
        self.assertEqual(f.mismatch(frame(), frame()), [])

    def test_uncertainty_and_mixed_are_not_positive_matches(self):
        self.assertIn('time_unclear', f.mismatch(frame(time='unclear'), frame(time='unclear')))
        self.assertIn('not_atomic', f.mismatch(frame(status='mixed'), frame()))

    def run_guard(self, left=None, right=None, condition='equivalent'):
        a, b = unit('a', 'If rent rises, help should increase.'), unit('b', 'If rents go up, help should increase.')
        calls = []
        def call(system, data, schema):
            calls.append((system, data))
            if system == f.CONDITION_SYSTEM: return result({'verdict': condition})
            value=(left or frame()) if data['TEXT'] == [a['statement']] else (right or frame())
            return result({k:value[k] for k in schema['properties']})
        stored = f.guard(call, a, b, checked_call)
        self.assertEqual(f.replay(a, b, stored), stored['allowed'])
        return a, b, stored, calls

    def test_source_and_claim_are_separate_payloads(self):
        a, b, stored, calls = self.run_guard()
        self.assertTrue(stored['allowed'])
        for system, data in calls:
            self.assertEqual(set(data), {'TEXT','COMMITMENT'} if system==f.TASK_SYSTEMS['time'] else {'TEXT'})
            self.assertNotIn('PARENT_CONTEXT', data)

    def test_condition_equivalence_is_required_not_just_presence(self):
        left = frame(condition='explicit', condition_quotes=['If rent rises'])
        right = frame(condition='explicit', condition_quotes=['If rents go up'])
        for verdict, allowed in [('equivalent', True), ('different', False), ('unclear', False)]:
            _, _, stored, calls = self.run_guard(left, right, verdict)
            self.assertEqual(stored['allowed'], allowed)
            self.assertEqual(len(stored['condition_checks']), 1)

    def test_failed_condition_request_withholds(self):
        a, b, stored, _ = self.run_guard(frame(condition='explicit', condition_quotes=['If rent rises']),
                                       frame(condition='explicit', condition_quotes=['If rents go up']))
        bad = deepcopy(stored)
        bad['condition_checks']['common']['errors'] = ['transport_error']
        with self.assertRaises(ValueError): f.replay(a, b, bad)

    def test_tampering_and_claim_change_rejected(self):
        a, b, stored, _ = self.run_guard()
        for mutate in [lambda x: x.update(allowed=False), lambda x: x['frames'].pop('a'),
                       lambda x: x.update(blocked_reasons=['fake']),
                       lambda x: x['condition_checks'].update(extra=result({'verdict':'equivalent'}))]:
            bad=deepcopy(stored); mutate(bad)
            with self.assertRaises(ValueError): f.replay(a, b, bad)
        a['statement'] = 'changed'
        with self.assertRaises(ValueError): f.replay(a, b, stored)

    def test_type_match_does_not_bypass_final_semantic_gates(self):
        from commentscope.factory.automatic_contract import passed
        _, _, stored, _ = self.run_guard()
        self.assertFalse(passed({'frame_guard': stored, 'errors': [], 'output': {
            'unit_faithful':'supported', 'compatible':'supported', 'core_supported':'unsupported', 'reason':'Different meaning'}}))

    def test_failed_components_replay_after_json_key_sort(self):
        a, b = unit('a', 'A claim'), unit('b', 'Another claim')
        def failed(*args): return {'output': None, 'errors': ['transport_error']}
        stored = f.guard(failed, a, b, checked_call)
        restored = json.loads(json.dumps(stored, sort_keys=True))
        self.assertFalse(f.replay(a, b, restored))
