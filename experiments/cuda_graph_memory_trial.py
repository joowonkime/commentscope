"""Bounded local deployment diagnostic; never a corpus or quality approval.

Only the CUDA graph environment changes. Six pre-existing synthetic requests,
weights, context, schemas, prompts and resource protections stay unchanged.
The environment is frozen separately from the argv and restored on exit.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import time

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory import position_frames as frames
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, command, file_hash
from experiments.corpus_resource_guard import host_observation
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'cuda-graph-memory-diagnostic-0.1'
ENVIRONMENT = {'GGML_CUDA_DISABLE_GRAPHS': '1'}


@contextmanager
def environment(values):
    if values != ENVIRONMENT:
        raise ValueError('Only the declared CUDA graph intervention is allowed')
    previous = {k: os.environ.get(k) for k in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def prepare(directory, source):
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('New private directory required')
    original = read_json(source)
    if len(original['requests']) != 6:
        raise ValueError('Exactly the existing six synthetic requests are required')
    plan = {k: deepcopy(original[k]) for k in ('deployment', 'requests', 'budget', 'limits')}
    plan.update(artifact_kind=VERSION, environment=deepcopy(ENVIRONMENT),
        command=command(plan['deployment'], 'baseline'),
        inputs={str(source): sha(source)}, code_sha256=code_hashes(),
        hypothesis='Disabling CUDA execution graphs may reduce host commit during local inference.',
        intervention_scope='Only GGML_CUDA_DISABLE_GRAPHS=1; no argv or request changes.',
        acceptance='Six successful bound outputs without a resource stop establish only short-run execution viability.',
        rejection='Any resource stop, call error or frame binding failure rejects this bounded trial.',
        runtime_reference_labels=False, quality_gate_passed=False, fresh_corpus_analysis=False)
    write(directory/'plan.json', plan)


def metrics(directory, results, binding_errors):
    rows = [read_json(p) for p in sorted((directory/'server/resources').glob('[0-9]*.json'))]
    valid = [r['observation'] for r in rows if 'observation' in r]
    resource_stop = (directory/'server/resources/stop-requested.json').exists()
    return {'completed_calls': len(results), 'call_errors': sum(bool(r['errors']) for r in results),
        'frame_binding_errors': binding_errors, 'resource_stop': resource_stop,
        'observation_errors': sum('observation_error' in r for r in rows),
        'minimum_commit_headroom_bytes': min((v['commit_limit']-v['committed_bytes'] for v in valid), default=None),
        'minimum_available_mb': min((v['available_mb'] for v in valid), default=None),
        'short_run_execution_viable': len(results) == 6 and not any(r['errors'] for r in results)
            and not binding_errors and not resource_stop and bool(valid)
            and not any('observation_error' in r for r in rows),
        'quality_gate_passed': False, 'fresh_corpus_analysis': False}


def run(directory):
    if not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('Private directory required')
    with experiment_lock(directory):
        plan = read_json(directory/'plan.json')
        if plan['artifact_kind'] != VERSION or plan['environment'] != ENVIRONMENT:
            raise ValueError('Unknown trial')
        if (plan['command'] != command(plan['deployment'], 'baseline')
                or len(plan['requests']) != 6
                or any(digest(r['request']) != r['request_sha256'] for r in plan['requests'])):
            raise ValueError('Trial requests or command changed')
        for field in ('inputs', 'code_sha256'):
            if any(sha(p) != h for p, h in plan[field].items()):
                raise ValueError('Frozen input or code changed')
        for item in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
            if file_hash(item['path']) != item['sha256']:
                raise ValueError('Deployment changed')
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        runner = Runner(directory, plan, budget)
        write(directory/'started.json', {'pid': os.getpid(), 'plan_sha256': runner.plan_sha,
            'before_host': host_observation(), 'environment': plan['environment']})
        results = []; binding_errors = []; failure = None
        try:
            with environment(plan['environment']), owned_server(plan['deployment'], 'baseline', directory/'server'):
                for row in plan['requests']:
                    result = runner.call('frame-'+row['id'], row['request'])
                    results.append(result)
                    try:
                        write(directory/'frames'/(row['id']+'.json'), frames.bind(row['source'], result))
                    except (ValueError, KeyError, TypeError):
                        binding_errors.append(row['id'])
        except BaseException as exc:
            failure = exc
        report = {**metrics(directory, results, binding_errors), 'plan_sha256': runner.plan_sha,
            'elapsed_seconds': time.monotonic()-runner.started,
            'exception_type': type(failure).__name__ if failure else None, 'budget_after': budget.summary()}
        write(directory/('failed.json' if failure else 'completed.json'), report)
        print({k:v for k,v in report.items() if k != 'budget_after'}, flush=True)
        if failure:
            raise failure
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('directory', type=Path)
    parser.add_argument('--source', type=Path, default=Path('runs/resource-profile-probe-20261014/plan.json'))
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.directory, args.source)
    else: run(args.directory)
