from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory import source_first, source_index
from commentscope.ingestion.normalize import NormalizedComment
from commentscope.storage import write_json_exclusive as write
from experiments import candidate_completion_pipeline as p
from experiments.grounding_contract_demo import fixture
from tests.test_source_first import output
from tests import test_fresh_grounded_pipeline as fresh_tests


POSITIONS = ['Safety reviews should be required.', 'Safety reviews should be voluntary.']
SOURCES = {f's{i}{j}': t+f' Additional context {j}.' for i, t in enumerate(POSITIONS) for j in range(3)}
NORMALIZED = [NormalizedComment(k, v, 'test', None) for k, v in SOURCES.items()]


class SyntheticRunner(p.CompletionRunner):
    audit_fails = False

    def call(self, stage, req, **kwargs):
        self.timeout(90); self.seq += 1
        if stage == 'embedding':
            vectors = [[1., 0.] if 'required' in s else [0., 1.] for s in SOURCES.values()]
            raw = {'sources': {k: {'text': v} for k, v in SOURCES.items()},
                   'clusters': [{'id': f'G{i}', 'members': [f's{i}{j}' for j in range(3)]} for i in range(2)],
                   'source_index': source_index.build(NORMALIZED, vectors, p.sha(self.plan['snapshot']), p.MODEL, p.REVISION, sources=SOURCES)}
            write(req['data']['output'], raw); return {'sha256': p.sha(req['data']['output'])}
        if stage in ('source-extraction', 'member-extraction'):
            text = req['data']['TARGET'].split(' Additional')[0]
            value = output(text, stance='support' if 'required' in text else 'oppose')
        elif stage == 'discovery-candidates':
            units = req['data']['units']; vectors = [[1., 0.] if 'required' in u['claim'] else [0., 1.] for u in units]
            return {**source_first.candidates(units, vectors, req['data']['sources'], minimum_sources=1),
                    'unit_ids': [u['claim_id'] for u in units],
                    'embedding_texts': [source_first.embedding_text(u) for u in units], 'vectors': vectors}
        elif stage == 'support-ranking':
            return {'rows': [{'id': r['id'], 'pair_sha256': p.digest(r), 'errors': [],
                              'scores': {'entailment': .98, 'neutral': .01, 'contradiction': .01}} for r in req['data']['pairs']]}
        elif stage.startswith('core-') and stage != 'core-kind':
            d = req['data']; s = json.dumps(d, sort_keys=True)
            same = not ('required' in s and 'voluntary' in s)
            value = {'verdict': 'supported' if same else 'unsupported', 'reason': 'Synthetic only.'}
        elif stage == 'core-kind': value = {'kind': 'value'}
        elif stage == 'argument-selection': value = {'status': 'selected', 'node_ids': [], 'essential_node_ids': []}
        elif stage == 'argument-audit':
            value = {'core_fidelity': 'distorted' if self.audit_fails else 'faithful', 'core_kind_matches': True,
                     'grounds': [], 'major_premises': 'preserved'}
        else: raise AssertionError(stage)
        return {'output': value, 'raw': json.dumps(value), 'errors': []}


class CandidateCompletionPipelineTests(unittest.TestCase):
    def run_synthetic(self, directory, fail):
        f = fixture(); d = {'models': {'baseline': {'path': 'synthetic', 'sha256': 'fixture'}},
                            'server': {'path': 'synthetic', 'sha256': 'fixture'}, 'runtime': {}}
        measurement = {'development_gate_passed': False, 'all_relations_complete': False, 'observed_evaluation': 14, 'planned_evaluation': 100}
        plan = {'artifact_kind': p.VERSION, 'snapshot': str(directory/'snapshot.json'), 'expires_at': f['expires_at'],
                'inputs': {}, 'code_sha256': {}, 'model_files': {}, 'limits': deepcopy(p.LIMITS),
                'retrieval_limits': deepcopy(p.support_retrieval.LIMITS), 'candidate_contract': p.completion.VERSION,
                'profile_extra_tokens': 768, 'evaluation': p.product_evaluation.execution_state(measurement, 'product_diagnostic'),
                'membership_policy': fresh_tests.FreshGroundedPipelineTests().policy(),
                'deployments': {k: deepcopy(d) for k in ('extraction', 'membership', 'profile')},
                'budget': {'ledger': str(directory/'unused.sqlite'), 'cycle_id': 'synthetic'},
                'classifier': f['model'], 'documents': [], 'selections': []}
        write(directory/'plan.json', plan); write(directory/'snapshot.json', {'synthetic': True})
        budget = Mock(); budget.summary.return_value = {'calls': [], 'charged_seconds': 0, 'remaining_seconds': 9000}
        with patch.object(p, 'CompletionRunner', SyntheticRunner), patch.object(p, 'file_hash', return_value='fixture'), \
             patch.object(p, 'InferenceBudget', return_value=budget), patch.object(p, 'owned_server'), \
             patch.object(p, 'load_snapshot', return_value=SimpleNamespace(snapshot=None, sha256=p.sha(plan['snapshot']))), \
             patch.object(p, 'normalize_snapshot', return_value=NORMALIZED), patch.object(SyntheticRunner, 'audit_fails', fail):
            p.execute(directory)
        return p.read_json(directory/'completed.json')

    def test_full_fresh_path_finishes_each_candidate_before_next_and_does_not_approve(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); report = self.run_synthetic(directory, False)
            self.assertEqual(report['screened_inputs'], 2); self.assertEqual(report['qualified_agents'], 0)
            self.assertFalse(report['quality_gate_passed']); self.assertTrue(report['fresh_analysis'])
            self.assertEqual(len(report['attempts']), 2)
            self.assertLessEqual(report['attempts'][0]['ended_elapsed'], report['attempts'][1]['started_elapsed'])
            self.assertTrue(all(r['state'] == 'screened_input' for r in report['outcomes']))

    def test_failed_argument_audit_defers_whole_candidates_without_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); report = self.run_synthetic(directory, True)
            self.assertEqual(report['screened_inputs'], 0)
            self.assertTrue(all(r['state'] == 'argument_audit_failed' for r in report['outcomes']))
            self.assertEqual(len(list((directory/'candidates').glob('*/typed.json'))), 2)
            self.assertEqual(p.read_json(directory/'bundle.json')['claims'], [])


if __name__ == '__main__': unittest.main()
