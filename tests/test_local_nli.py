import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from commentscope.providers.local_nli import LocalNLI, decide
from commentscope.factory.extractive_keypoints import anchors_for, assemble, SYSTEM, SCHEMA
from experiments.compare_local_nli import check_baseline, evaluate, validate_cases, render_comparison


class LocalNLITests(unittest.TestCase):
    def test_label_mapping_and_threshold(self):
        self.assertEqual(decide({'entailment': .8, 'neutral': .1, 'contradiction': .1}), 'supports')
        self.assertEqual(decide({'entailment': .79, 'neutral': .11, 'contradiction': .1}), 'unclear')
        self.assertEqual(decide({'entailment': .01, 'neutral': .98, 'contradiction': .01}), 'not_established')
        self.assertEqual(decide({'entailment': .01, 'neutral': .01, 'contradiction': .98}), 'contradicts')

    def test_invalid_scores_fail_closed(self):
        for scores in [{'LABEL_0': 1}, {'entailment': float('nan'), 'neutral': 0, 'contradiction': 0},
                       {'entailment': .8, 'neutral': .8, 'contradiction': 0},
                       {'entailment': True, 'neutral': 0, 'contradiction': 0},
                       {'entailment': -1, 'neutral': 1, 'contradiction': 1}]:
            with self.assertRaises(ValueError): decide(scores)

    def scorer(self, tokens=12):
        scorer = LocalNLI.__new__(LocalNLI)
        scorer.tokenizer = MagicMock(return_value={'input_ids': SimpleNamespace(shape=(1, tokens))})
        scorer.model = MagicMock()
        scorer.model.config.max_position_embeddings = 512
        logits = MagicMock()
        logits.softmax.return_value.tolist.return_value = [.9, .05, .05]
        logits.tolist.return_value = [3, 0, 0]
        scorer.model.return_value.logits.__getitem__.return_value = logits
        scorer.torch = MagicMock()
        scorer.labels = {0: 'entailment', 1: 'neutral', 2: 'contradiction'}
        return scorer

    def test_premise_first_hypothesis_second_and_no_truncation(self):
        scorer = self.scorer()
        result = scorer.score('source', 'representative')
        scorer.tokenizer.assert_called_once_with('source', 'representative', return_tensors='pt', truncation=False)
        self.assertEqual(result['relation'], 'supports')
        self.assertEqual(result['scores']['entailment'], .9)
        self.assertFalse(result['human_approved'])
        self.assertEqual(result['origin'], 'local_nli')

    def test_long_token_input_rejected_before_model(self):
        scorer = self.scorer(tokens=513)
        result = scorer.score('source', 'representative')
        scorer.model.assert_not_called()
        self.assertIsNone(result['relation']); self.assertTrue(result['errors'])

    def test_invalid_source_rejected_before_tokenizer(self):
        for source in ['', ' ', None, 'x'*501]:
            scorer = self.scorer()
            self.assertIsNone(scorer.score(source, 'representative')['relation'])
            scorer.tokenizer.assert_not_called()

    def test_runtime_failure_is_not_neutral_or_support(self):
        scorer = self.scorer(); scorer.model.side_effect = RuntimeError('inference failed')
        result = scorer.score('source', 'representative')
        self.assertIsNone(result['relation']); self.assertEqual(result['errors'], ['RuntimeError'])

    def test_suite_has_positive_negative_contradiction_ambiguity(self):
        suite = json.loads((Path(__file__).parent/'fixtures/synthetic-support-cases.json').read_text())
        validate_cases(suite['cases'])
        counts = {k: sum(c['category'] == k for c in suite['cases'])
                  for k in ['positive', 'negative', 'contradiction', 'ambiguous']}
        self.assertEqual(counts, {'positive': 8, 'negative': 8, 'contradiction': 2, 'ambiguous': 2})
        self.assertFalse(suite['human_approved']); self.assertFalse(suite['independent_gold'])

    def test_duplicate_or_invalid_cases_rejected(self):
        case = {'id': 'a', 'category': 'positive', 'source': 'a', 'representative': 'b', 'allowed': ['supports']}
        for cases in [[case, case], [{**case, 'allowed': []}], [{**case, 'source': ''}]]:
            with self.assertRaises(ValueError): validate_cases(cases)

    def test_real_evaluation_cannot_count_identity(self):
        case = {'id': 'a->a', 'category': 'positive', 'allowed': ['supports']}
        with self.assertRaises(ValueError):
            validate_cases([case], real=True, pairs={'a->a': {'origin': 'identity_text_only'}})

    def test_all_unclear_does_not_pass_positive_or_exact_negative(self):
        cases = [{'id': 'p', 'category': 'positive', 'allowed': ['supports']},
                 {'id': 'n', 'category': 'negative', 'allowed': ['not_established']}]
        records = {c['id']: {'relation': 'unclear', 'errors': []} for c in cases}
        result = evaluate(cases, records)
        self.assertEqual(result['positive']['matches'], 0)
        self.assertEqual(result['negative']['matches'], 0)
        records['p'] = {'relation': 'supports', 'errors': ['invalid']}
        self.assertEqual(evaluate(cases, records)['positive']['matches'], 0)

    def test_baseline_text_or_assembly_change_rejected(self):
        members = {'M1': {'source_comment_id': 's', 'target': 'original'}}
        anchors = anchors_for(members)
        pairs = {'M1->M1': {'source': 'M1', 'anchor': 'M1', 'relation': 'supports', 'errors': []}}
        prepared = {'snapshot_sha256': 's', 'extraction_sha256': 'e', 'expires_at': 'expiry'}
        baseline = {**prepared, 'candidate_sha256': 'c', 'members': members, 'anchors': anchors,
                    'pairs': pairs, 'assembly': assemble(members, anchors, pairs),
                    'prompt_sha256': hashlib.sha256(SYSTEM.encode()).hexdigest(), 'generation_schema': SCHEMA,
                    'request_settings': {'temperature': 0, 'seed': 407, 'max_tokens': 3000}}
        with patch('experiments.compare_local_nli.sha', return_value='c'):
            check_baseline(baseline, prepared, members, anchors, 'unused')
            bad = copy.deepcopy(baseline); bad['anchors']['M1']['text'] = 'edited'
            with self.assertRaises(ValueError): check_baseline(bad, prepared, members, anchors, 'unused')
            bad = copy.deepcopy(baseline); bad['assembly']['accepted_perspectives'] = 1
            with self.assertRaises(ValueError): check_baseline(bad, prepared, members, anchors, 'unused')
            bad = copy.deepcopy(baseline); bad['prompt_sha256'] = 'changed'
            with self.assertRaises(ValueError): check_baseline(bad, prepared, members, anchors, 'unused')

    def test_comparison_html_escapes_untrusted_text(self):
        case = {'id': 'a', 'allowed': ['supports'], 'source': '<script>x</script>', 'representative': 'a'}
        report = {'summary': {}, 'real_cases': [], 'real': {}, 'synthetic_cases': [case],
                  'synthetic': {m: {'a': {'relation': 'supports', 'errors': []}} for m in ['qwen', 'nli']}}
        nli_report = {'summary': {}, 'members': {}, 'anchors': {}, 'pairs': {},
                      'assembly': {'groups': [], 'unassigned': []}}
        page = render_comparison(report, nli_report)
        self.assertNotIn('<script>', page); self.assertIn('&lt;script&gt;', page)
