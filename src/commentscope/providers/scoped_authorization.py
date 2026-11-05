"""Immutable authorization for the requested J4 -> G1 -> G2 -> G3 sequence.

This scope does not extend or erase an older cycle. Both transports debit the
same $8 scope in the existing $50 account, with no retries or response imports.
"""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from pathlib import Path
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.openrouter_budget import units
from commentscope.providers import openrouter_decisions as od

VERSION='commentscope-jev-through-g3-authorization-20261106-v1'


def guard(auth, *, call_seconds=0, allow_expired=False, observed_at=None):
    start=datetime.fromisoformat(auth['started_at']);end=datetime.fromisoformat(auth['deadline'])
    if (auth.get('version')!=VERSION or auth.get('tasks')!=['TASK-005','TASK-006']
            or auth.get('gates')!=['G1','G2','G3'] or auth.get('decisions_deployment')!=od.DEPLOYMENT
            or not 0<units(auth['maximum_additional_usd'])<=units('8')
            or start.utcoffset() is None or end.utcoffset() is None
            or not timedelta(0)<end-start<=timedelta(hours=7)):
        raise ValueError('Frozen J4/G1/G2/G3 authorization required')
    now=observed_at or datetime.now(timezone.utc)
    if not allow_expired and not start<=now<end-timedelta(seconds=call_seconds+3):
        raise TimeoutError('Scoped authorization cannot cover the next bounded operation')


def bind(path,deployment,policy,maximum_usd,gate):
    path=Path(path);auth=read_json(path);guard(auth)
    if (gate not in auth['gates'] or deployment!=auth['chat_deployment']
            or units(policy['maximum_usd'])!=units('50')
            or policy!=read_json(auth['shared_policy_file'])
            or units(maximum_usd)!=units(auth['maximum_additional_usd'])):
        raise ValueError('Role map, shared policy, gate or total scope cap changed')
    return {'file':str(path.resolve()),'sha256':sha(path),'authorization':auth}


def check(plan,*,call_seconds=0,allow_expired=False):
    binding=plan.get('scoped_authorization')
    if binding is None:return
    if (set(binding)!={'file','sha256','authorization'} or sha(binding['file'])!=binding['sha256']
            or read_json(binding['file'])!=binding['authorization']
            or plan['inputs'].get(binding['file'])!=binding['sha256']):
        raise ValueError('Scoped authorization binding changed')
    auth=binding['authorization'];guard(auth,call_seconds=call_seconds,allow_expired=allow_expired)
    if (plan['deployment']!=auth['chat_deployment'] or plan['decisions_deployment']!=auth['decisions_deployment']
            or plan['gate'] not in auth['gates'] or plan['spend_policy']!=read_json(auth['shared_policy_file'])
            or units(plan['maximum_cost_usd'])!=units(auth['maximum_additional_usd'])
            or plan.get('execution_cycle') is not None):raise ValueError('Scoped execution role/account changed')


class PaidDecisions(od.DecisionsBudget):
    def __init__(self,base,ledger,*,plan_sha256,binding,paid_provider,key_metadata):
        auth=binding['authorization'];guard(auth)
        if sha(binding['file'])!=binding['sha256'] or read_json(binding['file'])!=auth:
            raise ValueError('Authorization changed before typed accounting')
        super().__init__(base,ledger,plan_sha256=plan_sha256,deployment=auth['decisions_deployment'],
            spend_scope_sha256=binding['sha256'],parent_limit_usd=auth['maximum_additional_usd'],
            opening_scope_charge_usd='0',additional_limit_usd=auth['maximum_additional_usd'],paid_provider=paid_provider,key_metadata=key_metadata)
        self.binding=deepcopy(binding)

    def call(self,payload,plan_sha,*,timeout_seconds,provider):
        if sha(self.binding['file'])!=self.binding['sha256'] or read_json(self.binding['file'])!=self.binding['authorization']:
            raise ValueError('Authorization changed before typed dispatch')
        guard(self.binding['authorization'],call_seconds=timeout_seconds)
        return super().call(payload,plan_sha,timeout_seconds=timeout_seconds,provider=provider)
