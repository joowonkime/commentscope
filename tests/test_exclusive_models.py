"""Lifecycle/ordering contracts only, not actual RAM or model-quality evidence."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from threading import Thread
import unittest

from commentscope.providers.exclusive_models import ExclusiveModels
from commentscope.providers.checkpoint_calls import CheckpointRunner


def auxiliary(system, data, schema, max_tokens):
    return {}


class ExclusiveModelTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.live = set()

    @contextmanager
    def server(self, sequence):
        self.assertFalse(self.live)
        self.live.add('llm'); self.events.append(('server_start', sequence))
        try:
            yield
        finally:
            self.live.remove('llm'); self.events.append(('server_stop', sequence))

    @contextmanager
    def guard(self, sequence):
        self.assertFalse(self.live)
        self.live.add('auxiliary'); self.events.append(('guard_start', sequence))
        try:
            yield
        finally:
            self.live.remove('auxiliary'); self.events.append(('guard_stop', sequence))

    def models(self):
        return ExclusiveModels(self.server, self.guard)

    def operation(self, kind, result):
        def call():
            self.assertEqual(self.live, {kind})
            self.events.append(('call', kind))
            return result
        return call

    def test_consecutive_llm_calls_share_server_and_close_on_exit(self):
        with self.models() as m:
            for i in range(3):
                self.assertEqual(m.invoke('llm', self.operation('llm', i)), i)
            self.assertEqual(m.server_starts, 1); self.assertEqual(m.server_stops, 0)
        self.assertEqual(m.server_stops, 1); self.assertFalse(self.live)

    def test_auxiliary_never_overlaps_and_next_llm_reloads(self):
        with self.models() as m:
            for kind in ('llm', 'llm', 'auxiliary', 'auxiliary', 'llm', 'auxiliary', 'llm'):
                m.invoke(kind, self.operation(kind, None))
        self.assertEqual((m.server_starts, m.server_stops, m.auxiliary_calls), (3, 3, 3))
        self.assertFalse(self.live)
        self.assertLess(self.events.index(('server_stop', 1)), self.events.index(('guard_start', 1)))
        self.assertLess(self.events.index(('guard_stop', 2)), self.events.index(('server_start', 2)))

    def test_unused_scope_does_not_load_any_model(self):
        with self.models() as m:
            pass
        self.assertEqual(self.events, []); self.assertEqual(m.server_starts, 0)

    def test_interruption_closes_owned_server(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.models() as m:
                def interrupted(): raise KeyboardInterrupt()
                m.invoke('llm', interrupted)
        self.assertFalse(self.live); self.assertEqual(m.server_stops, 1)

    def test_caught_auxiliary_failure_does_not_permit_later_reload(self):
        with self.models() as m:
            m.invoke('llm', self.operation('llm', None))
            def failure(): raise RuntimeError('provider failed')
            with self.assertRaisesRegex(RuntimeError, 'provider failed'):
                m.invoke('auxiliary', failure)
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                m.invoke('llm', lambda: self.fail('must not restart'))
        self.assertFalse(self.live); self.assertEqual(m.server_starts, 1)

    def test_guard_failure_prevents_auxiliary_operation(self):
        @contextmanager
        def failed_guard(sequence):
            raise RuntimeError('resource guard refused')
            yield
        with self.assertRaisesRegex(RuntimeError, 'resource guard refused'):
            with ExclusiveModels(self.server, failed_guard) as m:
                m.invoke('llm', self.operation('llm', None))
                m.invoke('auxiliary', lambda: self.fail('guard did not admit operation'))
        self.assertFalse(self.live); self.assertEqual(m.server_stops, 1)

    def test_start_failure_is_not_retried(self):
        calls = []
        @contextmanager
        def failed_server(sequence):
            calls.append(sequence)
            raise RuntimeError('server refused')
            yield
        with ExclusiveModels(failed_server, self.guard) as m:
            with self.assertRaisesRegex(RuntimeError, 'server refused'):
                m.invoke('llm', lambda: None)
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                m.invoke('llm', lambda: None)
        self.assertEqual(calls, [1]); self.assertEqual(m.server_starts, 0)

    def test_uncertain_shutdown_blocks_auxiliary_without_repeating_exit(self):
        exits = []
        class BrokenExit:
            def __enter__(self): return self
            def __exit__(self, *args):
                exits.append('exit')
                raise RuntimeError('unconfirmed termination')
        with self.assertRaisesRegex(RuntimeError, 'shutdown remains unconfirmed'):
            with ExclusiveModels(lambda n: BrokenExit(), self.guard) as m:
                m.invoke('llm', lambda: None)
                with self.assertRaisesRegex(RuntimeError, 'unconfirmed termination'):
                    m.invoke('auxiliary', lambda: self.fail('must not overlap'))
        self.assertEqual(exits, ['exit']); self.assertEqual(m.auxiliary_calls, 0)

    def test_reentrant_call_fails_and_scope_cannot_reopen(self):
        m = self.models()
        with self.assertRaisesRegex(RuntimeError, 'already busy'):
            with m:
                m.invoke('llm', lambda: m.invoke('auxiliary', lambda: None))
        self.assertFalse(self.live)
        with self.assertRaisesRegex(RuntimeError, 'reopened'):
            with m: pass
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            m.invoke('llm', lambda: None)

    def test_different_thread_cannot_enter_close_or_switch_models(self):
        errors = []
        with self.models() as m:
            m.invoke('llm', self.operation('llm', None))
            def other_thread():
                for action in (m.__enter__, lambda: m.__exit__(None, None, None),
                               lambda: m.invoke('auxiliary', lambda: self.fail('wrong thread'))):
                    try: action()
                    except RuntimeError as exc: errors.append(str(exc))
            worker = Thread(target=other_thread); worker.start(); worker.join(2)
            self.assertFalse(worker.is_alive()); self.assertEqual(len(errors), 3)
            self.assertTrue(all('one executor thread' in error for error in errors))
            self.assertEqual(self.live, {'llm'})
        self.assertFalse(self.live)

    def test_checkpoint_hit_needs_no_server_and_payload_is_unchanged(self):
        runtime = {'reasoning': 'on', 'reasoning_budget': 1024, 'context': 8192}
        request = {'system': 'test', 'data': {'source': 'original'}, 'schema': {}, 'max_tokens': 512}
        executed = []
        class Base:
            def __init__(self, directory, models):
                self.directory = directory; self.plan_sha = 'a'*64; self.seq = 0; self.models = models
            def call(self, stage, req, *, provider=None, maximum=None):
                def operation():
                    executed.append((stage, req, provider, maximum)); self.seq += 1
                    return {'output': {'stage': stage}, 'errors': []}
                return self.models.invoke('llm' if provider is None else 'auxiliary', operation)
        with tempfile.TemporaryDirectory() as tmp:
            with self.models() as first:
                expected = CheckpointRunner(Base(Path(tmp), first), runtime).call('saved', request)
            before = list(self.events)
            with self.models() as resumed:
                checkpoint = CheckpointRunner(Base(Path(tmp), resumed), runtime)
                self.assertEqual(checkpoint.call('saved', request), expected)
                self.assertEqual(checkpoint.reused, 1)
            self.assertEqual(resumed.server_starts, 0); self.assertEqual(self.events, before)
            self.assertEqual(len(executed), 1)
            self.assertEqual(executed[0][1], {**request, 'max_tokens': 1536})
            self.assertEqual(request['max_tokens'], 512)
            with self.models() as third:
                CheckpointRunner(Base(Path(tmp), third), runtime).call(
                    'embedding', {**request, 'max_tokens': 1}, provider=auxiliary, maximum=900)
            self.assertEqual(third.server_starts, 0); self.assertEqual(third.auxiliary_calls, 1)
        self.assertEqual(len(executed), 2)
        self.assertEqual(executed[-1][1], {**request, 'max_tokens': 1})
        self.assertIs(executed[-1][2], auxiliary); self.assertEqual(executed[-1][3], 900)


if __name__ == '__main__':
    unittest.main()
