"""Exercise r5 thresholds through the real offline gate evaluator."""
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory import acceptance
from commentscope.storage import write_json_exclusive as write
from experiments import minimal_factory_review as review


class R5ReviewTests(TestCase):
    def evaluate(self, gate, preserved, *, legacy=False, wrong_support=False):
        count, meaningful = (24, 19) if gate == 'G2' else (96, 74)
        version = review.VERSION if legacy else review.R5_VERSION
        profile = json.loads(Path('tests/fixtures/factory-acceptance-r5.json').read_text())
        with tempfile.TemporaryDirectory(dir='runs', prefix='test-r5-review-') as tmp:
            root = Path(tmp); scope = [f's{i}' for i in range(count)]
            plan = {'gate': gate, 'scope_ids': scope}
            if not legacy: plan.update(goal_revision=acceptance.R5, acceptance_profile=profile,
                                       acceptance_profile_sha256=digest(profile))
            write(root/'plan.json', plan)
            tasks = [{'id': 'source:'+sid, 'kind': 'source', 'key': sid, 'data': {}} for sid in scope]
            tasks.append({'id': 'support:x', 'kind': 'support', 'key': ['c', 's0'], 'data': {}})
            packet = {'artifact_kind': version+'-packet', 'run': str(root),
                      'plan_sha256': review.sha(root/'plan.json'), 'output_sha256': 'o', 'runtime_sha256': 'r',
                      'tasks': tasks, 'fact_benchmark': {'passed': True}}
            rows = [{'id': t['id'], 'verdict': ('pass' if i < preserved or t['kind'] == 'support' else 'fail'),
                     'reason': 'Authored test judgment.', 'label': None, 'omissions': []} for i, t in enumerate(tasks)]
            if wrong_support: rows[-1]['verdict'] = 'fail'
            write(root/'packet.json', packet)
            write(root/'review.json', {'artifact_kind': version+'-review', 'packet_sha256': digest(packet),
                                      'evaluator': 'synthetic test', 'rows': rows})
            loaded = (plan, {'binding_errors': 0, 'output_sha256': 'o', 'runtime_sha256': 'r'}, None,
                      {'agent_inputs': {'map': {'opinion_map': {}}}}, {})
            read, sha = review.read_json, review.sha
            def fixture_read(path):
                if str(path) == 'runs/design-freeze-20261016/samples.json':
                    return {'meaning_reference': 'synthetic-reference', 'meaning_reference_sha256': 'fixed'}
                if str(path) == 'synthetic-reference':
                    return {'rows': [{'source_id': f's{i}' if i < meaningful else f'outside{i}',
                                      'eligibility': 'meaningful'} for i in range(755)]}
                return read(path)
            with patch.object(review, 'load_run', return_value=loaded), patch.object(review, 'read_json', side_effect=fixture_read), \
                    patch.object(review, 'sha', side_effect=lambda p: 'fixed' if str(p) == 'synthetic-reference' else sha(p)):
                return review.evaluate(root, root/'review.json', root/'result.json')

    def test_11_12_of_19_and_44_45_of_74_boundaries(self):
        for gate, minimum in [('G2', 12), ('G3', 45)]:
            with self.subTest(gate=gate):
                self.assertFalse(self.evaluate(gate, minimum-1)['gate_passed'])
                self.assertTrue(self.evaluate(gate, minimum)['gate_passed'])

    def test_old_run_still_requires_eighty_percent(self):
        self.assertFalse(self.evaluate('G2', 12, legacy=True)['gate_passed'])
        self.assertTrue(self.evaluate('G2', 16, legacy=True)['gate_passed'])

    def test_r5_support_error_vetoes_even_perfect_preservation(self):
        self.assertFalse(self.evaluate('G2', 19, wrong_support=True)['gate_passed'])
