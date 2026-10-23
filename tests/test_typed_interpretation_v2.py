"""Contract controls use authored responses, not model accuracy measurements."""
from copy import deepcopy
import unittest

from commentscope.factory import typed_interpretation_v2 as v2


def source(text, sid='A', parent=None):
    return {'id': sid, 'text': text, 'parent': parent}


def claim(quote, sid='S1', **changes):
    return {'id': sid, 'quote': quote, 'occurrence': 1, 'meaning': quote,
            'voice': 'author', 'force': 'assertion', 'setting': 'real',
            'content_type': 'topic_view', 'unresolved': [], **changes}


def output(statements, attachments=(), **changes):
    return {'id': 'A', 'coverage': 'complete', 'statements': statements,
            'attachments': list(attachments), 'unresolved': [], **changes}


def view(text, statements, attachments=(), **changes):
    return v2.comparison_view(v2.bind(source(text), output(statements, attachments, **changes)), 'S1')


class TypedInterpretationV2Tests(unittest.TestCase):
    def test_metadata_preserved_without_topic_comparison_or_keyword_filter(self):
        examples = [('This video was published in 2018.', 'source_metadata', False),
                    ('The creator forgot the accessibility issue.', 'discussion_quality', True),
                    ('The creator is right: extend service.', 'topic_view', True)]
        for text, kind, available in examples:
            with self.subTest(text=text):
                result = view(text, [claim(text, content_type=kind)])
                self.assertEqual(result['original_span']['text'], text)
                self.assertEqual(result['operand'] is not None, available)
                self.assertFalse(result['membership_approved'])

    def test_mixed_metadata_and_topic_stance_only_routes_correct_statement(self):
        s = source('This video is old. Extend service.')
        r = v2.bind(s, output([claim('This video is old.', content_type='source_metadata'),
                              claim('Extend service.', 'S2')]))
        self.assertIsNone(v2.comparison_view(r, 'S1')['operand'])
        self.assertIsNotNone(v2.comparison_view(r, 'S2')['operand'])
        self.assertEqual(len(r['statements']), 2)

    def test_contextual_attitude_is_not_filtered_for_shortness_or_lack_of_reason(self):
        s = source('Deal with it', parent={'id': 'P', 'text': 'The delays are sad.'})
        r = v2.bind(s, output([claim(s['text'], content_type='contextual_attitude', force='recommendation')]))
        self.assertIsNotNone(v2.comparison_view(r, 'S1')['operand'])
        self.assertFalse(r['quality_gate_passed'])

    def test_local_unresolved_reference_holds_paraphrase_only_at_its_statement(self):
        s = source('They should fix it. Extend service.')
        first = claim('They should fix it.', meaning='The city should fix the station.',
                      unresolved=['They and it have multiple possible referents.'])
        r = v2.bind(s, output([first, claim('Extend service.', 'S2')]))
        v = v2.comparison_view(r, 'S1')
        self.assertIsNone(v['operand']); self.assertNotIn('city', str(v))
        self.assertEqual(v['original_span']['text'], first['quote'])
        self.assertIsNotNone(v2.comparison_view(r, 'S2')['operand'])
        original = v2.raw_comparison_source(r)
        self.assertEqual(original, s)
        self.assertNotIn('city', str(original))
        self.assertIsNone(v2.comparison_view(r, 'S1')['operand'])

    def test_source_wide_uncertainty_and_partial_coverage_hold_comparison(self):
        for changes in ({'unresolved': ['The source-wide attribution is unclear.']}, {'coverage': 'partial'}):
            v = view('Continue.', [claim('Continue.')], **changes)
            self.assertIsNone(v['operand'])

    def test_fiction_and_condition_coexist_without_an_actual_world_fact(self):
        text = 'If the spell works, everyone can fly.'
        v = view(text, [claim(text, setting='fictional', force='hypothetical')])
        self.assertEqual(v['operand']['setting'], 'fictional')
        self.assertEqual(v['operand']['contingency'], 'explicit_condition')
        self.assertEqual(v['operand']['full_original_span']['text'], text)
        self.assertFalse(v['operand']['semantic_approval'])

    def test_code_detects_scope_when_model_omits_attachment_and_rejects_mixed_role(self):
        text = 'If I have time, even if it rains, I will help.'
        raw = claim(text, force='hypothetical')
        v = view(text, [raw])
        self.assertEqual([s['kind'] for s in v['operand']['surface_scope']], ['condition', 'concession'])
        wrong = {'statement_id': 'S1', 'kind': 'condition', 'origin': 'comment',
                 'quote': 'If I have time, even if it rains', 'occurrence': 1}
        held = view(text, [raw], [wrong])
        self.assertIsNone(held['operand']); self.assertIn('condition_concession_conflict', held['holds'])

    def test_unknown_scope_and_reported_speech_remain_held(self):
        self.assertIsNone(view('Use A unless B.', [claim('Use A unless B.')])['operand'])
        self.assertIsNone(view('They said continue.', [claim('They said continue.', voice='reported')])['operand'])

    def test_known_because_projection_keeps_source_reasons_separate(self):
        operands = [view(text, [claim(text)])['operand'] for text in
                    ('Open earlier because visitors arrive early.', 'Open earlier because queues are long.')]
        self.assertEqual([o['position_span']['text'] for o in operands], ['Open earlier', 'Open earlier'])
        self.assertNotEqual(operands[0]['full_original_span'], operands[1]['full_original_span'])

    def test_tampering_route_or_scope_or_source_fails_replay(self):
        r = v2.bind(source('The video is old.'), output([claim('The video is old.', content_type='source_metadata')]))
        for mutate in (lambda x: x['statements'][0].update(content_route='topic_proposal'),
                       lambda x: x['statements'][0].update(comparison_holds=[]),
                       lambda x: x['source'].update(text='Different.'),
                       lambda x: x.update(counted_supports=1)):
            changed = deepcopy(r); mutate(changed)
            with self.assertRaises(ValueError): v2.validate(changed)

    def test_missing_and_duplicate_sources_do_not_erase_valid_neighbor(self):
        a = output([claim('A.')]); b = output([claim('B.')], id='B')
        for cases in ([a, a, b], [b]):
            result = v2.bind_batch([source('A.'), source('B.', 'B')], {'cases': cases})
            self.assertEqual([r['source']['id'] for r in result['records']], ['B'])
            self.assertEqual([e['id'] for e in result['errors']], ['A'])

    def test_wire_contract_has_no_relevance_or_mutually_exclusive_world(self):
        case = v2.schema(['A'])['properties']['cases']['items']
        statement = case['properties']['statements']['items']
        self.assertNotIn('relevance', case['properties']); self.assertNotIn('world', statement['properties'])
        self.assertIn('setting', statement['properties']); self.assertIn('content_type', statement['properties'])


if __name__ == '__main__': unittest.main()
