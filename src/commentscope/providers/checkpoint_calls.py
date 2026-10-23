"""Same-plan durable results; incomplete attempts are never silently retried.

A caller must hold the experiment lock. This cache does not reconstruct or refund
interrupted ledger calls. Ambiguous pending attempts require explicit recovery
after checking the original process and ledger, not a second model request.
"""
from copy import deepcopy
from pathlib import Path
import re

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write

VERSION = 'same-plan-model-call-checkpoint-0.1'


class PendingCallError(RuntimeError):
    pass


class CheckpointRunner:
    def __init__(self, base, runtime):
        self.base = base; self.runtime = deepcopy(runtime); self.reused = 0
        self.directory = Path(base.directory)/'checkpoints'
        files = list((Path(base.directory)/'calls').glob('*.request.json'))
        base.seq = max([int(p.name.split('-', 1)[0]) for p in files] or [0])

    def call(self, stage, req, *, provider=None, maximum=None):
        if not isinstance(stage, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', stage):
            raise ValueError('Safe stage identity required')
        actual = allocate(req, self.runtime) if provider is None else deepcopy(req)
        identity = {'artifact_kind': VERSION, 'plan_sha256': self.base.plan_sha, 'stage': stage,
                    'request_sha256': digest(actual),
                    'provider': 'local_llama' if provider is None else provider.__module__ + ':' + provider.__qualname__}
        key = digest(identity); intent = self.directory/(key + '.intent.json'); done = self.directory/(key + '.result.json')
        if done.exists():
            result = read_json(done)
            if (read_json(intent) != identity or set(result) != {'identity', 'result', 'result_sha256'}
                    or result['identity'] != identity or result['result_sha256'] != digest(result['result'])):
                raise ValueError('Checkpoint identity or result changed')
            self.reused += 1
            return deepcopy(result['result'])
        if intent.exists():
            raise PendingCallError('Pending same-plan call; inspect original process, call artifacts and ledger before recovery')
        write(intent, identity)
        result = self.base.call(stage, actual, provider=provider, maximum=maximum)
        write(done, {'identity': identity, 'result': result, 'result_sha256': digest(result)})
        return result
