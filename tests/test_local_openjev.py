from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from commentscope.providers.local_openjev import LocalOpenJev, format_pair


class LocalOpenJevTests(unittest.TestCase):
    def test_pair_preserves_order_whitespace_and_braces(self):
        self.assertEqual(format_pair(' a {x}\n', 'b'), 'Premise:  a {x}\n\nHypothesis: b')

    def test_invalid_input_is_not_truncated(self):
        for source in ['', ' ', None, 'x'*501]:
            with self.assertRaises(ValueError): format_pair(source, 'target')

    def scorer(self, tokens=12):
        x = LocalOpenJev.__new__(LocalOpenJev)
        x.device = 'cpu'; x.torch = MagicMock()
        ids = MagicMock(); ids.shape = (1, tokens)
        x.tokenizer = MagicMock(return_value={'input_ids': ids})
        x.model = MagicMock()
        logits = x.model.return_value.logits.__getitem__.return_value.float.return_value
        logits.softmax.return_value.tolist.return_value = [.05, .9, .05]
        logits.tolist.return_value = [0., 3., 0.]
        return x

    def test_pinned_label_order_and_source_first(self):
        x = self.scorer(); r = x.score('source', 'target')
        x.tokenizer.assert_called_once_with('Premise: source\nHypothesis: target', return_tensors='pt', truncation=False)
        self.assertEqual(r['relation'], 'supports')
        self.assertEqual(r['scores']['entailment'], .9)
        self.assertFalse(r['human_approved'])

    def test_long_tokens_fail_before_inference(self):
        x = self.scorer(513); r = x.score('source', 'target')
        x.model.assert_not_called(); self.assertIsNone(r['relation'])
        self.assertEqual(r['errors'], ['ValueError'])

    def test_inference_error_is_not_a_semantic_rejection(self):
        x = self.scorer(); x.model.side_effect = RuntimeError('failure')
        r = x.score('source', 'target')
        self.assertEqual(r['errors'], ['RuntimeError']); self.assertIsNone(r['relation'])
