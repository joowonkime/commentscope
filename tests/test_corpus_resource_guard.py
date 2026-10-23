from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import corpus_resource_guard as guard


class ResourceGuardTests(unittest.TestCase):
    def safe(self):
        return {'available_mb': 2048, 'commit_percent': 80, 'disk_free_bytes': 8*1024**3}

    def test_thresholds_and_invalid_observations(self):
        self.assertEqual(guard.unsafe_reasons(self.safe()), [])
        for change, reason in [({'available_mb': 1023}, 'low_host_available_memory'),
                               ({'commit_percent': 92}, 'high_host_commit'),
                               ({'disk_free_bytes': 4*1024**3-1}, 'low_host_disk')]:
            self.assertEqual(guard.unsafe_reasons({**self.safe(), **change}), [reason])
        for bad in (float('nan'), -1, True, None):
            with self.assertRaises(ValueError):
                guard.unsafe_reasons({**self.safe(), 'available_mb': bad})

    def run_guard(self, *, observe, readiness):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name)/'run'; directory.mkdir()
        write(directory/'plan.json', {})
        write(directory/'attempts/0001.started.json', {'pid': 123, 'plan_sha256': sha(directory/'plan.json')})
        real_resolve = Path.resolve
        def resolve(path, *args, **kwargs):
            return Path.cwd() if str(path) == '/proc/123/cwd' else real_resolve(path, *args, **kwargs)
        with patch.object(guard, 'PRIVATE_ROOT', Path(tmp.name)), \
             patch.object(guard.os, 'pidfd_open', return_value=987), \
             patch.object(guard.os, 'close'), \
             patch.object(Path, 'read_bytes', return_value=('python\0-m\0experiments.framed_corpus_pipeline\0run\0'+str(directory)+'\0').encode()), \
             patch.object(Path, 'resolve', resolve), \
             patch.object(guard.select, 'select', side_effect=readiness), \
             patch.object(guard, 'host_observation', side_effect=observe), \
             patch.object(guard.time, 'sleep'), \
             patch.object(guard.signal, 'pidfd_send_signal') as send:
            guard.guard(directory, 1)
            return directory/'resource-guard/0001', send

    def test_only_pinned_executor_signaled_on_pressure(self):
        outputs, send = self.run_guard(observe=[{**self.safe(), 'commit_percent': 94}], readiness=[([], [], [])])
        send.assert_called_once_with(987, signal.SIGINT)
        self.assertEqual(read_json(outputs/'stop-requested.json')['stop_reasons'], ['high_host_commit'])

    def test_terminal_executor_never_signaled(self):
        outputs, send = self.run_guard(observe=[], readiness=[([987], [], [])])
        send.assert_not_called()
        self.assertTrue(read_json(outputs/'finished.json')['target_terminal'])

    def test_transient_observation_error_then_safe_is_not_stop(self):
        outputs, send = self.run_guard(observe=[OSError(), self.safe()],
            readiness=[([], [], []), ([], [], []), ([987], [], [])])
        send.assert_not_called()
        self.assertFalse((outputs/'stop-requested.json').exists())

    def test_repeated_missing_observation_stops_owned_executor(self):
        outputs, send = self.run_guard(observe=[OSError(), OSError()], readiness=[([], [], []), ([], [], [])])
        send.assert_called_once_with(987, signal.SIGINT)
        self.assertEqual(read_json(outputs/'stop-requested.json')['stop_reasons'], ['resource_observation_unavailable'])


if __name__ == '__main__':
    unittest.main()
