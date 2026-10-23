import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner, VERSION
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from experiments import recover_interrupted_call as recovery
from experiments.framed_corpus_pipeline import experiment_lock


class InterruptedRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)/'run'; self.directory.mkdir()
        self.ledger = Path(tmp.name)/'ledger.sqlite'
        self.runtime = {'reasoning': 'on', 'reasoning_budget': 1024, 'context': 8192}
        self.req = {'system': 'test', 'data': {'source': 'unchanged'}, 'schema': {}, 'max_tokens': 512}
        self.actual = allocate(self.req, self.runtime)
        plan = {'deployment': {}, 'budget': {'ledger': str(self.ledger), 'cycle_id': 'test'}}
        write(self.directory/'plan.json', plan)
        self.plan_hash = sha(self.directory/'plan.json')
        self.budget = InferenceBudget(self.ledger, 'test', limit_seconds=None)
        self.call_id = self.budget.reserve(self.actual, self.plan_hash, 180)
        self.budget.finish(self.call_id, 22, 'interrupted', error='KeyboardInterrupt')
        write(self.directory/'started.json', {'plan_sha256': self.plan_hash})
        write(self.directory/'attempts/0001.started.json', {
            'pid': 123, 'plan_sha256': self.plan_hash, 'started_at': '2026-01-01T00:00:00+00:00'})
        write(self.directory/'attempts/0001.failed.json', {
            'exception_type': 'KeyboardInterrupt', 'budget_after': self.budget.summary()})
        write(self.directory/'servers/0001/runtime.json', {'pid': 456, 'command': ['test']})
        write(self.directory/'servers/0001/stopped.json', {'pid': 456, 'returncode': 0})
        self.identity = {'artifact_kind': VERSION, 'plan_sha256': self.plan_hash, 'stage': 'frame-test',
                         'request_sha256': digest(self.actual), 'provider': 'local_llama'}
        self.key = digest(self.identity)
        write(self.directory/'checkpoints'/(self.key+'.intent.json'), self.identity)
        self.request_path = self.directory/'calls/0001-frame-test.request.json'
        write(self.request_path, {'plan_sha256': self.plan_hash, 'request': self.actual,
                                 'request_sha256': digest(self.actual), 'timeout_seconds': 180})
        self.patches = [patch.object(recovery, 'PRIVATE_ROOT', Path(tmp.name)),
                        patch.object(recovery, 'validate'), patch.object(recovery, 'require_dead'),
                        patch.object(recovery, 'command', return_value=['test'])]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def reconcile(self, apply=True):
        return recovery.reconcile(self.directory, self.key, apply=apply)

    def test_inspect_makes_no_artifacts_or_ledger_changes(self):
        before = sha(self.ledger)
        report = self.reconcile(apply=False)
        self.assertFalse(report['checkpoint_published'])
        self.assertFalse((self.directory/'recoveries').exists())
        self.assertEqual(sha(self.ledger), before)
        recovery.validate.assert_called_once()
        self.assertEqual(recovery.require_dead.call_count, 2)

    def test_recovery_is_error_and_resume_never_retries_it(self):
        before = sha(self.ledger)
        report = self.reconcile()
        self.assertTrue(report['checkpoint_published'])
        base = Mock(directory=self.directory, plan_sha=self.plan_hash, seq=0)
        runner = CheckpointRunner(base, self.runtime)
        result = runner.call('frame-test', self.req)
        self.assertIsNone(result['output'])
        self.assertEqual(result['errors'], ['bounded_call_interrupted'])
        base.call.assert_not_called()
        self.assertEqual(sha(self.ledger), before)
        self.assertEqual(self.budget.summary()['calls'][0]['charged_seconds'], 183)

    def test_repeat_is_idempotent(self):
        self.assertEqual(self.reconcile(), self.reconcile())

    def test_partial_publication_can_finish_without_overwrite(self):
        original = recovery.write
        def interrupted(path, value):
            if str(path).endswith('.result.json'):
                raise KeyboardInterrupt
            original(path, value)
        with patch.object(recovery, 'write', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): self.reconcile()
        self.assertTrue((self.directory/'recoveries'/(self.key+'.json')).exists())
        self.assertTrue(self.reconcile()['checkpoint_published'])

    def test_existing_conflicting_result_rejected_before_other_writes(self):
        write(self.directory/'calls/0001-frame-test.result.json', {'output': {'invented': True}})
        with self.assertRaises(ValueError): self.reconcile()
        self.assertFalse((self.directory/'recoveries').exists())

    def test_changed_request_rejected(self):
        value = read_json(self.request_path); value['request']['data']['source'] = 'changed'
        with patch.object(recovery, 'read_json', side_effect=lambda p: value if p == self.request_path else read_json(p)):
            with self.assertRaises(ValueError): self.reconcile()

    def test_ambiguous_ledger_request_rejected(self):
        cid = self.budget.reserve(self.actual, self.plan_hash, 180)
        self.budget.finish(cid, 2, 'interrupted', error='KeyboardInterrupt')
        with self.assertRaises(ValueError): self.reconcile()

    def test_live_or_reserved_calls_rejected(self):
        with patch.object(recovery, 'require_dead', side_effect=ValueError('live')):
            with self.assertRaises(ValueError): self.reconcile()
        self.budget.reserve({**self.actual, 'data': {'source': 'other'}}, self.plan_hash, 180)
        with self.assertRaises(ValueError): self.reconcile()

    def test_live_experiment_lock_rejected(self):
        with experiment_lock(self.directory):
            with self.assertRaises(RuntimeError): self.reconcile()

    def test_changed_frozen_inputs_rejected(self):
        with patch.object(recovery, 'validate', side_effect=ValueError('changed')):
            with self.assertRaises(ValueError): self.reconcile()

    def test_failure_ledger_disagreement_rejected(self):
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute('UPDATE calls SET charged=184 WHERE id=?', (self.call_id,))
        with self.assertRaises(ValueError): self.reconcile()

    def test_successful_ledger_response_never_converted_to_failure(self):
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute('UPDATE calls SET state=?,response_json=?,error=NULL WHERE id=?',
                       ('ok', json.dumps({'output': 'value'}), self.call_id))
        with self.assertRaises(ValueError): self.reconcile()


class ProcessLivenessTests(unittest.TestCase):
    def test_only_missing_pid_is_terminal(self):
        with patch.object(recovery.os, 'kill', side_effect=ProcessLookupError):
            recovery.require_dead(123)
        with patch.object(recovery.os, 'kill'):
            with self.assertRaises(ValueError): recovery.require_dead(123)
        with patch.object(recovery.os, 'kill', side_effect=PermissionError):
            with self.assertRaises(PermissionError): recovery.require_dead(123)
        for pid in (0, -1, True, '123'):
            with self.assertRaises(ValueError): recovery.require_dead(pid)


if __name__ == '__main__':
    unittest.main()
