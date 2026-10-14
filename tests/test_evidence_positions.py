from copy import deepcopy
import unittest

from commentscope.factory import evidence_positions as p, evidence_units as old


class EvidencePositionsTests(unittest.TestCase):
    def test_topic_uses_exact_unicode_offsets_and_preserves_whitespace(self):
        text = '기후\t정책은  중요하다. Climate policy matters.'
        span = p.topic_span(text, {'first': 'T000', 'last': 'T001'})
        self.assertEqual(span['text'], '기후\t정책은')
        self.assertEqual(text[span['start']:span['end']], span['text'])

    def test_no_free_text_foreign_id_reversal_or_long_topic(self):
        for value in [{'first': 'T000', 'last': 'T999'}, {'first': 'T001', 'last': 'T000'},
                      {'first': 'T000', 'last': 'T000', 'text': 'invented'}, {'first': [], 'last': 'T000'}]:
            with self.assertRaises(ValueError): p.topic_span('Trains work.', value)
        with self.assertRaises(ValueError): p.topic_span('x'*121, {'first': 'T000', 'last': 'T000'})

    def test_status_and_topic_inventory_must_match(self):
        for v in [{'status': 'substantive', 'topic': []},
                  {'status': 'unclear', 'topic': [{'first': 'T000', 'last': 'T000'}]},
                  {'status': 'substantive', 'topic': [], 'statement': 'invented'}]:
            self.assertTrue(p.validate_topic(v, 'Trains work.'))

    def test_repeated_topic_keeps_selected_occurrence_not_nearest_text_match(self):
        text = 'Trains are fast. Boats are slow. Trains need maintenance.'
        topic = {'first': 'T000', 'last': 'T000'}
        unit = p.bind('s', text, {'first': 'S002', 'last': 'S002'}, topic)
        self.assertEqual(unit['topic_span']['start'], 0)
        p.validate_bound(unit, text)
        changed = deepcopy(unit); changed['topic_span']['start'] = text.rfind('Trains')
        with self.assertRaises(ValueError): p.validate_bound(changed, text)

    def test_source_and_saved_evidence_tampering_fails(self):
        text = 'Trains are fast. They need maintenance.'
        unit = p.bind('s', text, {'first': 'S001', 'last': 'S001'}, {'first': 'T000', 'last': 'T000'})
        for field in ['statement', 'topic_quote', 'source_comment_id']:
            bad = deepcopy(unit); bad[field] += ' invented'
            with self.assertRaises(ValueError): p.validate_bound(bad, text)
        bad = deepcopy(unit); bad['spans'][0]['text'] = 'Foreign parent.'
        with self.assertRaises(ValueError): p.validate_bound(bad, text)
        with self.assertRaises(ValueError): p.validate_bound(unit, text+' changed')

    def test_excess_context_is_deferred_without_truncation(self):
        text = 'Trains are useful. '+'x'*510+'. They need maintenance.'
        self.assertIsNone(p.bind('s', text, {'first': 'S002', 'last': 'S002'}, {'first': 'T000', 'last': 'T000'}))

    def test_final_check_sees_exact_saved_evidence_not_full_comment(self):
        text = 'External prefix. '+'A'*450+'. Trains are useful. They need maintenance. Another sentence.'
        ts = p.tokens(text); tid = next(t['id'] for t in ts if t['text'] == 'maintenance.')
        # Last focus avoids the oversized preceding sentence in the selected window.
        unit = p.bind('s', text, {'first': 'S004', 'last': 'S004'}, {'first': tid, 'last': tid})
        self.assertIsNotNone(unit)
        seen = []
        def calls(system, data, schema):
            seen.append(data)
            return {'errors': [], 'output': {'status': 'context_dependent'}}
        result = p.final_check(unit, calls)
        self.assertFalse(result['allowed'])
        self.assertEqual(set(seen[0]), {'FINAL_EVIDENCE', 'FOCUS', 'TOPIC'})
        self.assertEqual(seen[0]['FINAL_EVIDENCE'], ''.join(s['text'] for s in unit['spans']))
        self.assertNotIn('External prefix', seen[0]['FINAL_EVIDENCE'])

    def test_same_candidates_feed_position_only_and_final_policy(self):
        def calls(system, data, schema):
            if system == old.SELECT_SYSTEM:
                return {'errors': [], 'output': {'status': 'substantive', 'ranges': [{'first': 'S000', 'last': 'S000'}]}}
            if system == p.TOPIC_SYSTEM:
                return {'errors': [], 'output': {'status': 'substantive', 'topic': [{'first': 'T000', 'last': 'T000'}]}}
            return {'errors': [], 'output': {'status': 'context_dependent'}}
        report = p.extract('s', 'Trains should improve.', calls)
        self.assertEqual(len(report['position_units']), 1)
        self.assertEqual(report['units'], [])
        self.assertEqual(report['candidates'][0]['reason'], 'final_context_dependent')

    def test_formula_never_reaches_topic_or_final_model(self):
        def calls(system, data, schema):
            self.assertEqual(system, old.SELECT_SYSTEM)
            return {'errors': [], 'output': {'status': 'substantive', 'ranges': [{'first': 'S000', 'last': 'S000'}]}}
        self.assertFalse(p.extract('s', 'We should do it.', calls)['units'])

    def test_runtime_error_not_semantic_exclusion(self):
        unit = p.bind('s', 'Trains work.', {'first':'S000','last':'S000'}, {'first':'T000','last':'T000'})
        calls = lambda *args: {'errors': ['transport_error'], 'output': None}
        result = p.final_check(unit, calls)
        self.assertFalse(result['allowed']); self.assertTrue(result['result']['errors'])


if __name__ == '__main__': unittest.main()
