"""Resource pressure must not discard an already billed remote response."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from commentscope.providers import host_resources as resources
from experiments import openrouter_factory_pipeline as executor


class RemoteResourceStopTests(unittest.TestCase):
    def test_cli_reports_controlled_stop_without_unhandled_traceback(self):
        output = StringIO()
        with patch.object(executor, 'run', side_effect=resources.ResourceStopRequested('host pressure')), \
                redirect_stdout(output):
            self.assertEqual(executor.main(['run', 'runs/authored-stop']), 2)
        report = json.loads(output.getvalue())
        self.assertEqual(report['failure_type'], 'ResourceStopRequested')
        self.assertEqual(report['reason'], 'host_resources')
        self.assertFalse(report['automatic_retry'])

    def test_stop_outside_remote_work_still_interrupts_owned_executor(self):
        interrupt = Mock()
        guard = resources.RemoteCallGuard(interrupt=interrupt)
        guard.request_stop()
        interrupt.assert_called_once_with()
        with self.assertRaises(resources.ResourceStopRequested):
            with guard.remote_call(): self.fail('No new dispatch after stop')

    def test_remote_response_can_be_settled_and_checkpointed_before_stop(self):
        interrupt = Mock(); guard = resources.RemoteCallGuard(interrupt=interrupt)
        durable = []
        with self.assertRaises(resources.ResourceStopRequested):
            with guard.remote_call():
                guard.request_stop()
                interrupt.assert_not_called()
                durable.extend(['provider_response', 'settled_charge', 'checkpoint'])
        self.assertEqual(durable, ['provider_response', 'settled_charge', 'checkpoint'])
        with self.assertRaises(resources.ResourceStopRequested): guard.check()
        with self.assertRaises(resources.ResourceStopRequested):
            with guard.remote_call(): self.fail('No second paid request')

    def test_original_provider_failure_is_not_hidden_by_resource_stop(self):
        guard = resources.RemoteCallGuard(interrupt=Mock())
        with self.assertRaisesRegex(OSError, 'original failure'):
            with guard.remote_call():
                guard.request_stop()
                raise OSError('original failure')
        with self.assertRaises(resources.ResourceStopRequested): guard.check()

    def test_local_work_after_remote_call_is_interrupted_immediately(self):
        interrupt = Mock(); guard = resources.RemoteCallGuard(interrupt=interrupt)
        with guard.remote_call(): pass
        guard.request_stop()
        interrupt.assert_called_once_with()

    def test_remote_region_cannot_cover_overlapping_calls(self):
        guard = resources.RemoteCallGuard(interrupt=Mock())
        with guard.remote_call():
            with self.assertRaises(ValueError):
                with guard.remote_call(): self.fail('Overlapping remote work')
        guard.check()

    def test_observer_storage_failure_latches_stop_without_killing_remote_call(self):
        policy = {**resources.POLICY, 'poll_seconds': .01}
        observation = {'available_mb': 4096, 'committed_bytes': 0,
                       'commit_limit': 8*1024**3, 'disk_free_bytes': 10*1024**3}
        stopped = threading.Event(); interrupt = Mock()
        guard = resources.RemoteCallGuard(interrupt=interrupt)
        actual_write = resources.write
        def disk_failure(path, value):
            if str(path).endswith('000002.json'): raise OSError('disk full')
            actual_write(path, value)
        def request_stop():
            guard.request_stop(); stopped.set()
        with tempfile.TemporaryDirectory() as tmp, patch.object(resources, 'POLICY', policy), \
                patch.object(resources, 'write', disk_failure):
            with self.assertRaises(resources.ResourceStopRequested):
                with resources.watch(tmp, policy, lambda: observation, interrupt=request_stop):
                    with guard.remote_call():
                        self.assertTrue(stopped.wait(1))
                        interrupt.assert_not_called()
            self.assertTrue((Path(tmp)/'finished.json').exists())


if __name__ == '__main__': unittest.main()
