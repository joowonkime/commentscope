"""Bind multiple executors to the same approved money and time envelope."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.openrouter_budget import units

CYCLE_VERSION = 'commentscope-autonomous-cycle-20261105-v1'


def cycle_guard(cycle, *, call_seconds=0, allow_expired=False, observed_at=None):
    if (cycle.get('version') != CYCLE_VERSION or 'TASK-004' not in cycle.get('tasks', [])
            or not 0 < units(cycle['maximum_additional_usd']) <= units('5')):
        raise ValueError('Explicit bounded cycle authorization required')
    start = datetime.fromisoformat(cycle['started_at'])
    end = datetime.fromisoformat(cycle['deadline'])
    observed_at = observed_at or datetime.now(timezone.utc)
    if (start.utcoffset() is None or end.utcoffset() is None
            or not timedelta(0) < end-start <= timedelta(hours=7)):
        raise ValueError('At most seven hours with explicit timezone required')
    if not allow_expired and not start <= observed_at < end-timedelta(seconds=call_seconds+3):
        raise TimeoutError('Cycle deadline cannot cover another bounded operation')


def bind_cycle(path, deployment, policy, maximum_usd):
    path=Path(path);cycle=read_json(path)
    cycle_guard(cycle)
    _configuration(cycle,deployment,policy,maximum_usd)
    return {'file':str(path.resolve()),'sha256':sha(path),'cycle':deepcopy(cycle)}


def _configuration(cycle,deployment,policy,maximum_usd):
    if (deployment!=cycle['selected_deployment']
            or policy!=read_json(Path(cycle['shared_policy_file']))
            or units(maximum_usd)!=units(cycle['maximum_additional_usd'])):
        raise ValueError('Factory deployment, policy and total cap must match the original cycle')


def check_cycle(plan, *, call_seconds=0, allow_expired=False):
    binding=plan.get('execution_cycle')
    if binding is None:return
    if (not isinstance(binding,dict) or set(binding)!={'file','sha256','cycle'}
            or sha(binding['file'])!=binding['sha256']
            or read_json(binding['file'])!=binding['cycle']
            or plan['inputs'].get(binding['file'])!=binding['sha256']):
        raise ValueError('Frozen execution cycle changed')
    _configuration(binding['cycle'],plan['deployment'],plan['spend_policy'],plan['maximum_cost_usd'])
    cycle_guard(binding['cycle'],call_seconds=call_seconds,allow_expired=allow_expired)
