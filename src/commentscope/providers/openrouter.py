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
from commentscope.factory.automatic_contract import digest

VERSION = 'openrouter-chat-completions-0.1'
ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
CAPACITY_VERSION = 'openrouter-utf8-context-bound-0.1'
PROVIDER_MARGIN = 8192


def validate(deployment):
    required = {'version', 'model', 'context', 'call_seconds'}
    if (not isinstance(deployment, dict) or not required <= deployment.keys()
            or deployment.keys() - required - {'provider', 'reasoning', 'temperature'}
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
    temperature = deployment.get('temperature', 0)
    if temperature is not None and (type(temperature) not in (int, float)
            or not math.isfinite(temperature) or not 0 <= temperature <= 2):
        raise ValueError('Temperature must be finite0..2 or explicit null to omit')
    reasoning = deployment.get('reasoning')
    if reasoning is not None:
        if not isinstance(reasoning, dict):
            raise ValueError('Explicit reasoning enabled flag or effort required')
        enabled = set(reasoning) == {'enabled'} and type(reasoning['enabled']) is bool
        effort = (set(reasoning) == {'effort'} and isinstance(reasoning['effort'], str)
                  and reasoning['effort'] in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'))
        if not (enabled or effort):
            raise ValueError('Choose one explicit reasoning enabled flag or effort')
    return deepcopy(deployment)


def required_parameters(deployment):
    """Endpoint capabilities required by the fields this deployment transmits."""
    deployment = validate(deployment)
    required = {'structured_outputs', 'response_format', 'max_tokens'}
    if deployment.get('temperature', 0) is not None:
        required.add('temperature')
    if deployment.get('reasoning') is not None:
        required.add('reasoning')
    return required


class Client:
    """Picklable client; supply an explicitly selected model deployment."""
    def __init__(self, deployment):
        self.deployment = validate(deployment)

    def payload(self, system, data, schema, max_tokens):
        if type(max_tokens) is not int or not 0 < max_tokens < self.deployment['context']:
            raise ValueError('Bounded output allocation required')
        temperature = self.deployment.get('temperature', 0)
        payload = {'model': self.deployment['model'], 'temperature': temperature,
                   'max_tokens': max_tokens, 'stream': False,
                   'provider': {**self.deployment.get('provider', {}),
                                'require_parameters': True, 'allow_fallbacks': False},
                   'response_format': {'type': 'json_schema', 'json_schema': {
                       'name': 'perspective_draft', 'strict': True, 'schema': schema}},
                   'messages': [{'role': 'system', 'content': system},
                                {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]}
        if temperature is None:
            payload.pop('temperature')
        if 'reasoning' in self.deployment and self.deployment['reasoning'] is not None:
            payload['reasoning'] = deepcopy(self.deployment['reasoning'])
        return payload

    def measure(self, request):
        if set(request) != {'system', 'data', 'schema', 'max_tokens'}:
            raise ValueError('Complete logical request required')
        payload = self.payload(request['system'], request['data'], request['schema'], request['max_tokens'])
        size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        return {'artifact_kind': CAPACITY_VERSION, 'request_sha256': digest(request),
                'input_upper_bound_tokens': size, 'provider_margin': PROVIDER_MARGIN,
                'output_reservation': request['max_tokens'], 'context': self.deployment['context'],
                'native_tokenization': False,
                'fits': size+request['max_tokens']+PROVIDER_MARGIN <= self.deployment['context']}

    def generate(self, system, data, schema, max_tokens=3000):
        payload = self.payload(system, data, schema, max_tokens)
        key = os.environ.get('OPENROUTER_API_KEY', '').strip()
        if not key:
            raise ValueError('OPENROUTER_API_KEY is not configured')
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
