"""Freeze identical synthetic Factory requests for Codex and local Qwen.

This development comparison never grants G1/G2/G3/G4 admission. It preserves
first outputs; equality between providers does not establish semantic truth.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from commentscope.factory import owned_arguments as oa, explicit_discourse as ed
from commentscope.factory import source_scope, literal_discovery
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers import codex_runner, llama_runtime, host_resources
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.providers.runtime_runner import RuntimeRunner
from commentscope.storage import write_json_exclusive as write
from experiments.compare_backend_discovery import check_quota, quota_watch
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.minimal_factory_pipeline import portable_host_observation, private
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'codex-local-development-comparison-0.1'


def request_pack():
    cases = []
    texts = [
        ('request', 'Offer evening clinic appointments.', False),
        ('existing-rule', 'The clinic currently requires a ticket.', False),
        ('empirical-ground', 'I choose the train because diesel prices have risen.', True),
        ('value-ground', 'I prefer flexible shifts because autonomy matters.', True),
        ('forecast', 'The harbor may close tomorrow.', False),
        ('reported', 'My colleague says "The park should charge admission." I disagree.', False),
    ]
    for sid, text, ground in texts:
        graph = ed.parse({'id': sid, 'text': text, 'parent': None})
        node = next(n for n in graph['nodes'] if not ground or n['kind'] == 'ground')
        cases.append({'id': sid, 'request': oa.metadata_request(graph, node)})
    graph = ed.parse({'id': 'nominal-reference',
                     'text': 'Inspect playgrounds. The process should be transparent.', 'parent': None})
    cases.append({'id': 'nominal-reference', 'request': source_scope.request(graph, literal_discovery.roots(graph)[-1])})
    graph = ed.parse({'id': 'conditional', 'parent': None,
        'text': 'Tree inspections should be required only if small schools get fee waivers.'})
    cases.append({'id': 'conditional', 'request': literal_discovery.selection_request(
        graph, [n['id'] for n in literal_discovery.roots(graph)])})
    return {'version': VERSION, 'source_kind': 'synthetic', 'cases': cases,
            'reference_labels_in_requests': False, 'independent_gold': False}


def prepare(directory, qwen_deployment, model, effort, ledger, cycle_id):
    private(directory)
    if directory.exists():
        raise ValueError('New comparison directory required')
    executable = Path(shutil.which('codex') or '').resolve()
    if not executable.is_file():
        raise ValueError('Codex CLI not found')
    deployment = codex_runner.validate({'version': codex_runner.VERSION,
        'executable': str(executable), 'sha256': codex_runner.file_sha256(executable),
        'cli_version': subprocess.check_output([str(executable), '--version'], text=True, timeout=10).strip(),
        'model': model, 'reasoning_effort': effort,
        'auth_home': str(Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')).resolve()),
        'call_seconds': 600})
    pack = request_pack()
    write(directory/'requests.json', pack)
    plan = {'artifact_kind': VERSION, 'request_pack_sha256': sha(directory/'requests.json'),
        'code_sha256': code_hashes(), 'backends': {'codex': deployment,
            'qwen': llama_runtime.validate(read_json(qwen_deployment))},
        'budget': {'ledger': str(ledger.resolve()), 'cycle_id': cycle_id},
        'resource_policy': deepcopy(host_resources.POLICY),
        'limits': {'call_seconds': 600, 'analysis_seconds': None},
        'runtime': {'context': 8192, 'reasoning': 'off', 'reasoning_budget': 0},
        'codex_output_budget': 'advisory only; native usage includes harness and reasoning',
        'codex_thinking_same_as_qwen': False, 'quality_gate_passed': False,
        'purpose': 'Development provider comparison; no independent gold or Factory admission'}
    write(directory/'plan.json', plan)
    for source in plan['code_sha256']:
        target = directory/'frozen-code'/source
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
    return {'prepared': str(directory), 'cases': len(pack['cases']), 'inference_calls': 0}


def validate(directory):
    private(directory)
    plan = read_json(directory/'plan.json')
    if (plan['artifact_kind'] != VERSION or plan['resource_policy'] != host_resources.POLICY
            or sha(directory/'requests.json') != plan['request_pack_sha256']
            or plan['code_sha256'] != code_hashes()):
        raise ValueError('Frozen comparison inputs or code changed')
    return plan


def run(directory, backend):
    check_quota(wait_for_fresh=False)
    plan = validate(directory)
    with experiment_lock(directory), quota_watch():
        observation = portable_host_observation()
        reasons = host_resources.reasons(observation, plan['resource_policy'])
        if backend == 'qwen':
            reasons += llama_runtime.startup_reasons(observation, plan['backends']['qwen'])
        if reasons:
            record = {'backend': backend, 'status': 'resource_hold', 'observation': observation,
                      'reasons': sorted(set(reasons)), 'inference_calls': 0}
            write(directory/'holds'/f'{backend}-{time.time_ns()}.json', record)
            return record
        root = directory/backend
        subplan = {**deepcopy(plan), 'deployment': plan['backends'][backend],
                   'comparison_plan_sha256': sha(directory/'plan.json')}
        if (root/'plan.json').exists():
            if read_json(root/'plan.json') != subplan:
                raise ValueError('Backend plan changed')
        else:
            write(root/'plan.json', subplan)
        if (root/'completed.json').exists():
            return read_json(root/'completed.json')
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)

        def guard():
            check_quota(wait_for_fresh=False)

        def execute(base):
            checkpoint = CheckpointRunner(base, plan['runtime'])
            outputs = []
            for case in read_json(directory/'requests.json')['cases']:
                guard()
                if backend == 'qwen':
                    if not base.client.measure(case['request'])['fits']:
                        raise ValueError('Qwen context capacity exceeded; no truncation')
                result = checkpoint.call(case['id'], case['request'])
                if result.get('errors'):
                    raise ValueError('Comparison call failed; no automatic repair')
                outputs.append({'id': case['id'], 'request_sha256': digest(case['request']), 'result': result})
                print(json.dumps({'backend': backend, 'completed': len(outputs), 'case': case['id']}), flush=True)
            write(root/'outputs.json', outputs)
            completed = {'backend': backend, 'execution_complete': True,
                'plan_sha256': sha(root/'plan.json'), 'outputs_sha256': sha(root/'outputs.json'),
                'cases': len(outputs), 'reused_calls': checkpoint.reused,
                'quality_gate_passed': False, 'semantic_review_required': True}
            write(root/'completed.json', completed)
            return completed

        with host_resources.watch(root/'resources'/str(time.time_ns()), plan['resource_policy'], portable_host_observation):
            if backend == 'codex':
                return execute(codex_runner.CodexRunner(root, subplan, budget, guard))
            with llama_runtime.owned_server(plan['backends']['qwen'], root/'server'/str(time.time_ns()),
                                            portable_host_observation, guard) as client:
                return execute(RuntimeRunner(root, subplan, budget, client))


def report(directory):
    plan = validate(directory)
    data = {}
    for backend in ('codex', 'qwen'):
        root = directory/backend
        if (root/'completed.json').exists():
            done = read_json(root/'completed.json')
            expected = {**deepcopy(plan), 'deployment': plan['backends'][backend],
                        'comparison_plan_sha256': sha(directory/'plan.json')}
            if (read_json(root/'plan.json') != expected
                    or done['plan_sha256'] != sha(root/'plan.json')
                    or done['outputs_sha256'] != sha(root/'outputs.json')):
                raise ValueError('Stored output changed')
            data[backend] = {r['id']: r for r in read_json(root/'outputs.json')}
            if set(data[backend]) != {c['id'] for c in read_json(directory/'requests.json')['cases']}:
                raise ValueError('Complete comparison case coverage required')
    rows = []
    for case in read_json(directory/'requests.json')['cases']:
        row = {'id': case['id'], 'request_sha256': digest(case['request'])}
        for backend in data:
            result = data[backend][case['id']]
            if result['request_sha256'] != row['request_sha256']:
                raise ValueError('Providers received different logical requests')
            row[backend] = result['result']['output']
        row['same_json'] = row['codex'] == row['qwen'] if len(data) == 2 else None
        rows.append(row)
    return {'plan_sha256': sha(directory/'plan.json'), 'completed_backends': list(data),
            'cases': rows, 'quality_gate_passed': False, 'independent_gold': False,
            'semantic_review_required': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--qwen-deployment', type=Path, required=True)
    p.add_argument('--codex-model', required=True)
    p.add_argument('--codex-effort', choices=['low', 'medium', 'high', 'xhigh'], default='low')
    p.add_argument('--ledger', type=Path, required=True); p.add_argument('--cycle-id', required=True)
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    p.add_argument('--backend', choices=['codex', 'qwen'], required=True)
    p = sub.add_parser('report'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.directory, args.qwen_deployment, args.codex_model,
                         args.codex_effort, args.ledger, args.cycle_id)
    elif args.action == 'run':
        result = run(args.directory, args.backend)
    else:
        result = report(args.directory)
    print(json.dumps(result, ensure_ascii=False, indent=2))
