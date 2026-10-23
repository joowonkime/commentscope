import unittest

from commentscope.factory import interpretation_scope as scope
from commentscope.factory import typed_interpretation as v1


class InterpretationScopeTests(unittest.TestCase):
    def test_condition_and_even_if_concession_are_distinct_across_topics(self):
        for activity in ('visit the library', 'ride the tram', 'study art'):
            text = f'If I have time, even if it rains, I will {activity}.'
            result = scope.parse(text)
            self.assertEqual([(s['kind'], s['span']['text']) for s in result['scopes']],
                             [('condition', 'If I have time'), ('concession', 'even if it rains')])
            self.assertEqual(result['text'], text); self.assertFalse(result['semantic_approval'])

    def test_even_if_alone_is_never_a_required_condition(self):
        for text in ('Even if it rains, I will visit.', 'I will visit, even if it rains.'):
            result = scope.parse(text)
            self.assertEqual([s['kind'] for s in result['scopes']], ['concession'])

    def test_only_if_and_plain_if_preserve_complete_statement(self):
        for text, expected in [('I agree only if repairs are free.', 'only if repairs are free.'),
                               ("If I have time, I'll help.", 'If I have time')]:
            result = scope.parse(text)
            self.assertEqual(result['scopes'][0]['span']['text'], expected)
            self.assertEqual(result['text'], text)

    def test_unknown_nested_quoted_or_negated_forms_are_not_guessed(self):
        for text in ('If A, B, C.', 'If A, B if C.', 'Unless A, B.', 'Only if A, B.',
                     'Not only if A.', 'If A (or B), C.', 'They said "If A, B."',
                     'If A because B, C.', 'If A, B; otherwise C.', 'If A, B. If C, D.',
                     'If, then.', 'Even if, leave.'):
            with self.subTest(text=text):
                r = scope.parse(text)
                self.assertEqual(r['status'], 'requires_interpretation')
                self.assertEqual(r['scopes'], [])

    def test_scope_absence_is_not_a_proof_of_unconditional_meaning(self):
        r = scope.parse('무료라면 방문하겠습니다.')
        self.assertEqual(r['status'], 'no_recognized_scope_marker')
        self.assertFalse(r['semantic_approval']); self.assertFalse(r['factual_verification'])

    def test_conflict_detects_combined_condition_concession_without_changing_output(self):
        text = 'If I have time, even if it rains, I will visit.'
        original = 'Another sentence. ' + text
        statement = {'span': v1.quote_span(original, text)}
        attachment = {'kind': 'condition', 'origin': 'comment',
                      'span': v1.quote_span(original, 'If I have time, even if it rains')}
        result = scope.audit(statement, [attachment])
        self.assertEqual(len(result['conflicts']), 1)
        self.assertEqual(result['syntax']['scopes'][1]['span']['text'], 'even if it rains')
        self.assertEqual(result['syntax']['scopes'][0]['span']['start'], len('Another sentence. '))
        self.assertEqual(result['original_statement_span'], statement['span'])


if __name__ == '__main__': unittest.main()
