from pathlib import Path
import tempfile
import unittest

from experiments.claim_support_probe import (CachedScores, POLICIES, accepted, checks_for,
                                              evaluate_pair, render, summarize)
from experiments.claim_frame_probe import unit
from commentscope.storage import write_json_exclusive
from commentscope.factory.claim_clusters import read_json


def record(support=True):
    return {'errors': [], 'relation': 'supports' if support else 'not_established',
            'scores': {'entailment': .9 if support else .05, 'neutral': .05 if support else .9,
                       'contradiction': .05}, 'seconds': .1}


class ClaimSupportTests(unittest.TestCase):
    def test_source_inputs_and_direction(self):
        a, b = unit('a', 'source A', 'core'), unit('b', 'source B', 'detail')
        a['parent_context'] = 'Must not appear'
        b['expected'] = False
        checks = checks_for(a, b)
        self.assertEqual(checks['anchor_fidelity'], ('source A', 'core'))
        self.assertEqual(checks['common_from_source'], ('source B', 'core'))
        self.assertEqual(checks['common_to_claim'], ('core', 'detail'))
        self.assertEqual(checks['claim_to_common'], ('detail', 'core'))
        self.assertNotIn('Must not appear', repr(checks))

    def test_mutual_constraint_not_rescue_for_directional_failure(self):
        a, b = unit('a', 'A', 'core'), unit('b', 'B', 'detail')
        def score(p, h): return record((p, h) != ('core', 'detail'))
        result = evaluate_pair(a, b, score)
        self.assertTrue(result['policies']['directional']['allowed'])
        self.assertFalse(result['policies']['mutual_claims']['allowed'])
        def fail_source(p, h): return record((p, h) != ('B', 'detail'))
        result = evaluate_pair(a, b, fail_source)
        self.assertTrue(all(not r['allowed'] for r in result['policies'].values()))

    def test_invalid_anchor_cannot_be_rescued(self):
        a, b = unit('a', 'bad source', 'core'), unit('b', 'B', 'detail')
        result = evaluate_pair(a, b, lambda p, h: record(p != 'bad source'))
        for r in result['policies'].values():
            self.assertFalse(r['allowed'])
            self.assertIn('anchor_fidelity', r['blocked_checks'])

    def test_scores_and_relation_must_agree_and_errors_block(self):
        with self.assertRaises(ValueError): accepted({**record(False), 'relation': 'supports'})
        self.assertFalse(accepted({**record(), 'errors': ['RuntimeError']}))
        with self.assertRaises(ValueError): accepted({**record(), 'scores': {}})

    def test_reject_everything_has_zero_positive_retention(self):
        a = unit('a', 'A', 'claim')
        rows = [{'id': str(e), 'kind': kind, 'expected': e,
                 'nli': evaluate_pair(a, a, lambda *args: record(False))}
                for kind in ['synthetic', 'real_development'] for e in [True, False]]
        summary = summarize(rows)
        for kinds in summary.values():
            for r in kinds.values():
                self.assertEqual(r['positive_kept'], 0)
                self.assertEqual(r['negative_blocked'], 1)
                self.assertEqual(r['false_rejection_ids'], ['True'])

    def test_cache_reuse_manifest_binding_and_checkpoint_change(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = {'expires_at': '2099-01-01T00:00:00Z', 'threshold': .8}
            calls = []
            def score(*args): calls.append(args); return record()
            cached = CachedScores(d, manifest, score)
            self.assertEqual(cached('A', 'B'), cached('A', 'B'))
            self.assertEqual(len(calls), 1)
            restored = CachedScores(d, manifest, lambda *args: self.fail('Cache not reused'))
            self.assertEqual(restored('A', 'B'), record())
            with self.assertRaises(ValueError): CachedScores(d, {**manifest, 'threshold': .9}, score)
            path = next(Path(d).glob('score-*.json'))
            stored = read_json(path); stored['request']['premise'] = 'changed'
            # Replace only the test-owned checkpoint to simulate corruption.
            path.unlink(); write_json_exclusive(path, stored)
            with self.assertRaises(ValueError): CachedScores(d, manifest, score)('A', 'B')

    def test_expired_input_never_calls_model(self):
        with tempfile.TemporaryDirectory() as d:
            cached = CachedScores(d, {'expires_at': '2000-01-01T00:00:00Z'},
                                  lambda *args: self.fail('Expired model call'))
            with self.assertRaises(ValueError): cached('A', 'B')

    def test_renderer_escapes_corpus_text(self):
        a = unit('a', '<script>oops</script>', 'claim')
        report = {'summary': {}, 'results': [{'id': 'x', 'expected': True,
                                             'nli': evaluate_pair(a, a, lambda *args: record())}]}
        page = render(report)
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)


if __name__ == '__main__': unittest.main()
