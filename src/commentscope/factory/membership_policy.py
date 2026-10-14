"""Carry the exact evaluated membership policy into downstream requests.

Only source/target data changes. No evaluation labels or model decisions are
policy inputs. This binding preserves a configuration, not semantic approval.
"""
from copy import deepcopy

from commentscope.factory.automatic_contract import digest
from commentscope.factory.scoped_discovery import judge_request


VERSION = 'frozen-membership-policy-0.1'


def from_rows(rows):
    if not rows:
        raise ValueError('Membership policy needs evaluated requests')
    policy = None
    for row in rows:
        req = row['request']
        if digest(req) != row['request_sha256']:
            raise ValueError('Membership request changed')
        if set(req) != {'system', 'data', 'schema', 'max_tokens'}:
            raise ValueError('Unexpected membership request fields')
        original = judge_request(row['text'], row['claim'])
        if req['data'] != original['data'] or req['schema'] != original['schema']:
            raise ValueError('Membership source, target or schema changed')
        candidate = {'version': VERSION, **{k: deepcopy(req[k]) for k in ('system', 'schema', 'max_tokens')}}
        validate(candidate)
        if policy is not None and candidate != policy:
            raise ValueError('Mixed membership policies cannot qualify one deployment')
        policy = candidate
    return policy


def validate(policy):
    if (not isinstance(policy, dict)
            or set(policy) != {'version', 'system', 'schema', 'max_tokens'}
            or policy['version'] != VERSION
            or not isinstance(policy['system'], str) or not policy['system'].strip()
            or type(policy['max_tokens']) is not int or not 1 <= policy['max_tokens'] <= 4096):
        raise ValueError('Invalid frozen membership policy')
    probe = {'id': 'C', 'text': 'Schema probe.', 'kind': 'fact',
             'scope': {'entity': '', 'time': '', 'conditions': ''}, 'requires': []}
    if policy['schema'] != judge_request('Schema probe.', probe)['schema']:
        raise ValueError('Membership schema is incompatible')


def invocation(policy, text, claim):
    validate(policy)
    req = judge_request(text, claim)
    req.update({k: deepcopy(policy[k]) for k in ('system', 'schema', 'max_tokens')})
    return req


def bind_rows(policy, rows):
    """Produce derived requests without editing an earlier frozen artifact."""
    bound = deepcopy(rows)
    for row in bound:
        row['request'] = invocation(policy, row['text'], row['claim'])
        row['request_sha256'] = digest(row['request'])
    return bound
