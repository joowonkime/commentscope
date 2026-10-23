"""Own one persistent LLM or one bounded auxiliary-model call, never both.

This primitive does not execute inference or choose model settings. The caller
supplies the existing owned-server context, a guarded auxiliary context, and a
synchronous bounded operation whose workers have exited before it returns.
Use it below CheckpointRunner so completed cache hits need no model lifetime.
An escaping exception poisons this scope; recovery belongs to the caller's
separately recorded execution, never an implicit retry here.
"""
from threading import get_ident

VERSION = 'exclusive-owned-model-lifetime-0.1'


class ExclusiveModels:
    def __init__(self, server_factory, auxiliary_guard_factory):
        if not callable(server_factory) or not callable(auxiliary_guard_factory):
            raise TypeError('Owned server and auxiliary guard factories required')
        self.server_factory = server_factory
        self.auxiliary_guard_factory = auxiliary_guard_factory
        self.server_starts = 0
        self.server_stops = 0
        self.auxiliary_calls = 0
        self._server = None
        self._entered = False
        self._closed = False
        self._busy = False
        self._failed = False
        self._shutdown_failed = False
        self._owner_thread = get_ident()

    def _require_owner(self):
        if get_ident() != self._owner_thread:
            raise RuntimeError('Lifetime scope belongs to one executor thread')

    def __enter__(self):
        self._require_owner()
        if self._entered or self._closed:
            raise RuntimeError('Lifetime scope cannot be reopened or nested')
        self._entered = True
        return self

    def _stop_server(self):
        if self._shutdown_failed:
            raise RuntimeError('Owned server shutdown remains unconfirmed')
        if self._server is not None:
            context = self._server
            # A failed exit must never be interpreted as released ownership.
            try:
                context.__exit__(None, None, None)
            except BaseException:
                self._shutdown_failed = self._failed = True
                raise
            self._server = None
            self.server_stops += 1

    def __exit__(self, exc_type, exc, traceback):
        self._require_owner()
        self._closed = True
        self._stop_server()
        return False

    def invoke(self, kind, operation):
        self._require_owner()
        if not self._entered or self._closed or self._failed or self._busy:
            raise RuntimeError('Model lifetime scope unavailable or already busy')
        if kind not in ('llm', 'auxiliary') or not callable(operation):
            raise ValueError('Explicit model kind and bounded operation required')
        self._busy = True
        try:
            if kind == 'llm':
                if self._server is None:
                    context = self.server_factory(self.server_starts + 1)
                    context.__enter__()
                    self._server = context
                    self.server_starts += 1
                return operation()
            self._stop_server()
            self.auxiliary_calls += 1
            with self.auxiliary_guard_factory(self.auxiliary_calls):
                result = operation()
            return result
        except BaseException:
            self._failed = True
            raise
        finally:
            self._busy = False
