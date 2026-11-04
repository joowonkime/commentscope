"""Specification traceability failures; no inference or semantic quality claims."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from unittest import TestCase

from tools import check_mvp_spec as check


ROOT = Path(__file__).resolve().parents[1]


class MVPSpecTests(TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / 'docs/mvp-traceability.json').read_text(encoding='utf-8'))

    def errors(self, document=None):
        return '\n'.join(check.validate(self.spec if document is None else document, ROOT))

    def evidence(self, kind='offline'):
        return {'kind': kind, 'scope': 'Synthetic contract regression only.',
                'reference': 'tests/test_mvp_spec.py', 'result': 'pass'}

    def test_committed_graph_and_frozen_r5_contract_are_consistent(self):
        self.assertEqual(self.errors(), '')

    def test_lost_product_task_and_dangling_requirement_are_rejected(self):
        del self.spec['product_tasks']['Reflect']
        self.assertIn('product_tasks', self.errors())
        self.spec['tasks'][0]['requirements'].append('REQ-999')
        self.assertIn('REQ-999', self.errors())

    def test_group_flow_cannot_disappear_inside_an_existing_converse_task(self):
        self.spec['product_tasks']['Converse'].remove('REQ-006')
        self.assertIn('REQ-006', self.errors())

    def test_duplicate_ids_and_dependency_cycles_are_rejected(self):
        self.spec['requirements'].append(deepcopy(self.spec['requirements'][0]))
        self.spec['tasks'][0]['depends_on'] = ['TASK-002']
        errors = self.errors()
        self.assertIn('duplicate', errors)
        self.assertIn('cycle', errors)

    def test_missing_files_and_paths_outside_repository_are_rejected(self):
        for path in ('src/commentscope/missing.py', '../private-state.json', '/tmp/private-state.json'):
            with self.subTest(path=path):
                doc = deepcopy(self.spec)
                doc['requirements'][0]['code'].append(path)
                self.assertIn('reference', self.errors(doc))

    def test_done_without_evidence_or_unfinished_prerequisites_is_rejected(self):
        self.spec['tasks'][1]['status'] = 'done'
        errors = self.errors()
        self.assertIn('evidence', errors)
        self.assertIn('unfinished dependency', errors)

    def test_offline_result_cannot_complete_a_formal_gate_task(self):
        for task in self.spec['tasks'][:4]:
            task['status'] = 'done'
            task['evidence'] = [self.evidence(kind) for kind in task['required_evidence']]
        gate = self.spec['tasks'][4]
        gate['status'] = 'done'
        gate['evidence'] = [self.evidence()]
        self.spec['resume']['next_task'] = 'TASK-006'
        self.spec['tasks'][5]['status'] = 'next'
        self.assertIn('formal_gate', self.errors())

    def test_resume_cannot_skip_dependencies_or_have_two_active_tasks(self):
        self.spec['resume']['next_task'] = 'TASK-007'
        self.spec['tasks'][6]['status'] = 'next'
        errors = self.errors()
        self.assertIn('active task', errors)
        self.assertIn('unfinished dependency', errors)

    def test_changed_r5_pin_is_rejected(self):
        self.spec['acceptance_contract']['digest'] = '0' * 64
        self.assertIn('r5', self.errors())

    def test_accepted_decision_requires_a_recorded_basis(self):
        self.spec['decisions'][0]['status'] = 'accepted'
        self.assertIn('evidence', self.errors())

    def test_malformed_data_is_reported_without_traceback(self):
        for document in (None, [], {}, {'schema_version': 1, 'requirements': [None]}):
            with self.subTest(document=document):
                self.assertTrue(check.validate(document, ROOT))
        self.spec['tasks'][0]['depends_on'] = 'TASK-002'
        self.assertTrue(self.errors())

    def test_invalid_nested_status_evidence_and_url_are_reported(self):
        self.spec['requirements'][0]['implementation'] = []
        self.spec['requirements'][0]['sources'].append('https://[invalid')
        self.spec['decisions'][0]['status'] = []
        self.spec['tasks'][0]['status'] = []
        self.spec['tasks'][0]['evidence'] = [dict(self.evidence(), kind=[])]
        self.assertTrue(self.errors())

    def test_resume_prints_current_work_and_limits_without_model_access(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/check_mvp_spec.py'), '--resume'],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.spec['spec_version'], result.stdout)
        self.assertIn('TASK-001', result.stdout)
        self.assertIn('HOLD', result.stdout)
        self.assertIn('not semantic quality', result.stdout)
