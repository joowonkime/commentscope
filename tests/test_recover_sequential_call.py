"""Synthetic terminal proof and no-retry behavior; no model is loaded."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner, VERSION
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from experiments import recover_sequential_call as recovery


class SequentialRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.directory = self.root/'run'; self.ledger = self.root/'ledger.sqlite'
        self.runtime = {'reasoning': 'on', 'reasoning_budget': 1024, 'context': 8192}
        self.request = {'system': 'test', 'data': {'source': 'unchanged'}, 'schema': {}, 'max_tokens': 512}
        actual = allocate(self.request, self.runtime)
        write(self.directory/'plan.json', {'deployment': {}, 'limits': {'call_seconds': 1800},
              'budget': {'ledger': str(self.ledger), 'cycle_id': 'test'}})
        self.plan_hash = sha(self.directory/'plan.json')
        self.budget = InferenceBudget(self.ledger, 'test', limit_seconds=None)
        self.call_id = self.budget.reserve(actual, self.plan_hash, 1800)
        self.budget.finish(self.call_id, 22, 'interrupted', error='KeyboardInterrupt')
        write(self.directory/'started.json', {'plan_sha256': self.plan_hash})
        write(self.directory/'attempts/0001.started.json', {'pid': 123, 'plan_sha256': self.plan_hash,
                                                        'started_at': '2026-01-01T00:00:00+00:00'})
        write(self.directory/'attempts/0001.failed.json', {'exception_type': 'KeyboardInterrupt',
                                                        'budget_after': self.budget.summary()})
        self.server = self.directory/'models/0001/llm-0001'
        write(self.server/'runtime.json', {'pid': 456, 'command': ['test']})
        write(self.server/'stopped.json', {'pid': 456, 'returncode': 0})
        write(self.server/'resources/finished.json', {'observer_stopped': True})
        self.identity = {'artifact_kind': VERSION, 'plan_sha256': self.plan_hash, 'stage': 'frame-test',
                         'request_sha256': digest(actual), 'provider': 'local_llama'}
        self.key = digest(self.identity)
        write(self.directory/'checkpoints'/(self.key+'.intent.json'), self.identity)
        self.request_path = self.directory/'calls/0001-frame-test.request.json'
        write(self.request_path, {'plan_sha256': self.plan_hash, 'request': actual,
                                 'request_sha256': digest(actual), 'timeout_seconds': 1800})
        self.transition = self.directory/'transitions/0001/00001.started.json'
        write(self.transition, {'kind': 'llm', 'stage': 'frame-test', 'plan_sha256': self.plan_hash,
                               'request_sha256': digest(actual), 'at': '2026-01-01T00:00:01+00:00'})
        write(self.directory/'transitions/0001/00001.failed.json', {'exception_type': 'KeyboardInterrupt', 'stage': 'frame-test'})
        for item in [patch.object(recovery.pipeline, 'PRIVATE_ROOT', self.root),
                     patch.object(recovery.pipeline, 'validate'), patch.object(recovery, 'require_dead'),
                     patch.object(recovery.pipeline, 'command', return_value=['test'])]:
            item.start(); self.addCleanup(item.stop)

    def reconcile(self, apply=True):
        return recovery.reconcile(self.directory, self.key, apply=apply)

    def test_inspection_and_publication_preserve_ledger_and_never_infer_on_resume(self):
        before = sha(self.ledger)
        inventory = {str(p): sha(p) for p in self.directory.rglob('*.json')}
        inspected = self.reconcile(False)
        self.assertFalse(inspected['checkpoint_published'])
        self.assertEqual(inventory, {str(p): sha(p) for p in self.directory.rglob('*.json')})
        published = self.reconcile(); self.assertTrue(published['checkpoint_published'])
        self.assertEqual(sha(self.ledger), before)
        base = Mock(directory=self.directory, plan_sha=self.plan_hash, seq=0)
        result = CheckpointRunner(base, self.runtime).call('frame-test', self.request)
        self.assertEqual(result['errors'], ['bounded_call_interrupted']); self.assertIsNone(result['output'])
        base.call.assert_not_called()
        self.assertEqual(self.budget.summary()['calls'][0]['charged_seconds'], 1803)
        self.assertEqual(self.reconcile(), published)

    def test_live_process_missing_observer_or_bad_server_shutdown_rejected(self):
        with patch.object(recovery, 'require_dead', side_effect=ValueError('live')):
            with self.assertRaisesRegex(ValueError, 'live'): self.reconcile()
        path = self.server/'resources/finished.json'; path.write_text(json.dumps({'observer_stopped': False}))
        with self.assertRaisesRegex(ValueError, 'shutdown unproven'): self.reconcile()
        path.write_text(json.dumps({'observer_stopped': True}))
        (self.server/'stopped.json').write_text(json.dumps({'pid': 456, 'returncode': 1}))
        with self.assertRaisesRegex(ValueError, 'shutdown unproven'): self.reconcile()
        self.assertFalse((self.directory/'recoveries').exists())

    def test_every_earlier_owned_server_and_auxiliary_observer_is_checked(self):
        target = self.directory/'models/0001/llm-0002'
        for filename in ('runtime.json', 'stopped.json', 'resources/finished.json'):
            write(target/filename, read_json(self.server/filename))
        auxiliary = self.directory/'models/0001/auxiliary-0001/finished.json'
        write(auxiliary, {'observer_stopped': False})
        with self.assertRaisesRegex(ValueError, 'Auxiliary observer'): self.reconcile()
        auxiliary.write_text(json.dumps({'observer_stopped': True}))
        self.reconcile(False)
        (self.server/'stopped.json').write_text(json.dumps({'pid': 999, 'returncode': 0}))
        with self.assertRaisesRegex(ValueError, 'shutdown unproven'): self.reconcile()

    def test_final_transition_cannot_be_auxiliary_changed_or_finished(self):
        original = read_json(self.transition)
        for field, value in [('kind', 'auxiliary'), ('stage', 'other'), ('request_sha256', 'changed')]:
            changed = dict(original); changed[field] = value; self.transition.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'transition differs'): self.reconcile()
        self.transition.write_text(json.dumps(original))
        write(self.directory/'transitions/0001/00001.finished.json', {})
        with self.assertRaisesRegex(ValueError, 'transition differs'): self.reconcile()

    def test_ambiguous_or_reserved_ledger_never_published(self):
        cid = self.budget.reserve(allocate(self.request, self.runtime), self.plan_hash, 1800)
        with self.assertRaisesRegex(ValueError, 'Unfinished reservation'): self.reconcile()
        self.budget.finish(cid, 2, 'interrupted', error='KeyboardInterrupt')
        with self.assertRaisesRegex(ValueError, 'ambiguous ledger'): self.reconcile()

    def test_successful_ledger_response_and_refund_mismatch_rejected(self):
        with sqlite3.connect(self.ledger) as db:
            db.execute('UPDATE calls SET charged=1804 WHERE id=?', (self.call_id,))
        with self.assertRaisesRegex(ValueError, 'ledger disagree'): self.reconcile()
        with sqlite3.connect(self.ledger) as db:
            db.execute('UPDATE calls SET state=?,response_json=?,error=NULL WHERE id=?', ('ok', '{"value":"response"}', self.call_id))
        with self.assertRaisesRegex(ValueError, 'does not prove'): self.reconcile()

    def test_partial_publication_finishes_and_conflicts_are_never_overwritten(self):
        original = recovery.write
        def interrupted(path, value):
            if str(path).endswith('.result.json'): raise KeyboardInterrupt()
            original(path, value)
        with patch.object(recovery, 'write', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): self.reconcile()
        self.assertTrue(self.reconcile()['checkpoint_published'])
        path = self.directory/'calls/0001-frame-test.result.json'; path.write_text('{"invented":true}')
        with self.assertRaisesRegex(ValueError, 'never overwrite'): self.reconcile()

    def test_lock_changed_plan_private_path_and_completed_run_rejected(self):
        with recovery.pipeline.experiment_lock(self.directory):
            with self.assertRaises(RuntimeError): self.reconcile()
        with patch.object(recovery.pipeline, 'validate', side_effect=ValueError('frozen changed')):
            with self.assertRaisesRegex(ValueError, 'frozen changed'): self.reconcile()
        with self.assertRaisesRegex(ValueError, 'private'):
            recovery.reconcile(self.root.parent/'outside', self.key)
        write(self.directory/'completed.json', {})
        with self.assertRaisesRegex(ValueError, 'completed'): self.reconcile()

    def test_changed_request_or_timeout_cannot_preserve_a_different_failure(self):
        original = read_json(self.request_path)
        for field, value in [('request_sha256', 'changed'), ('timeout_seconds', 180)]:
            changed = dict(original); changed[field] = value; self.request_path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'identity or finite timeout'): self.reconcile()


if __name__ == '__main__': unittest.main()
