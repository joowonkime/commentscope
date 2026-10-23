#!/usr/bin/env python3
"""Prepare/freeze, then execute one authorized Terra diagnostic; never retry.

Subscription text inference in an empty, read-only working directory with tools
disabled. This does not change the Factory provider or its Qwen inference ledger.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from commentscope.factory import typed_interpretation as ti
from commentscope.factory import typed_interpretation_v2 as ti_v2
from commentscope.factory import explicit_discourse as discourse

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def read(path):
    return json.loads(path.read_text())


def code_freeze():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('src', 'tests', 'experiments')
            for p in sorted((ROOT / folder).rglob('*.py'))}


def legacy_audit(input_value):
    """Structural replay, not a replacement semantic evaluation of old outputs."""
    source_by_id = {s['id']: s for s in sources_from_input(input_value)}
    results = {}
    for name in ('gpt', 'luna', 'terra'):
        run = ROOT / 'runs' / f'{name}-feasibility-20261017-v1'
        items = []
        for case in read(run / 'output.json')['cases']:
            source = source_by_id[case['id']]; graph = discourse.parse(source)
            for statement in case['statements']:
                target = ti.quote_span(source['text'], statement['exact_quote'])
                for quote in statement['reason_quotes']:
                    ground = ti.quote_span(source['text'], quote)
                    if ti.overlaps(target, ground):
                        verdict = 'reject_self_or_overlapping_reason'
                    elif ti.surface_reason(graph, target, ground):
                        verdict = 'surface_syntax_only'
                    else:
                        verdict = 'pending_semantic_review'
                    items.append({'statement_id': statement['id'], 'reason_quote': quote,
                                  'structural_verdict': verdict, 'semantic_approval': False})
        results[name] = {'run': str(run.relative_to(ROOT)), 'items': items,
                        'counts': dict(Counter(i['structural_verdict'] for i in items))}
    return {'model_calls': 0, 'method': 'original quote/range replay only; no semantic relabeling',
            'results': results, 'quality_gate_passed': False}


def sources_from_input(value):
    return [{'id': c['id'], 'text': c['text'],
             'parent': {'id': c['id'] + '.parent', 'text': c['parent_text']} if c['parent_text'] else None,
             'video_context': {'artifact_kind': 'snapshot-video-context-20261017-v1',
                'video_id': 'kl39KHS07Xc', 'title': value['video_title'], 'primary_language': 'en'}}
            for c in value['cases']]


def prepare(run, contract_name='v1'):
    run.mkdir(parents=True, exist_ok=False)
    input_path = ROOT / 'runs/terra-feasibility-20261017-v1/input.json'
    contract = {'v1': ti, 'v2': ti_v2}[contract_name]
    value = read(input_path); sources = sources_from_input(value); req = contract.request(sources)
    write(run / 'input.json', value); write(run / 'sources.json', sources)
    write(run / 'schema.json', req['schema'])
    (run / 'prompt.txt').write_text(req['prompt'])
    write(run / 'legacy-replay.json', legacy_audit(value))
    write(run / 'pre-run-review-criteria.json', {
        'review_type': 'assistant offline original comparison, not independent human gold',
        'reuse_previous_criteria': 'runs/terra-feasibility-20261017-v1/pre-run-review-criteria.json',
        'required': ['No self reasons, background-as-reason, borrowed reasons or altered owner',
            'Correct statement-level metadata/topic routing, including mixed and contextual replies',
            'Fictional setting and conditionality remain separate; unresolved meaning cannot enter comparison',
            'Preserve recommendations, reports, uncertainty, contrast and ambiguous references',
            'Preserve short contextual attitudes without inventing policy support',
            'Preserve conditions, modality, fictional world and individual concrete facets',
            'No binding errors; no semantic approval from exact quotes/syntax alone'],
        'advance_to_24': (
            'Zero binding errors or unhandled scope conflicts; C3 metadata only; every other source retains at least one faithful author proposal. '
            'Intrinsic ambiguity must remain literal and locally held, never guessed; correct uncertainty is not an error and does not count as verified support. '
            'Review every claim/scope; then prepare actual integration separately, never call source-only probe full G2'
            if contract_name == 'v2' else
            'Only if all six known cases have no material semantic loss/error and no structural holds; then prepare integration separately, never call source-only probe full G2'),
        'denominators_unchanged': True, 'all999_authorized': False})
    write(run / 'plan.json', {'prepared_at': now(), 'contract': contract.VERSION,
        'authorization': 'User authorized Terra groundwork and small recheck with go-ahead; no full-corpus/provider migration',
        'hypothesis': 'Separate exact evidence, premises, content routing and scope; deterministic ownership/scope guards retain ambiguities as holds',
        'responsible_modules': ['src/commentscope/factory/typed_interpretation.py',
                               'src/commentscope/factory/typed_interpretation_v2.py',
                               'src/commentscope/factory/interpretation_scope.py',
                               'experiments/typed_interpretation_probe.py'],
        'model': 'gpt-5.6-terra', 'reasoning_effort': 'medium', 'requests_planned': 1,
        'call_timeout_seconds': 300, 'transport_retries': 0, 'application_retries': 0,
        'aggregate_budget_added': False, 'api_keys_used': False,
        'reference_indices': [7, 8, 15, 17, 19, 23],
        'selection': 'Same six known failures; development diagnostic, not held-out or representative',
        'comparison': 'Same Terra model/input; changed contract/prompt; not a causal model comparison',
        'runtime_labels_or_prior_outputs_supplied': False,
        'main_pipeline_changed': False, 'factory_criteria_changed': False,
        'input_sha256': hashlib.sha256(input_path.read_bytes()).hexdigest()})
    write(run / 'freeze.json', {'code': code_freeze(), 'files': {
        name: hashlib.sha256((run / name).read_bytes()).hexdigest()
        for name in ('input.json', 'sources.json', 'prompt.txt', 'schema.json',
                     'plan.json', 'pre-run-review-criteria.json')}})
    print(json.dumps({'prepared': str(run), 'calls': 0,
                      'legacy_counts': {k: v['counts'] for k, v in read(run / 'legacy-replay.json')['results'].items()}}))


def execute(run):
    freeze = read(run / 'freeze.json')
    if freeze['code'] != code_freeze() or any(
            hashlib.sha256((run / name).read_bytes()).hexdigest() != sha
            for name, sha in freeze['files'].items()):
        raise ValueError('Frozen code/input/criteria changed; prepare a new run')
    # Exclusive marker prevents accidental repeat inference after interruption.
    with (run / 'started.json').open('x') as marker:
        json.dump({'started_at': now(), 'requests': 1, 'retries': 0}, marker)
    workdir = tempfile.mkdtemp(prefix='commentscope-terra-typed-')
    argv = ['codex', 'exec', '--ignore-user-config', '--skip-git-repo-check', '--ephemeral',
            '--model', 'gpt-5.6-terra']
    settings = ['model_reasoning_effort="medium"', 'web_search="disabled"', 'approval_policy="never"',
        'features.shell_tool=false', 'features.unified_exec=false', 'features.multi_agent=false',
        'features.apps=false', 'model_provider="commentscope_probe"',
        'model_providers.commentscope_probe.name="OpenAI"',
        'model_providers.commentscope_probe.requires_openai_auth=true',
        'model_providers.commentscope_probe.wire_api="responses"',
        'model_providers.commentscope_probe.request_max_retries=0',
        'model_providers.commentscope_probe.stream_max_retries=0']
    for setting in settings:
        argv += ['-c', setting]
    argv += ['-s', 'read-only', '-C', workdir, '--json', '--output-schema', str(run / 'schema.json'),
             '-o', str(run / 'output.json'), '-']
    write(run / 'invocation.json', {'argv': argv, 'started_at': now()})
    env = dict(os.environ)
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'CODEX_THREAD_ID'):
        env.pop(key, None)
    started = time.monotonic(); code = None; error = None
    try:
        with (run / 'events.jsonl').open('w') as out, (run / 'stderr.txt').open('w') as err:
            result = subprocess.run(argv, input=(run / 'prompt.txt').read_text(), text=True,
                stdout=out, stderr=err, env=env, timeout=300)
            code = result.returncode
    except (subprocess.TimeoutExpired, OSError) as exc:
        error = str(exc)
    write(run / 'execution.json', {'exit_code': code, 'error': error,
        'elapsed_seconds': time.monotonic() - started, 'finished_at': now(),
        'output_exists': (run / 'output.json').exists()})
    if code != 0 or error:
        raise RuntimeError('Single attempt failed; retained original artifacts; no retry')
    replay(run)


def replay(run):
    events = [json.loads(line) for line in (run / 'events.jsonl').read_text().splitlines() if line.strip()]
    unexpected = [e for e in events if e.get('item', {}).get('type') not in (None, 'agent_message', 'reasoning')]
    usage = [e['usage'] for e in events if e.get('type') == 'turn.completed' and 'usage' in e]
    write(run / 'usage.json', {'completed_turn_usage': usage, 'unexpected_tool_events': unexpected,
                             'subscription_percentage_inferred': False})
    if unexpected:
        raise ValueError('Unexpected tool activity; keep output held')
    if len(usage) != 1 or any(e.get('type') == 'turn.failed' for e in events):
        raise ValueError('Expected exactly one completed inference; keep output held')
    contract_version = read(run / 'plan.json')['contract']
    contract = {ti.VERSION: ti, ti_v2.VERSION: ti_v2}[contract_version]
    result = contract.bind_batch(read(run / 'sources.json'), read(run / 'output.json'))
    write(run / 'binding-validation.json', result)
    print(json.dumps({'bound_sources': len(result['records']), 'errors': result['errors'], 'usage': usage}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'run', 'replay'])
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--contract', choices=['v1', 'v2'], default='v1', help='Contract for prepare; execution uses its frozen plan')
    args = parser.parse_args(); run = args.run.resolve()
    if args.stage == 'prepare':
        prepare(run, args.contract)
    else:
        {'run': execute, 'replay': replay}[args.stage](run)
