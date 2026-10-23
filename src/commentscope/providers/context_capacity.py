"""Measure the loaded llama.cpp template; split work without cutting sources.

Endpoints: llama.cpp b11541 tools/server/README.md, /apply-template and /tokenize.
These local metadata requests perform no inference and never reserve ledger calls.
"""
from copy import deepcopy
import json
from urllib.request import Request, build_opener, ProxyHandler

from commentscope.factory.automatic_contract import digest
from commentscope.providers.local_llama import NoRedirect

VERSION = 'template-context-capacity-20261016-v1'


def post(path, payload):
    if path not in ('/apply-template', '/tokenize'):
        raise ValueError('Only local template/tokenization endpoints allowed')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    req = Request('http://127.0.0.1:8091'+path, data=json.dumps(payload).encode(),
                  headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=30) as response:
        return json.load(response)


def measure(request, *, transport=post, context=8192, margin=256):
    if (set(request) != {'system', 'data', 'schema', 'max_tokens'}
            or type(request['max_tokens']) is not int or request['max_tokens'] < 1
            or context != 8192 or margin != 256):
        raise ValueError('Frozen complete context allocation required')
    payload = {'messages': [{'role': 'system', 'content': request['system']},
                            {'role': 'user', 'content': json.dumps(request['data'], ensure_ascii=False)}],
               'response_format': {'type': 'json_schema', 'json_schema': {
                   'name': 'perspective_draft', 'strict': True, 'schema': request['schema']}},
               'chat_template_kwargs': {'enable_thinking': False}}
    formatted = transport('/apply-template', payload)
    if not isinstance(formatted.get('prompt'), str) or not formatted['prompt']:
        raise ValueError('Loaded server template did not return a prompt')
    tokenized = transport('/tokenize', {'content': formatted['prompt'], 'add_special': True, 'parse_special': True})
    tokens = tokenized.get('tokens')
    if not isinstance(tokens, list) or any(type(t) is not int for t in tokens):
        raise ValueError('Loaded server tokenization did not return token IDs')
    count = len(tokens)
    return {'artifact_kind': VERSION, 'request_sha256': digest(request),
            'prompt_sha256': digest(formatted['prompt']), 'input_tokens': count,
            'output_reservation': request['max_tokens'], 'safety_margin': margin,
            'context': context, 'fits': count + request['max_tokens'] + margin <= context}


def partition(items, build_request, inspect, *, minimum=1):
    """Deterministic contiguous bisection; inspect must use the loaded template.

    Only oversized requests are split. Errors are not retried or repaired. Every
    original task appears exactly once in fitted work or explicit capacity holds.
    """
    if type(minimum) is not int or minimum < 1:
        raise ValueError('Positive minimum task size required')
    fitted = []; deferred = []
    def visit(group):
        if len(group) < minimum:
            deferred.extend({'item':deepcopy(item),'reason':'minimum_task_size'} for item in group)
            return
        req = build_request(group); measured = inspect(req)
        if measured['request_sha256'] != digest(req):
            raise ValueError('Capacity measurement belongs to another request')
        if measured['fits']:
            fitted.append({'items': deepcopy(group), 'request': req, 'capacity': measured})
        elif len(group) < 2 * minimum:
            reason='context_capacity' if minimum==1 else 'context_capacity_minimum_group'
            deferred.extend({'item':deepcopy(item),'reason':reason,'capacity':measured} for item in group)
        else:
            mid = len(group)//2; visit(group[:mid]); visit(group[mid:])
    if items: visit(list(items))
    return fitted, deferred
