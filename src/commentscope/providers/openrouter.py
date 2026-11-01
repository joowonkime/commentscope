"""OpenRouter transport for the existing Factory runner and checkpoints.

Only the endpoint and authentication differ from the logical Factory request.
Keys are read in the worker, never placed in plans, checkpoints or client state.
This module does not select models, start servers, retry calls or grant gates.
"""
from copy import deepcopy
import json
import math
import os
from urllib.request import Request, build_opener, ProxyHandler

from commentscope.providers.local_llama import NoRedirect
from commentscope.providers.runtime_runner import RuntimeRunner

VERSION = 'openrouter-chat-completions-0.1'
ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'


def validate(deployment):
    required = {'version', 'model', 'context', 'call_seconds'}
    if (not isinstance(deployment, dict) or not required <= deployment.keys()
            or deployment.keys() - required - {'provider', 'reasoning'}
            or deployment['version'] != VERSION
            or not isinstance(deployment['model'], str) or not deployment['model'].strip()
            or deployment['model'] != deployment['model'].strip()
            or '/' not in deployment['model']
            or type(deployment['context']) is not int or deployment['context'] < 2
            or type(deployment['call_seconds']) not in (int, float)
            or not math.isfinite(deployment['call_seconds']) or deployment['call_seconds'] <= 0):
        raise ValueError('Explicit OpenRouter model, context and finite deadline required')
    provider = deployment.get('provider', {})
    if (not isinstance(provider, dict) or provider.keys() - {'only', 'order', 'max_price'}
            or any(not isinstance(v, list) or not v
                   or any(not isinstance(p, str) or not p.strip() for p in v)
                   for k, v in provider.items() if k != 'max_price')):
        raise ValueError('Explicit provider names required; routing guarantees cannot be relaxed')
    prices = provider.get('max_price')
    if prices is not None and (not isinstance(prices, dict)
            or set(prices) != {'prompt', 'completion', 'request'}
            or any(type(p) not in (int, float) or not math.isfinite(p) or p < 0
                   for p in prices.values())):
        raise ValueError('Finite nonnegative prompt/completion/request price ceilings required')
    reasoning = deployment.get('reasoning')
    if reasoning is not None:
        if (not isinstance(reasoning, dict) or set(reasoning) != {'enabled'}
                or type(reasoning['enabled']) is not bool):
            raise ValueError('Reasoning must be an explicit enabled flag or omitted')
    return deepcopy(deployment)


class Client:
    """Picklable client; supply an explicitly selected model deployment."""
    def __init__(self, deployment):
        self.deployment = validate(deployment)

    def generate(self, system, data, schema, max_tokens=3000):
        if type(max_tokens) is not int or not 0 < max_tokens < self.deployment['context']:
            raise ValueError('Bounded output allocation required')
        key = os.environ.get('OPENROUTER_API_KEY', '').strip()
        if not key:
            raise ValueError('OPENROUTER_API_KEY is not configured')
        payload = {'model': self.deployment['model'], 'temperature': 0,
                   'max_tokens': max_tokens, 'stream': False,
                   'provider': {**self.deployment.get('provider', {}),
                                'require_parameters': True, 'allow_fallbacks': False},
                   'response_format': {'type': 'json_schema', 'json_schema': {
                       'name': 'perspective_draft', 'strict': True, 'schema': schema}},
                   'messages': [{'role': 'system', 'content': system},
                                {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]}
        if 'reasoning' in self.deployment and self.deployment['reasoning'] is not None:
            payload['reasoning'] = deepcopy(self.deployment['reasoning'])
        req = Request(ENDPOINT, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+key})
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(req, timeout=self.deployment['call_seconds']) as response:
            return json.load(response)


class Runner(RuntimeRunner):
    """Same durable requests/results, distinguished from local checkpoints.

    The caller owns API spend limits and run locking. No local GPU or server
    lifecycle is required by this runner. API usage/cost stays in raw results.
    """
    provider_identity = 'openrouter_chat_completions'
