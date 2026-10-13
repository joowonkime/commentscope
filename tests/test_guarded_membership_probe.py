from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory import condition_guard as guard, membership_policy
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import guarded_membership_probe as probe
from experiments.directed_off_deployment import control_rows
from experiments.reasoning_membership_probe import execute
import test_directed_off_deployment


class GuardedMembershipProbeTests(unittest.TestCase):
    def parent(self):
        parent = test_directed_off_deployment.DirectedOffDeploymentTests().parent()
        parent.update(models={'baseline': {'name': 'Qwen3-8B-Q4_K_M'}}, server={},
                      proposals=[], reference_source='unchanged-reference-source')
        return parent

    def controls(self, root):
        plan = self.parent()
        policy = membership_policy.from_rows(plan['rows']); policy['max_tokens'] = 180
        plan.update(rows=control_rows(policy), plumbing_only=True, evaluation_ids=[f'T{i}' for i in range(1, 9)])
        plan['runtime'].update(reasoning='off', reasoning_budget=0, max_tokens=180)
        write(root/'plan.json', plan)
        for row in plan['rows']:
            raw = 'supported' if row['id'] == 'T4' else row['expected']
            output = {'verdict': raw, 'reason': 'synthetic raw model decision'}
            write(root/(row['id']+'.json'), {'request_sha256': row['request_sha256'],
                  'result': {'raw': json.dumps(output), 'output': output, 'errors': []}})
        write(root/'report.json', {'precision': .8, 'original_failure': 'T4'})
        write(root/'completed.json', {'plan_sha256': sha(root/'plan.json'), 'report_sha256': sha(root/'report.json'),
              'records': {r['id']: sha(root/(r['id']+'.json')) for r in plan['rows']}})
        return plan

    def replay(self, root):
        self.controls(root/'old')
        with patch.object(probe, 'validate'), patch.object(probe, 'code_hashes', return_value={}):
            probe.prepare_controls(root/'replay', root/'old')
        budget = Mock(); budget.summary.return_value = {'calls': []}
        with patch('experiments.reasoning_membership_probe.validate'), \
             patch('experiments.reasoning_membership_probe.InferenceBudget', return_value=budget), \
             patch('experiments.reasoning_membership_probe.owned_server') as server:
            execute(root/'replay')
        server.assert_not_called(); budget.call.assert_not_called()

    def test_replay_preserves_failure_without_server_or_new_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.replay(root)
            report = read_json(root/'replay'/'report.json')
            self.assertEqual(report['precision'], 1)
            self.assertEqual(report['positive_retention'], 1)
            self.assertEqual(report['actual']['T4'], 'unclear')
            self.assertFalse(report['development_gate_passed'])
            self.assertEqual(read_json(root/'old'/'report.json')['precision'], .8)
            self.assertEqual(read_json(root/'replay'/'T4.json')['result']['output']['verdict'], 'supported')

    def test_full_trial_preserves_fixed_sources_targets_and_reference_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.replay(root)
            parent = self.parent(); write(root/'parent'/'plan.json', parent)
            with patch.object(probe, 'validate'), patch.object(probe, 'code_hashes', return_value={}), \
                 patch.object(probe, 'ceiling', return_value={'cannot_pass': False}):
                probe.prepare_trial(root/'trial', root/'parent', root/'replay')
            trial = read_json(root/'trial'/'plan.json')
            self.assertEqual(trial['evaluation_ids'], parent['evaluation_ids'])
            self.assertEqual(trial['reference_source'], parent['reference_source'])
            for old, new in zip(parent['rows'], trial['rows']):
                self.assertEqual(old['text'], new['text']); self.assertEqual(old['claim'], new['claim'])
                for key in ('system', 'data', 'schema'):
                    self.assertEqual(old['request'][key], new['request'][key])
            self.assertEqual(trial['membership_guard'], guard.VERSION)
            self.assertNotIn('reused_records', trial)

    def test_impossible_host_policy_blocks_before_model_validation_or_new_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.replay(root)
            write(root/'parent'/'plan.json', self.parent())
            with patch.object(probe, 'ceiling', return_value={'cannot_pass': True}), \
                 patch.object(probe, 'verify_controls') as verify, patch.object(probe, 'validate') as validate:
                with self.assertRaisesRegex(ValueError, 'perfect model'):
                    probe.prepare_trial(root/'trial', root/'parent', root/'replay')
            verify.assert_not_called(); validate.assert_not_called()
            self.assertFalse((root/'trial').exists())

    def test_tampered_raw_record_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan = self.controls(root)
            with patch.object(probe, 'sha', wraps=sha) as hashes:
                hashes.side_effect = lambda p: 'changed' if Path(p).name == 'T4.json' else sha(p)
                with self.assertRaisesRegex(ValueError, 'record changed'):
                    probe.completed_records(root, plan)

    def test_guarded_source_cannot_silently_qualify_unguarded_runtimes(self):
        from experiments import fresh_grounded_pipeline as fresh, grounded_integration as staged
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.replay(root)
            gate = {'development_gate_passed': True, 'all_relations_complete': True}
            with patch.object(fresh, 'checkpoint', return_value=gate):
                with self.assertRaisesRegex(ValueError, 'not bound'):
                    fresh.prepare(root/'fresh', None, root/'replay', root/'old'/'plan.json', None, None)
            with patch.object(staged, 'checkpoint', return_value=gate):
                with self.assertRaisesRegex(ValueError, 'not bound'):
                    staged.prepare(root/'replay', root/'staged')
            self.assertFalse((root/'fresh').exists()); self.assertFalse((root/'staged').exists())
