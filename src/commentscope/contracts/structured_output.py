"""Offline checks for the explicit JSON Schema subset used by Factory.

Unknown keywords make a check incomplete, never silently successful. This is
neither a full JSON Schema implementation nor a provider-support guarantee.
Source membership, cross-field rules and semantic fidelity still need binders.
Diagnostics contain paths and rule names, never rejected output values.
"""
import json
import re

KEYWORDS = {'type', 'properties', 'required', 'additionalProperties', 'items',
            'minItems', 'maxItems', 'uniqueItems', 'minLength', 'maxLength',
            'pattern', 'enum', 'const', 'anyOf', 'description'}
TYPES = {'object', 'array', 'string', 'boolean', 'integer', 'number', 'null'}


def _json(value):
    try:
        json.dumps(value, allow_nan=False)
        return True
    except (ValueError, TypeError):
        return False


def inspect_schema(schema):
    """Inventory constraints requiring host checks; do not infer binder rules."""
    issues = []; obligations = []
    def issue(path, keyword):
        issues.append({'path': path, 'keyword': keyword})
    def visit(node, path):
        if not isinstance(node, dict):
            issue(path, 'schema_object'); return
        for keyword in sorted(node.keys() - KEYWORDS):
            issue(path, keyword)
        if 'type' in node and (not isinstance(node['type'], str) or node['type'] not in TYPES):
            issue(path, 'type')
        for keyword in ('minItems', 'maxItems', 'minLength', 'maxLength'):
            if keyword in node and (type(node[keyword]) is not int or node[keyword] < 0):
                issue(path, keyword)
        for low, high in (('minItems', 'maxItems'), ('minLength', 'maxLength')):
            if (type(node.get(low)) is int and type(node.get(high)) is int
                    and node[low] > node[high]):
                issue(path, low+'>'+high)
        for keyword in ('additionalProperties', 'uniqueItems'):
            if keyword in node and type(node[keyword]) is not bool:
                issue(path, keyword)
        if 'description' in node and not isinstance(node['description'], str):
            issue(path, 'description')
        if 'enum' in node and (not isinstance(node['enum'], list) or not node['enum'] or not _json(node['enum'])):
            issue(path, 'enum')
        if 'const' in node and not _json(node['const']):
            issue(path, 'const')
        if 'required' in node and (not isinstance(node['required'], list)
                or any(not isinstance(k, str) for k in node['required'])
                or len(set(node['required'])) != len(node['required'])):
            issue(path, 'required')
        if 'pattern' in node:
            try:
                re.compile(node['pattern'])
            except (re.error, TypeError):
                issue(path, 'pattern')
            obligations.append({'path': path, 'kind': 'pattern'})
        if node.get('type') == 'string' and 'enum' not in node and 'const' not in node:
            obligations.append({'path': path, 'kind': 'free_text'})
        if 'minLength' in node or 'maxLength' in node:
            obligations.append({'path': path, 'kind': 'string_length'})
        if node.get('uniqueItems') is True:
            obligations.append({'path': path, 'kind': 'array_uniqueness'})
        if not node:
            obligations.append({'path': path, 'kind': 'unconstrained_schema'})
        if 'properties' in node:
            if not isinstance(node['properties'], dict):
                issue(path, 'properties')
            else:
                for name, child in node['properties'].items():
                    if not isinstance(name, str):
                        issue(path, 'property_name'); continue
                    visit(child, path+'/properties/'+name.replace('~', '~0').replace('/', '~1'))
        if 'items' in node:
            visit(node['items'], path+'/items')
        if 'anyOf' in node:
            if not isinstance(node['anyOf'], list) or not node['anyOf']:
                issue(path, 'anyOf')
            else:
                for index, child in enumerate(node['anyOf']):
                    visit(child, path+'/anyOf/'+str(index))
    visit(schema, '$')
    return {'supported': not issues, 'issues': issues, 'obligations': obligations,
            'semantic_approval': False, 'provider_enforcement_assumed': False}


def _equal(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


def check_output(schema, value):
    """Check supported constraints exactly; unsupported schemas are explicit.

    Patterns use Python's regex engine. Callers needing arbitrary JSON Schema
    or different regex dialects must use a full validator instead.
    """
    inspected = inspect_schema(schema)
    if not inspected['supported']:
        return {'checked': False, 'errors': [], 'schema_issues': inspected['issues']}
    errors = []
    def error(path, keyword):
        errors.append({'path': path, 'keyword': keyword})
    def visit(node, item, path):
        kind = node.get('type')
        matches = {'object': isinstance(item, dict), 'array': isinstance(item, list),
                   'string': isinstance(item, str), 'boolean': type(item) is bool,
                   'integer': type(item) is int or (type(item) is float and item.is_integer()),
                   'number': type(item) in (int, float), 'null': item is None}
        if kind and not matches[kind]:
            error(path, 'type'); return
        if 'enum' in node and not any(_equal(item, member) for member in node['enum']):
            error(path, 'enum')
        if 'const' in node and not _equal(item, node['const']):
            error(path, 'const')
        if 'anyOf' in node:
            matched = False
            for child in node['anyOf']:
                before = len(errors); visit(child, item, path)
                matched = matched or len(errors) == before
                del errors[before:]
            if not matched:
                error(path, 'anyOf')
        if isinstance(item, dict):
            properties = node.get('properties', {})
            if any(k not in item for k in node.get('required', [])):
                error(path, 'required')
            if node.get('additionalProperties') is False and item.keys() - properties.keys():
                error(path, 'additionalProperties')
            for name, child in properties.items():
                if name in item:
                    visit(child, item[name], path+'/'+name.replace('~', '~0').replace('/', '~1'))
        if isinstance(item, list):
            for bound, compare in (('minItems', lambda n: len(item) < n), ('maxItems', lambda n: len(item) > n)):
                if bound in node and compare(node[bound]): error(path, bound)
            if node.get('uniqueItems') and any(_equal(a, b) for i, a in enumerate(item) for b in item[:i]):
                error(path, 'uniqueItems')
            if 'items' in node:
                for index, child in enumerate(item): visit(node['items'], child, path+'/'+str(index))
        if isinstance(item, str):
            for bound, compare in (('minLength', lambda n: len(item) < n), ('maxLength', lambda n: len(item) > n)):
                if bound in node and compare(node[bound]): error(path, bound)
            if 'pattern' in node and re.search(node['pattern'], item) is None:
                error(path, 'pattern')
    if not _json(value):
        error('$', 'finite_json')
    else:
        visit(schema, value, '$')
    return {'checked': True, 'errors': errors, 'schema_issues': []}
