from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.claim_clusters import read_json
from commentscope.providers import host_resources as h
from experiments import audit_model_compare as server


class HostResourceTests(unittest.TestCase):
    def observation(self, **changes):
        return dict(available_mb=8000, committed_bytes=36*1024**3, commit_limit=38*1024**3,
                    disk_free_bytes=18*1024**3, commit_percent=95, **changes)

    def test_percentage_alone_is_not_a_resource_failure(self):
        self.assertEqual(h.reasons(self.observation(), h.POLICY), [])

    def test_each_actual_resource_boundary_is_preserved(self):
        for field, value, expected in [
            ('available_mb', 1535, 'low_host_available_memory'),
            ('commit_limit', 37*1024**3-1, 'low_host_commit_headroom'),
            ('disk_free_bytes', 6*1024**3-1, 'low_host_disk')]:
            observation = self.observation(); observation[field] = value
            self.assertEqual(h.reasons(observation, h.POLICY), [expected])

    def test_invalid_observations_fail_closed(self):
        for value in (None, True, float('inf'), float('nan'), -1):
            row = self.observation(); row['commit_limit'] = value
            with self.assertRaises(ValueError): h.reasons(row, h.POLICY)

    def test_policy_cannot_be_silently_weakened(self):
        with self.assertRaises(ValueError): h.reasons(self.observation(), {**h.POLICY, 'minimum_available_mb': 1})

    def test_missing_observations_are_recorded_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            observer = h.Observer(tmp, h.POLICY, Mock(side_effect=[OSError(), OSError(), self.observation()]))
            self.assertEqual(observer.sample()['stop_reasons'], [])
            self.assertEqual(observer.sample()['stop_reasons'], ['resource_observation_unavailable'])
            self.assertEqual(observer.sample()['stop_reasons'], [])
            self.assertEqual(observer.failures, 0)

    def test_unsafe_start_does_not_yield_or_signal_other_processes(self):
        row = self.observation(); row['available_mb'] = 0
        with tempfile.TemporaryDirectory() as tmp:
            interrupt = Mock()
            with self.assertRaises(RuntimeError):
                with h.watch(tmp, h.POLICY, lambda: row, interrupt=interrupt):
                    self.fail('Unsafe startup yielded')
            interrupt.assert_not_called()
            self.assertTrue((Path(tmp)/'stop-requested.json').exists())

    def test_safe_context_stops_observer(self):
        with tempfile.TemporaryDirectory() as tmp:
            interrupt = Mock()
            with h.watch(tmp, h.POLICY, self.observation, interrupt=interrupt): pass
            interrupt.assert_not_called()
            self.assertTrue(read_json(Path(tmp)/'finished.json')['observer_stopped'])

    def test_pressure_during_work_interrupts_only_injected_executor(self):
        policy = {**h.POLICY, 'poll_seconds': .01}
        row = self.observation(); row['available_mb'] = 0
        notified = threading.Event()
        with tempfile.TemporaryDirectory() as tmp, patch.object(h, 'POLICY', policy):
            with h.watch(tmp, policy, Mock(side_effect=[self.observation(), row]), interrupt=notified.set):
                self.assertTrue(notified.wait(1))
            self.assertEqual(read_json(Path(tmp)/'stop-requested.json')['stop_reasons'], ['low_host_available_memory'])

    def test_monitor_storage_failure_also_interrupts_executor(self):
        policy = {**h.POLICY, 'poll_seconds': .01}
        notified = threading.Event(); actual_write = h.write
        def disk_failure(path, value):
            if str(path).endswith('000002.json'): raise OSError('disk')
            actual_write(path, value)
        with tempfile.TemporaryDirectory() as tmp, patch.object(h, 'POLICY', policy), patch.object(h, 'write', disk_failure):
            with h.watch(tmp, policy, self.observation, interrupt=notified.set):
                self.assertTrue(notified.wait(1))

    def test_memory_profile_is_explicit_and_legacy_command_unchanged(self):
        plan = {'server': {'path': 'server'}, 'models': {'baseline': {'path': 'model'}}, 'runtime': deepcopy(server.RUNTIME)}
        old = server.command(plan, 'baseline')
        self.assertNotIn('--cache-ram', old)
        plan['runtime']['memory_profile'] = {'version': 'local-memory-profile-0.1', 'load_mode': 'dio',
            'cache_ram_mib': 0, 'cache_idle_slots': False, 'host_resource_policy': deepcopy(h.POLICY)}
        self.assertEqual(server.command(plan, 'baseline'), old+['--load-mode', 'dio', '--cache-ram', '0', '--no-cache-idle-slots'])
        plan['runtime']['memory_profile']['cache_ram_mib'] = 8192
        with self.assertRaises(ValueError): server.command(plan, 'baseline')

    def compact_plan(self):
        profile = {'version': 'local-memory-profile-0.2', 'load_mode': 'dio', 'cache_ram_mib': 0,
            'cache_idle_slots': False, 'host_resource_policy': deepcopy(h.POLICY),
            'kv_cache': {'k': 'q8_0', 'v': 'q8_0'}, 'flash_attention': 'on', 'batch_size': 512, 'ubatch_size': 128}
        return {'server': {'path': 'server'}, 'models': {'baseline': {'path': 'model'}},
            'runtime': {**deepcopy(server.RUNTIME), 'context': 8192, 'memory_profile': profile}}

    def test_compact_profile_is_explicit_and_preserves_context_and_guard(self):
        plan = self.compact_plan()
        argv = server.command(plan, 'baseline')
        self.assertEqual(argv[argv.index('-c')+1], '8192')
        self.assertEqual(argv[-10:], ['--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0',
            '--flash-attn', 'on', '--batch-size', '512', '--ubatch-size', '128'])
        for field, value in [('batch_size', True), ('ubatch_size', 512), ('kv_cache', {'k':'q4_0','v':'q4_0'}),
                             ('flash_attention', 'off'), ('host_resource_policy', {**h.POLICY, 'minimum_available_mb': 1})]:
            changed = deepcopy(plan); changed['runtime']['memory_profile'][field] = value
            with self.assertRaises(ValueError): server.command(changed, 'baseline')

    def test_mapped_profile_changes_only_explicit_loading_flags(self):
        plan = self.compact_plan()
        previous = server.command(plan, 'baseline')
        previous[previous.index('--load-mode')+1] = 'mmap'
        plan['runtime']['memory_profile'].update(version='local-memory-profile-0.3',
            load_mode='mmap', host_buffer=False, repack=False)
        self.assertEqual(server.command(plan, 'baseline'), previous + ['--no-host', '--no-repack'])
        self.assertEqual(plan['runtime']['memory_profile']['host_resource_policy'], h.POLICY)

    def test_mapped_profile_does_not_allow_silent_policy_or_loading_changes(self):
        plan = self.compact_plan()
        plan['runtime']['memory_profile'].update(version='local-memory-profile-0.3',
            load_mode='mmap', host_buffer=False, repack=False)
        for field, value in [('load_mode', 'dio'), ('host_buffer', True), ('repack', True),
                             ('host_buffer', 0), ('extra', 'flag'), ('ubatch_size', 64)]:
            changed = deepcopy(plan); changed['runtime']['memory_profile'][field] = value
            with self.assertRaises(ValueError): server.command(changed, 'baseline')

    def test_host_only_profile_disables_gpu_and_operation_offloading(self):
        plan = self.compact_plan()
        plan['runtime']['gpu_layers'] = 0
        plan['runtime']['memory_profile'].update(version='local-memory-profile-0.4',
            load_mode='mmap', host_buffer=False, repack=False, device='none', op_offload=False)
        argv = server.command(plan, 'baseline')
        self.assertEqual(argv[-3:], ['--device', 'none', '--no-op-offload'])
        for value in ('all', 1, False):
            changed = deepcopy(plan); changed['runtime']['gpu_layers'] = value
            with self.assertRaises(ValueError): server.command(changed, 'baseline')
        for field, value in [('device', 'CUDA0'), ('op_offload', True), ('op_offload', 0)]:
            changed = deepcopy(plan); changed['runtime']['memory_profile'][field] = value
            with self.assertRaises(ValueError): server.command(changed, 'baseline')


if __name__ == '__main__': unittest.main()
