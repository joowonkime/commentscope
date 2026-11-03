"""Replay saved request/output constraints offline, without contacting a provider.

Reports omit originals, model text and binder messages. Historical failures are
diagnostics, never new-run qualification or permission to reuse paid responses.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from commentscope.contracts.structured_output import inspect_schema, check_output
from commentscope.factory.automatic_contract import digest
from commentscope.storage import write_json_exclusive

VERSION = 'offline-factory-contract-audit-0.1'


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _stage(path):
    name = path.name.removesuffix('.request.json').split('-', 1)[-1]
    return re.sub(r'-[0-9a-f]{20}$', '', name)


def audit_runs(directories):
    counts = Counter(); stages = defaultdict(Counter); schemas = {}
    failures = []; response_failures = []; integrity = []
    runs = sorted({Path(p).resolve() for p in directories})
    for directory in runs:
        requests = {}
        for path in sorted((directory/'calls').glob('*.request.json')):
            counts['requests'] += 1; stage = _stage(path); stages[stage]['requests'] += 1
            try:
                saved = _read(path); request = saved['request']; key = digest(request)
                if saved['request_sha256'] != key:
                    raise ValueError('request_digest_mismatch')
                schema = request['schema']; schema_key = digest(schema)
                requests[key] = schema
            except (ValueError, TypeError, KeyError):
                integrity.append({'run': str(directory), 'file': path.name, 'kind': 'invalid_request_identity'})
                continue
            if schema_key not in schemas:
                schemas[schema_key] = {'requests': 0, **inspect_schema(schema)}
            schemas[schema_key]['requests'] += 1
            result_path = path.with_name(path.name.replace('.request.json', '.result.json'))
            if not result_path.exists():
                counts['missing_results'] += 1; stages[stage]['missing_results'] += 1; continue
            try:
                result = _read(result_path)
                if not isinstance(result, dict): raise ValueError('result_object')
                checked = None
                if result.get('errors'):
                    status = 'generation_or_transport_errors'
                elif 'output' not in result:
                    status = 'missing_outputs'
                else:
                    checked = check_output(schema, result['output'])
                    status = ('unsupported_schemas' if not checked['checked'] else
                              'schema_violations' if checked['errors'] else 'schema_valid_outputs')
            except (ValueError, TypeError):
                integrity.append({'run': str(directory), 'file': result_path.name, 'kind': 'invalid_result_record'})
                continue
            counts[status] += 1; stages[stage][status] += 1
            if status != 'schema_valid_outputs':
                response_failures.append({'run': str(directory), 'file': result_path.name,
                    'stage': stage, 'request_sha256': key, 'classification': status,
                    'constraint_errors': checked['errors'] if checked else []})
        for path in sorted((directory/'artifacts'/'errors').glob('*.json')):
            counts['binding_failures'] += 1
            try:
                saved = _read(path); result = saved['result']; key = saved['request_sha256']
                stage = saved['stage']; schema = requests.get(key)
                checked = None
                if schema is None:
                    kind = 'request_not_found'
                elif not isinstance(result, dict) or result.get('errors') or 'output' not in result:
                    kind = 'generation_or_transport_error'
                else:
                    checked = check_output(schema, result['output'])
                    kind = ('unsupported_schema' if not checked['checked'] else
                            'schema_violation' if checked['errors'] else 'binder_only_rejection')
                failures.append({'run': str(directory), 'file': path.name, 'stage': stage,
                    'request_sha256': key, 'classification': kind,
                    'constraint_errors': checked['errors'] if checked else []})
            except (ValueError, TypeError, KeyError):
                integrity.append({'run': str(directory), 'file': path.name, 'kind': 'invalid_binding_error_record'})
    for name in ('requests', 'missing_results', 'binding_failures', 'schema_valid_outputs',
                 'schema_violations', 'generation_or_transport_errors', 'missing_outputs', 'unsupported_schemas'):
        counts.setdefault(name, 0)
    counts['integrity_errors'] = len(integrity)
    counts['unique_schemas'] = len(schemas)
    counts['unsupported_contracts'] = sum(not s['supported'] for s in schemas.values())
    return {'artifact_kind': VERSION, 'counts': dict(counts),
            'stages': {k: dict(v) for k, v in sorted(stages.items())},
            'schemas': schemas, 'binding_failures': failures,
            'response_failures': response_failures, 'integrity_errors': integrity,
            'runs': [str(p) for p in runs], 'network_calls': 0,
            'historical_diagnostics_only': True, 'semantic_approval': False,
            'current_code_qualification': False, 'binder_reexecution': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append', required=True,
                        help='Saved run directory; repeat to include several runs')
    parser.add_argument('--output', type=Path, required=True, help='New private report path; never overwritten')
    args = parser.parse_args()
    if any(not (p/'calls').is_dir() for p in args.run):
        parser.error('Each run must contain a calls directory')
    report = audit_runs(args.run)
    write_json_exclusive(args.output, report)
    print(json.dumps({'counts': report['counts'], 'network_calls': 0,
                      'historical_diagnostics_only': True}, sort_keys=True))
    return 1 if report['counts']['integrity_errors'] or report['counts']['unsupported_contracts'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
