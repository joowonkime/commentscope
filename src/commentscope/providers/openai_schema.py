"""Versioned OpenAI wire schemas with the original host contract retained.

See https://developers.openai.com/api/docs/guides/structured-outputs .
Only array uniqueness is moved to host validation. Unknown constraints fail
closed; root unions use a transport envelope, never a rewritten answer.
"""
from copy import deepcopy
import json

from commentscope.contracts import structured_output
from commentscope.factory.automatic_contract import digest

VERSION = 'openai-strict-schema-20261104-v1'


def validate_wire(schema):
    inspected = structured_output.inspect_schema(schema)
    if not inspected['supported']:
        raise ValueError('Unsupported provider schema constraints: '+str(inspected['issues']))
    if schema.get('type') != 'object' or 'anyOf' in schema:
        raise ValueError('OpenAI wire schema requires an object root without anyOf')
    properties = 0; enums = 0; strings = 0
    def visit(node, depth):
        nonlocal properties, enums, strings
        if not ({'type', 'anyOf', 'enum', 'const'} & node.keys()):
            raise ValueError('OpenAI schema nodes require an explicit type, union or finite values')
        if 'uniqueItems' in node:
            raise ValueError('OpenAI wire schema does not support uniqueItems')
        depth += node.get('type') in ('object', 'array')
        if depth > 10: raise ValueError('OpenAI schema nesting exceeds10 levels')
        if node.get('type') == 'object':
            props = node.get('properties')
            if (not isinstance(props, dict) or node.get('additionalProperties') is not False
                    or set(node.get('required', [])) != set(props)):
                raise ValueError('OpenAI objects require all properties and additionalProperties:false')
            properties += len(props)
            strings += sum(len(k.encode('utf-8')) for k in props)
        values = node.get('enum', [])
        enums += len(values)
        size = sum(len(v.encode('utf-8')) for v in values if isinstance(v, str))
        if len(values) > 250 and size > 15000:
            raise ValueError('OpenAI large enum strings exceed15000 bytes')
        strings += size
        if isinstance(node.get('const'), str): strings += len(node['const'].encode('utf-8'))
        for child in node.get('properties', {}).values(): visit(child, depth)
        if 'items' in node: visit(node['items'], depth)
        for child in node.get('anyOf', []): visit(child, depth)
    visit(schema, 0)
    if properties > 5000 or enums > 1000 or strings > 120000:
        raise ValueError('OpenAI schema property/enum/string limit exceeded')


def compile_schema(canonical):
    inspected = structured_output.inspect_schema(canonical)
    if not inspected['supported']:
        raise ValueError('Canonical schema cannot be completely checked by the host: '+str(inspected['issues']))
    wire = deepcopy(canonical); obligations = []
    def lower(node, path):
        if 'uniqueItems' in node:
            if node.pop('uniqueItems'):
                obligations.append({'path': path, 'constraint': 'uniqueItems'})
                node['description'] = (node.get('description', '')+' Items in this array must be distinct.').strip()
        for key, child in node.get('properties', {}).items():
            lower(child, path+'/properties/'+key.replace('~', '~0').replace('/', '~1'))
        if 'items' in node: lower(node['items'], path+'/items')
        for index, child in enumerate(node.get('anyOf', [])): lower(child, path+'/anyOf/'+str(index))
    lower(wire, '$')
    wrapped = wire.get('type') != 'object' or 'anyOf' in wire
    if wrapped:
        wire = {'type': 'object', 'properties': {'result': wire},
                'required': ['result'], 'additionalProperties': False}
    validate_wire(wire)
    return {'version': VERSION, 'schema': wire, 'wrapped': wrapped,
            'canonical_schema_sha256': digest(canonical), 'wire_schema_sha256': digest(wire),
            'host_obligations': obligations}


def decode(canonical, response):
    """Run only after the untouched receipt is durable and spend is settled."""
    compiled = compile_schema(canonical)
    value = json.loads(response['choices'][0]['message']['content'])
    if compiled['wrapped']:
        if not isinstance(value, dict) or set(value) != {'result'}:
            raise ValueError('Invalid provider transport envelope')
        value = value['result']
    checked = structured_output.check_output(canonical, value)
    if not checked['checked'] or checked['errors']:
        raise ValueError('Provider response violates the unchanged canonical schema')
    if not compiled['wrapped']: return response
    logical = deepcopy(response)
    logical['choices'][0]['message']['content'] = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return logical
