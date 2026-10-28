"""Connect a portable local provider to Factory's existing durable call contract."""
from copy import deepcopy
from pathlib import Path
import time

from commentscope.agents.runtime import request
from commentscope.factory.claim_clusters import sha
from commentscope.factory.automatic_contract import digest
from commentscope.providers.budget import BudgetExhausted, positive
from commentscope.storage import write_json_exclusive as write


class RuntimeRunner:
    """Supply to CheckpointRunner; no experiment globals or model names.

    Callers own ExclusiveModels, quota watching, experiment locking and plan
    validation. The plan hash includes the deployment; checkpoints therefore
    cannot silently carry an 8B response into a replacement-model experiment.
    """
    def __init__(self, directory, plan, budget, client, *, clock=time.monotonic):
        if client.deployment != plan['deployment']:
            raise ValueError('Client does not belong to the frozen deployment')
        self.directory = Path(directory)
        self.plan = deepcopy(plan)
        self.plan_sha = sha(self.directory/'plan.json')
        self.budget = budget
        self.client = client
        self.clock = clock
        self.started = clock()
        self.seq = 0

    def call(self, stage, req, *, provider=None, maximum=None):
        deadline = self.plan['limits']['call_seconds'] if maximum is None else maximum
        if not positive(deadline):
            raise ValueError('Finite positive call deadline required')
        cumulative = self.plan['limits']['analysis_seconds']
        if cumulative is not None:
            if not positive(cumulative):
                raise ValueError('Invalid analysis deadline')
            remaining = cumulative - (self.clock() - self.started) - 3
            if remaining <= 0:
                raise TimeoutError('Analysis deadline reached')
            deadline = min(deadline, remaining)
        self.seq += 1
        prefix = f'{self.seq:04}-{stage}'
        write(self.directory/'calls'/(prefix+'.request.json'), {
            'request': req, 'request_sha256': digest(req),
            'plan_sha256': self.plan_sha, 'timeout_seconds': deadline})

        def invoke(system, data, schema):
            return self.budget.call(req, self.plan_sha, timeout_seconds=deadline,
                                    provider=self.client.generate if provider is None else provider)

        if provider is not None:
            result = invoke(None, None, None)
        else:
            try:
                result = request(req['system'], req['data'], req['schema'], invoke)
            except BudgetExhausted:
                raise
            except RuntimeError:
                result = {'raw': None, 'output': None, 'errors': ['bounded_call_failed'],
                          'seconds': None, 'usage': None}
        write(self.directory/'calls'/(prefix+'.result.json'), result)
        return result
