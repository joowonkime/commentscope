import unittest
from experiments.mvp_probe_report import render


class MVPProbeReportTests(unittest.TestCase):
    def test_source_and_answer_strings_are_escaped_and_scope_is_clear(self):
        metric = {'supported_kept': 9, 'unsupported_false_support': 0, 'development_gate_passed': True}
        llm = {'rows': [], **metric, 'fact_decision_development_gate_passed': True}
        nli = {'variants': {'nli_only': {**metric, 'rows': []}, 'unanimous_llm_nli': metric}}
        answer = {'scores': [{'question_id': 'Q1', 'candidate_id': c, 'passed': True} for c in ['P1', 'P2']],
                  'counts': dict.fromkeys(['answerable', 'unanswerable'], {'passed': 1, 'total': 1}),
                  'comparison_p95_seconds': 1}
        turn = {'status': 'answered', 'answerability': 'grounded', 'limitation': 'none',
                'points': [{'text': '<img onerror="bad()">', 'kind': 'value', 'member_source_count': 3, 'epistemic_status': 'attributed'}]}
        page = render({'rows': []}, llm, nli, {'rows': [{'id': 'Q1', 'text': '<script>bad()</script>'}]}, answer,
                      [{'seconds': 1, 'turns': {'P1': turn, 'P2': turn}}])
        self.assertNotIn('<script>', page); self.assertNotIn('<img ', page)
        self.assertIn('&lt;script&gt;', page); self.assertIn('합성', page)
        self.assertIn('자동 MVP 전체 완료 화면이 아닙니다', page)


if __name__ == '__main__': unittest.main()
