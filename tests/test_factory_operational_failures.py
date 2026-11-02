"""Fault injection: failed calls remain failed, completed work is not charged twice."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory import pipeline_work
from commentscope.factory.automatic_contract import digest
from commentscope.providers.checkpoint_calls import CheckpointRunner, PendingCallError
from commentscope.providers.budget import BudgetExhausted
from experiments import openrouter_factory_pipeline as executor


class OperationalFailureTests(unittest.TestCase):
    def work(self, runner):
        self.saved = {}
        return pipeline_work.PipelineWork(runner, lambda req: {'fits': True, 'request_sha256': digest(req)},
            lambda name, value: self.saved.__setitem__(name, value), registry={},
            membership_mode='raw', verification_contract='test', schedule={})

    def request(self, group):
        return {'system': 'Authored fault test', 'data': {'id': group[0]}, 'schema': {}, 'max_tokens': 32}

    def bind(self, group, result):
        if result.get('errors') or not isinstance(result.get('output'), dict): raise ValueError('invalid response')
        return result['output']

    def test_timeout_resume_preserves_prior_result_and_never_reissues_the_failed_call(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Mock(directory=Path(directory), plan_sha='a'*64, seq=0)
            base.call.side_effect = [{'output': {'id': 'first'}, 'raw': '{}', 'errors': []},
                                     {'output': None, 'raw': None, 'errors': ['bounded_call_failed']}]
            runtime = {'reasoning': 'off', 'reasoning_budget': 0, 'context': 8192}
            for attempt in range(2):
                work = self.work(CheckpointRunner(base, runtime))
                with self.assertRaises(pipeline_work.ModelResponseUnavailable) as caught:
                    work.work('extract', ['first', 'timeout', 'never-sent'], self.request, self.bind, 1)
                self.assertEqual(caught.exception.diagnostic['stage'], 'extract')
                self.assertEqual(caught.exception.diagnostic['request_sha256'], digest(self.request(['timeout'])))
                self.assertEqual(len(work.errors), 1)
                self.assertEqual(sum(n.startswith('bound/') for n in self.saved), 1)
            self.assertEqual(base.call.call_count, 2)

    def test_completed_malformed_response_is_isolated_and_never_promoted(self):
        runner = Mock(); runner.call.side_effect = [
            {'output': None, 'raw': 'invalid JSON', 'errors': ['invalid_json']},
            {'output': {'id': 'good'}, 'raw': '{}', 'errors': []}]
        work = self.work(runner)
        self.assertEqual(work.work('extract', ['bad', 'good'], self.request, self.bind, 1), [{'id': 'good'}])
        self.assertEqual(len(work.errors), 1); self.assertEqual(runner.call.call_count, 2)

    def test_invalid_response_envelope_is_saved_and_stops_dispatch(self):
        runner = Mock(); runner.call.return_value = None
        work = self.work(runner)
        with self.assertRaises(pipeline_work.ModelResponseUnavailable):
            work.work('extract', ['bad', 'never-sent'], self.request, self.bind, 1)
        self.assertEqual(work.errors[0]['exception'], 'InvalidResponseEnvelope')
        self.assertEqual(runner.call.call_count, 1)

    def test_cli_reports_known_failure_with_nonzero_status_without_a_new_model_call(self):
        failure = pipeline_work.ModelResponseUnavailable('extract', 'a'*64, 'b'*64)
        for error, reason in ((failure, 'model_response_unavailable'),
                              (PendingCallError('pending'), 'pending_call'),
                              (BudgetExhausted('budget'), 'budget_blocked')):
            with self.subTest(reason=reason), patch.object(executor, 'run', side_effect=error) as run:
                output = io.StringIO()
                with redirect_stdout(output): code = executor.main(['run', 'runs/authored-fault-test'])
                report = json.loads(output.getvalue())
                self.assertNotEqual(code, 0); self.assertEqual(report['reason'], reason)
                self.assertFalse(report['automatic_retry']); self.assertFalse(report['quality_gate_passed'])
                self.assertFalse(report['execution_complete'])
                run.assert_called_once()


if __name__ == '__main__': unittest.main()
