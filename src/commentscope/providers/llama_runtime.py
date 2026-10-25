"""Model-neutral, loopback llama.cpp deployment with an owned lifetime.

No downloads or inference happen on import. Callers supply quota and host
observations; the existing ledger/checkpoint layer still owns model requests.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time
from urllib.request import Request, build_opener, ProxyHandler

from commentscope.file_integrity import file_sha256
from commentscope.providers import context_capacity, host_resources
from commentscope.providers.local_llama import NoRedirect
from commentscope.storage import write_json_exclusive as write

VERSION = 'portable-llama-runtime-0.1'
STARTUP = {'minimum_available_mb': 4096,
           'minimum_commit_headroom_bytes': 4 * 1024**3,
           'minimum_gpu_free_mb': 3072,
           'maximum_weight_bytes': 3 * 1024**3}


def file_hash(path):
    return file_sha256(path)


def validate(deployment):
    """Freeze a separate small-model profile; do not alter legacy 8B guards."""
    if set(deployment) != {'version', 'model', 'server', 'runtime', 'startup', 'resource_policy'}:
        raise ValueError('Complete portable deployment required')
    if deployment['version'] != VERSION or deployment['startup'] != STARTUP:
        raise ValueError('Unknown portable startup profile')
    host_resources.validate(deployment['resource_policy'])
    model, server, runtime = (deployment[k] for k in ('model', 'server', 'runtime'))
    if (set(model) != {'name', 'repository', 'revision', 'path', 'sha256'}
            or set(server) != {'path', 'sha256', 'libraries'}):
        raise ValueError('Pinned model and server identities required')
    for entry in (model, server):
        if (not isinstance(entry['path'], str) or not Path(entry['path']).is_absolute()
                or not isinstance(entry['sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
            raise ValueError('Absolute artifact path and SHA256 required')
    if (not model['path'].endswith('.gguf')
            or not isinstance(model['name'], str) or not model['name'].strip()
            or not isinstance(model['repository'], str) or not model['repository'].strip()
            or not isinstance(model['revision'], str)
            or not re.fullmatch('[0-9a-f]{40}', model['revision'])
            or not isinstance(server['libraries'], str)):
        raise ValueError('Versioned GGUF and library search path required')
    expected = {'context', 'threads', 'gpu_layers', 'port', 'batch_size', 'ubatch_size',
                'call_seconds', 'startup_seconds', 'thinking'}
    ranges = {'threads': (1, 64), 'gpu_layers': (1, 999), 'port': (1024, 65535),
              'batch_size': (32, 512), 'ubatch_size': (32, 128)}
    if (set(runtime) != expected or type(runtime['context']) is not int
            or runtime['context'] != 8192 or runtime['thinking'] is not False):
        raise ValueError('8192 context and thinking off required')
    for field, (low, high) in ranges.items():
        if type(runtime[field]) is not int or not low <= runtime[field] <= high:
            raise ValueError('Invalid runtime field: ' + field)
    if runtime['ubatch_size'] > runtime['batch_size']:
        raise ValueError('Microbatch cannot exceed batch')
    for field in ('call_seconds', 'startup_seconds'):
        value = runtime[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Finite positive per-operation deadline required')
    return deepcopy(deployment)


def command(deployment):
    d = validate(deployment); r = d['runtime']
    return [d['server']['path'], '-m', d['model']['path'],
            '--host', '127.0.0.1', '--port', str(r['port']),
            '-c', str(r['context']), '--no-context-shift',
            '-ngl', str(r['gpu_layers']), '-t', str(r['threads']),
            '--parallel', '1', '--jinja', '--no-cache-prompt',
            '--chat-template-kwargs', '{"enable_thinking": false}',
            '--reasoning', 'off', '--reasoning-budget', '0',
            '--load-mode', 'dio', '--cache-ram', '0', '--no-cache-idle-slots',
            '--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0', '--flash-attn', 'on',
            '--batch-size', str(r['batch_size']), '--ubatch-size', str(r['ubatch_size'])]


def startup_reasons(observation, deployment):
    d = validate(deployment)
    result = host_resources.reasons(observation, d['resource_policy'])
    value = observation['gpu_free_mb']
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Fresh GPU headroom required')
    p = d['startup']
    if observation['available_mb'] < p['minimum_available_mb']:
        result.append('startup_available_memory')
    if observation['commit_limit'] - observation['committed_bytes'] < p['minimum_commit_headroom_bytes']:
        result.append('startup_commit_headroom')
    if value < p['minimum_gpu_free_mb']:
        result.append('startup_gpu_headroom')
    return result


class Client:
    """Picklable provider compatible with InferenceBudget's bounded worker."""
    def __init__(self, deployment):
        self.deployment = validate(deployment)

    def post(self, path, payload, *, timeout_seconds=30):
        if path not in ('/health', '/apply-template', '/tokenize', '/v1/chat/completions'):
            raise ValueError('Unknown loopback endpoint')
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0):
            raise ValueError('Finite positive HTTP deadline required')
        port = self.deployment['runtime']['port']
        body = None if path == '/health' else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = Request(f'http://127.0.0.1:{port}{path}', data=body,
                      headers={'Content-Type': 'application/json'})
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(req, timeout=timeout_seconds) as response:
            return json.load(response)

    def generate(self, system, data, schema, max_tokens=3000):
        if type(max_tokens) is not int or not 0 < max_tokens < self.deployment['runtime']['context']:
            raise ValueError('Bounded output allocation required')
        payload = {'model': 'local', 'temperature': 0, 'seed': 407,
                   'max_tokens': max_tokens,
                   'chat_template_kwargs': {'enable_thinking': False},
                   'response_format': {'type': 'json_schema', 'json_schema': {
                       'name': 'perspective_draft', 'strict': True, 'schema': schema}},
                   'messages': [{'role': 'system', 'content': system},
                                {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]}
        return self.post('/v1/chat/completions', payload,
                         timeout_seconds=self.deployment['runtime']['call_seconds'])

    def measure(self, request):
        return context_capacity.measure(request, transport=self.post)


@contextmanager
def owned_server(deployment, directory, observe, check_quota):
    """Start/stop only this server; resource and quota failures escape to caller."""
    d = validate(deployment); directory = Path(directory)
    check_quota()
    if Path(d['model']['path']).stat().st_size > d['startup']['maximum_weight_bytes']:
        raise ValueError('This startup profile is limited to small model weights')
    for artifact in (d['model'], d['server']):
        if file_hash(artifact['path']) != artifact['sha256']:
            raise ValueError('Pinned deployment artifact changed')
    if not os.access(d['server']['path'], os.X_OK):
        raise ValueError('Executable llama-server required')
    observation = observe(); refusals = startup_reasons(observation, d)
    write(directory/'preflight.json', {'observation': observation, 'refusal_reasons': refusals})
    if refusals:
        raise RuntimeError('Portable model startup resource policy refused')
    with socket.socket() as probe:
        # POSIX can reuse TIME_WAIT addresses while refusing active listeners.
        # Windows SO_REUSEADDR can also share an active port; keep its default.
        if os.name == 'posix':
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', d['runtime']['port']))
    argv = command(d); write(directory/'deployment.json', d)
    env = {k: v for k, v in os.environ.items() if not k.startswith('LLAMA_ARG_')}
    env['LD_LIBRARY_PATH'] = d['server']['libraries']
    client = Client(d)
    with (directory/'server.log').open('x') as log:
        proc = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
        started = time.monotonic()
        try:
            with host_resources.watch(directory/'resources', d['resource_policy'], observe):
                while True:
                    check_quota()
                    if proc.poll() is not None:
                        raise RuntimeError('Owned llama-server failed; inspect private log')
                    try:
                        healthy = client.post('/health', None, timeout_seconds=1).get('status') == 'ok'
                    except OSError:
                        healthy = False
                    if healthy:
                        break
                    if time.monotonic() - started >= d['runtime']['startup_seconds']:
                        raise TimeoutError('Local model startup deadline')
                    time.sleep(.2)
                write(directory/'started.json', {'pid': proc.pid, 'command': argv,
                      'startup_seconds': time.monotonic() - started})
                yield client
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=5)
            write(directory/'stopped.json', {'pid': proc.pid, 'returncode': proc.returncode})
        if proc.returncode != 0:
            raise RuntimeError('Owned llama-server shutdown was not clean')
