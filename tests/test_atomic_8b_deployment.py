from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments.atomic_discovery_probe import invocation
from experiments.atomic_8b_deployment import prepare


class Atomic8BDeploymentTests(unittest.TestCase):
    def fixture(self, root):
        source, model, output = (root / name for name in ('source', 'model', 'output'))
        rows = []
        for i in range(20):
            sources = {f's{i}': f'Original source {i}.'}
            req = invocation(sources)
            rows.append({'id': f'C{i:03}', 'sources': sources, 'request': req,
                         'request_sha256': digest(req)})
        original = {'rows': rows, 'inputs': {}, 'runtime': {'context': 8192},
                    'models': {'baseline': {'name': '4B'}}, 'server': {}, 'model': {}}
        deployment = {'models': {'baseline': {'name': '8B'}}, 'server': {'path': 'server'},
                      'runtime': {'reasoning': 'on', 'context': 4096}, 'model': {'name': '8B'}}
        write(source / 'plan.json', original)
        write(model / 'plan.json', deployment)
        return source, model, output, original

    def test_same_twenty_requests_and_separate_new_target_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, model, output, original = self.fixture(Path(tmp))
            before = sha(source / 'plan.json')
            with patch('experiments.atomic_8b_deployment.validate'), patch('experiments.atomic_8b_deployment.code_hashes', return_value={}):
                prepare(output, source, model)
            plan = read_json(output / 'plan.json')
            self.assertEqual(plan['rows'], original['rows'])
            self.assertEqual(sha(source / 'plan.json'), before)
            self.assertEqual(plan['models']['baseline']['name'], '8B')
            self.assertEqual(plan['runtime']['reasoning'], 'off')
            self.assertEqual(plan['runtime']['context'], 8192)
            self.assertEqual(plan['new_relation_protocol']['criteria']['sample_size'], 100)
            self.assertEqual(plan['new_relation_protocol']['retries'], 0)
            with self.assertRaises(ValueError): prepare(output, source, model)

    def test_changed_source_or_prompt_is_not_matched_comparison(self):
        for mutation in ('count', 'source', 'request', 'hash', 'input'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                source, model, output, original = self.fixture(Path(tmp))
                altered = deepcopy(original)
                if mutation == 'count': altered['rows'].pop()
                elif mutation == 'source': altered['rows'][0]['sources']['s0'] = 'Changed'
                elif mutation == 'request':
                    altered['rows'][0]['request']['max_tokens'] = 900
                    altered['rows'][0]['request_sha256'] = digest(altered['rows'][0]['request'])
                elif mutation == 'hash': altered['rows'][0]['request_sha256'] = 'bad'
                else: altered['inputs'] = {str(source / 'plan.json'): 'wrong hash'}
                # Write an independent deliberately invalid fixture, not an old plan.
                bad = Path(tmp) / 'invalid'
                write(bad / 'plan.json', altered)
                with self.assertRaises(ValueError): prepare(output, bad, model)
                self.assertFalse(output.exists())
