"""Route uncached calls through exclusive LLM/auxiliary lifetimes with exact logs."""
from datetime import datetime, timezone

from commentscope.factory.automatic_contract import digest
from commentscope.providers import framed_embedding, evidence_nli
from commentscope.storage import write_json_exclusive as write


class SequentialRunner:
    """A base-call adapter; CheckpointRunner stays outside this boundary."""
    def __init__(self, base, models, directory):
        self.base, self.models = base, models
        self.directory, self.plan_sha = base.directory, base.plan_sha
        self.events = directory; self.event_sequence = 0

    @property
    def seq(self): return self.base.seq

    @seq.setter
    def seq(self, value): self.base.seq = value

    def call(self, stage, req, *, provider=None, maximum=None):
        if provider is not None and provider not in (framed_embedding.generate, evidence_nli.generate):
            raise ValueError('Unrecognized auxiliary model provider')
        self.event_sequence += 1
        path = self.events/f'{self.event_sequence:05}'
        kind = 'llm' if provider is None else 'auxiliary'
        write(path.with_suffix('.started.json'), {'kind': kind, 'stage': stage, 'plan_sha256': self.plan_sha,
              'request_sha256': digest(req), 'at': datetime.now(timezone.utc).isoformat()})
        try:
            result = self.models.invoke(kind, lambda: self.base.call(stage, req, provider=provider, maximum=maximum))
        except BaseException as exc:
            write(path.with_suffix('.failed.json'), {'exception_type': type(exc).__name__, 'stage': stage})
            raise
        write(path.with_suffix('.finished.json'), {'stage': stage, 'at': datetime.now(timezone.utc).isoformat(),
              'server_starts': self.models.server_starts, 'server_stops': self.models.server_stops,
              'auxiliary_calls': self.models.auxiliary_calls})
        return result
