import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.providers.local_nli import decide
from commentscope.storage import write_json_exclusive
from experiments import openjev_probe as p


def record(ent=.9):
    scores = {'entailment': ent, 'neutral': 1-ent, 'contradiction': 0.}
    return {'errors': [], 'scores': scores, 'relation': decide(scores), 'seconds': .01}


class OpenJevProbeTests(unittest.TestCase):
    def cases(self):
        return [{'id': 'positive', 'source': 'Trains are useful.', 'target': 'Trains are useful.',
                 'expected': True, 'task': 'fidelity', 'split': 'test'},
                {'id': 'negative', 'source': 'Trains are useful.', 'target': 'Trains are harmful.',
                 'expected': False, 'task': 'fidelity', 'split': 'test'}]

    def test_bad_case_inventory_rejected(self):
        a = self.cases()[0]
        for cases in [[], [a, a], [{**a, 'expected': 1}], [{**a, 'source': 'x'*501}]]:
            with self.assertRaises(ValueError): p.validate_cases(cases)

    def test_all_rejections_do_not_count_as_success(self):
        s = p.summarize(self.cases(), {c['id']: record(.1) for c in self.cases()})['test']
        self.assertEqual(s['positive_kept'], 0); self.assertEqual(s['negative_blocked'], 1)

    def test_transport_errors_are_not_correct_negative_decisions(self):
        r = {c['id']: {'errors': ['RuntimeError'], 'relation': None} for c in self.cases()}
        s = p.summarize(self.cases(), r)['test']
        self.assertEqual(s['errors'], 2); self.assertEqual(s['negative_blocked'], 0)

    def test_changed_relation_label_is_rejected(self):
        r = record(); r['relation'] = 'contradicts'
        with self.assertRaises(ValueError): p.summarize(self.cases(), {'positive': r, 'negative': record(.1)})

    def test_transfer_fixture_is_balanced_and_kept_separate(self):
        cases = json.loads(Path('tests/fixtures/openjev-transfer-cases.json').read_text())['cases']
        self.assertEqual(len(cases), 12); self.assertEqual(sum(c['expected'] for c in cases), 6)
        self.assertEqual(len({c['id'] for c in cases}), 12)

    def test_only_source_target_enter_inference_and_checkpoints(self):
        seen = []
        class Fake:
            metadata = {'test': True}
            def score(self, source, target):
                seen.append((source, target))
                return record(.9 if source == target else .1)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            plan = {'expires_at': '2099-01-01T00:00:00Z', 'inputs': {}, 'code_sha256': {},
                    'cases': self.cases(), 'models': {'deberta': {'test': True}}}
            write_json_exclusive(directory/'plan.json', plan)
            with patch('sys.argv', ['probe', '--run-dir', tmp, '--phase', 'deberta', '--diagnostic-only']), \
                 patch.object(p.local_nli, 'LocalNLI', Fake), patch.object(p, 'version', return_value='test'), \
                 patch('builtins.print'):
                p.main()
            self.assertEqual(seen, [(c['source'], c['target']) for c in self.cases()])
            for path in (directory/'deberta').glob('score-*.json'):
                value = json.loads(path.read_text())
                self.assertEqual(set(value['request']), {'premise', 'hypothesis'})
                self.assertEqual(value['result_sha256'], digest(value['result']))

    def test_html_escapes_source_and_target(self):
        cases = [{**c, 'source': '<script>x</script>'} for c in self.cases()]
        records = {c['id']: record() for c in cases}
        summary = p.summarize(cases, records)
        page = p.render({'cases': cases, 'records': {n: records for n in ['deberta', 'openjev']},
                         'summaries': {n: summary for n in ['deberta', 'openjev']}, 'performance': {}, 'limitations': []})
        self.assertNotIn('<script>', page); self.assertIn('&lt;script&gt;', page)
