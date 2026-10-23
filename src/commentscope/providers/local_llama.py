"""Loopback-only transport with proxies and redirects disabled."""
import json
import math
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def generate(system, data, schema, max_tokens=3000, *, timeout_seconds=180):
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('Finite positive local transport timeout required')
    payload = {'model': 'local', 'temperature': 0, 'seed': 407, 'max_tokens': max_tokens,
               'response_format': {'type': 'json_schema', 'json_schema': {'name': 'perspective_draft', 'strict': True, 'schema': schema}},
               'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]}
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request('http://127.0.0.1:8091/v1/chat/completions', data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'})
    with opener.open(request, timeout=timeout_seconds) as response:
        return json.load(response)
