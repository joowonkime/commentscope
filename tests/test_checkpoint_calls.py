from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from commentscope.providers.checkpoint_calls import CheckpointRunner, PendingCallError, run_origin
from commentscope.storage import write_json_exclusive as write


class CheckpointCallTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.base = Mock(directory=Path(tmp.name), plan_sha='a'*64, seq=0)
        self.runtime = {'reasoning': 'on', 'reasoning_budget': 1024, 'context': 8192}
        self.req = {'system': 'test', 'data': {'source': 'original'}, 'schema': {}, 'max_tokens': 512}
        self.base.call.return_value = {'output': {'kind': 'value'}, 'errors': []}

    def test_same_plan_reuses_bound_result_without_model_call(self):
        runner = CheckpointRunner(self.base, self.runtime)
        first = runner.call('source-a', self.req)
        resumed = CheckpointRunner(self.base, self.runtime)
        second = resumed.call('source-a', self.req)
        self.assertEqual(first, second); self.assertEqual(self.base.call.call_count, 1)
        self.assertEqual(resumed.reused, 1)
        self.assertEqual(self.base.call.call_args.args[1]['max_tokens'], 1536)

    def test_recorded_failure_is_reused_not_retried_or_promoted(self):
        self.base.call.return_value = {'output': None, 'errors': ['transport_error']}
        runner = CheckpointRunner(self.base, self.runtime)
        runner.call('source-a', self.req)
        self.assertEqual(runner.call('source-a', self.req)['errors'], ['transport_error'])
        self.assertEqual(self.base.call.call_count, 1)

    def test_pending_call_is_not_assumed_dead_and_restarted(self):
        self.base.call.side_effect = RuntimeError('interrupted')
        runner = CheckpointRunner(self.base, self.runtime)
        with self.assertRaises(RuntimeError): runner.call('source-a', self.req)
        self.base.call.side_effect = None
        with self.assertRaises(PendingCallError): CheckpointRunner(self.base, self.runtime).call('source-a', self.req)
        self.assertEqual(self.base.call.call_count, 1)

    def test_different_plan_or_request_cannot_reuse_response(self):
        runner = CheckpointRunner(self.base, self.runtime)
        runner.call('source-a', self.req)
        runner.call('source-a', {**self.req, 'data': {'source': 'changed'}})
        self.base.plan_sha = 'b'*64
        CheckpointRunner(self.base, self.runtime).call('source-a', self.req)
        self.assertEqual(self.base.call.call_count, 3)

    def test_non_llm_provider_keeps_its_declared_token_contract(self):
        def cpu(system, data, schema, max_tokens): return {}
        runner = CheckpointRunner(self.base, self.runtime)
        runner.call('embedding', {**self.req, 'max_tokens': 1}, provider=cpu, maximum=900)
        self.assertEqual(self.base.call.call_args.args[1]['max_tokens'], 1)
        self.assertEqual(self.base.call.call_args.kwargs['maximum'], 900)

    def test_call_sequence_continues_after_prior_logs(self):
        write(self.base.directory/'calls/0007-frame.request.json', {})
        CheckpointRunner(self.base, self.runtime)
        self.assertEqual(self.base.seq, 7)

    def test_cached_return_is_not_mutable_shared_state(self):
        runner = CheckpointRunner(self.base, self.runtime); runner.call('source-a', self.req)
        second = runner.call('source-a', self.req); second['output']['kind'] = 'fact'
        self.assertEqual(runner.call('source-a', self.req)['output']['kind'], 'value')

    def test_interrupted_fresh_run_resumes_without_becoming_cross_run_reuse(self):
        plan = {'run_directory': str(self.base.directory), 'cross_run_response_reuse': False}
        self.assertEqual(run_origin(plan, self.base.directory, attempt=1),
                         {'fresh_run': True, 'same_plan_resume': False})
        runner = CheckpointRunner(self.base, self.runtime)
        first = runner.call('source-a', self.req)
        resumed = CheckpointRunner(self.base, self.runtime)
        self.assertEqual(resumed.call('source-a', self.req), first)
        self.assertEqual(self.base.call.call_count, 1)
        self.assertEqual(run_origin(plan, self.base.directory.resolve(), attempt=2),
                         {'fresh_run': True, 'same_plan_resume': True})

    def test_copied_plan_or_authorized_cross_run_reuse_cannot_claim_fresh_origin(self):
        plan = {'run_directory': str(self.base.directory), 'cross_run_response_reuse': False}
        with self.assertRaises(ValueError):
            run_origin(plan, self.base.directory/'copied-run', attempt=1)
        with self.assertRaises(ValueError):
            run_origin({**plan, 'cross_run_response_reuse': True}, self.base.directory, attempt=1)
        with self.assertRaises(ValueError):
            run_origin({'cross_run_response_reuse': False}, self.base.directory, attempt=1)

    def test_invalid_attempt_cannot_produce_fresh_execution_metadata(self):
        plan = {'run_directory': str(self.base.directory), 'cross_run_response_reuse': False}
        for attempt in (0, -1, True, 1.0):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                run_origin(plan, self.base.directory, attempt=attempt)


if __name__ == '__main__': unittest.main()
