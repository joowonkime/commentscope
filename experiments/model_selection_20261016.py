"""Bounded 8B runtime qualification and paired thinking-mode diagnostic.

This does not adopt the draft batch architecture or run the corpus pipeline.
Existing source contracts are benchmark workloads, not approved product outputs.
No downloads, prompt repairs, automatic fallback, or experiment retries.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import subprocess
import time

from commentscope.factory import batch_stances as batch, position_frames as frames
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.factory.framed_corpus import sources
from commentscope.ingestion import load_snapshot
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.generation_limits import allocate
from commentscope.providers.host_resources import reasons, POLICY
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash, command
from experiments.batched_cluster_pilot import select_ids
from experiments.corpus_resource_guard import host_observation
from experiments.framed_cluster_controls import synthetic_snapshot, TARGET
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'model-selection-20261016-0.1'
BASE = Path('runs/framed-corpus-sequential-20261015/plan.json')
# This is a new full-GPU deployment probe, not a relaxation of the CPU plan.
# Live guards are unchanged. Idle limits are engineering probe prerequisites,
# not a claim that these amounts guarantee stability for the full corpus.
PREFLIGHT = {'available_mb': 4096, 'commit_headroom_bytes': 8*1024**3,
             'gpu_free_mib': 6400, 'disk_free_bytes': 6*1024**3}
TRANSFER = [
    ('G', 'Some people say "Safety reviews should be mandatory." I disagree: they should remain voluntary.', False),
    ('H', 'Safety reviews would be expensive. I have not decided whether to support making them mandatory.', False),
    ('I', 'I support mandatory safety reviews even though they may be expensive.', True),
    ('J', '안전성 검토는 의무화해야 합니다. 공공의 안전이 중요하기 때문입니다.', True),
    ('K', '소규모 연구실에 수수료를 면제해 줄 때만 안전성 검토 의무화에 찬성합니다.', False),
    ('L', '안전성 검토는 의무화하지 말고 자율에 맡겨야 합니다.', False),
]


def deployment(base, mode):
    if mode not in ('off', 'on'): raise ValueError('Fixed off/on comparison only')
    result = deepcopy(base)
    runtime = result['runtime']
    runtime.update(context=8192, gpu_layers=99, reasoning=mode,
                   reasoning_budget=0 if mode == 'off' else 1024,
                   template_kwargs={'enable_thinking': mode == 'on'})
    profile = runtime['memory_profile']
    profile.update(version='local-memory-profile-0.2', load_mode='dio')
    for key in ('host_buffer', 'repack', 'device', 'op_offload'): profile.pop(key, None)
    command(result, 'baseline')  # Reuse strict existing deployment validation.
    return result


def fixed_candidate():
    # Authored fixed target for classification only, NEVER an automatic discovery.
    source = {'id': 'fixture', 'text': TARGET['statement'], 'parent': None}
    return {'id': 'BP'+digest(TARGET)[:24], 'contract': deepcopy(TARGET),
            'nominee_source_ids': ['fixture'], 'source_sha256': {'fixture': digest(source)},
            'discovery_refs': [digest({'authored_benchmark_target': TARGET})], 'semantic_approval': False}


def workloads(snapshot):
    controls = list(sources(synthetic_snapshot()).values())
    transfer = [{'id': sid, 'text': text, 'parent': None} for sid, text, _ in TRANSFER]
    registry = sources(snapshot)
    real = [registry[sid] for sid in select_ids(snapshot, 'real')[:8]]
    candidate = fixed_candidate()
    tasks = []
    for name, items in [('controls-membership', controls), ('transfer-membership', transfer)]:
        pairs = [{'source_id': s['id'], 'candidate_id': candidate['id']} for s in items]
        tasks.append({'name': name, 'kind': 'membership', 'sources': items,
                      'candidates': [candidate], 'pairs': pairs,
                      'request': batch.membership_request(items, [candidate], pairs)})
    for name, items in [('controls-discovery', controls), ('real8-discovery', real)]:
        tasks.append({'name': name, 'kind': 'discovery', 'sources': items,
                      'request': batch.discovery_request(items)})
    for source in controls:
        if source['id'] in ('A', 'B', 'D'):
            tasks.append({'name': 'frame-'+source['id'], 'kind': 'frame', 'sources': [source],
                          'request': frames.invocation(source)})
    return tasks


def preflight_reasons(host, gpu):
    result = reasons(host, POLICY)
    if host['available_mb'] < PREFLIGHT['available_mb']: result.append('idle_ram')
    if host['commit_limit']-host['committed_bytes'] < PREFLIGHT['commit_headroom_bytes']: result.append('idle_commit')
    if gpu < PREFLIGHT['gpu_free_mib']: result.append('idle_gpu')
    return result


def observe():
    host = host_observation()
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                         capture_output=True, text=True, check=True, timeout=15)
    lines = gpu.stdout.strip().splitlines()
    if len(lines) != 1: raise ValueError('Exactly one observed GPU required')
    free = int(lines[0])
    return {'host': host, 'gpu_free_mib': free, 'refusal_reasons': preflight_reasons(host, free)}


def prepare(directory):
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('New private run directory required')
    base = read_json(BASE)
    cycle = read_json(base['cycle'])
    if cycle['limit_seconds'] is not None or cycle['analysis_seconds'] is not None:
        raise ValueError('Existing uncapped ledger required')
    snapshot = load_snapshot(Path(base['snapshot'])).snapshot
    live(snapshot.usage.expires_at)
    tasks = workloads(snapshot)
    design = {'artifact_kind': VERSION, 'model_comparison': 'same8B_off_vs_on1024',
              'task_sha256': digest(tasks), 'tasks_per_arm': 7,
              'order': ['off', 'on'], 'retries': 0, 'repairs': 0,
              'scope': 'runtime qualification then component comparison, no corpus or agent approval',
              'selection_rule': 'Operational success first. Review ALL discovery candidates and A/B/D frames. '
                  'Report support preservation, false supports, conditions/authorship/reasons, errors and cost separately. '
                  'Prefer off for development unless on has better fidelity without extra false supports or omissions. '
                  'Unresolved material errors mean no quality-qualified selection; never declare MVP success.',
              'reference': {'controls_support': ['A', 'B', 'C'], 'controls_not_support': ['D', 'E', 'F'],
                            'transfer_support': [sid for sid, _, yes in TRANSFER if yes],
                            'transfer_not_support': [sid for sid, _, yes in TRANSFER if not yes],
                            'shared_abc_required': True, 'D_essential_fee_waiver_required': True,
                            'individual_A_B_reasons_not_common_essential_conditions': True,
                            'real_discovery': 'review every candidate against whole source and parent; not independent gold'},
              'runtime_reference_labels': False, 'new_downloads': False,
              'preflight': PREFLIGHT, 'live_resource_policy': POLICY}
    write(directory/'design.json', design)
    hashes = code_hashes()
    for mode in ('off', 'on'):
        plan = {'artifact_kind': VERSION, 'mode': mode, 'deployment': deployment(base['deployment'], mode),
                'budget': deepcopy(base['budget']), 'limits': {'analysis_seconds': None, 'call_seconds': 600},
                'tasks': tasks, 'design_path': str(directory/'design.json'), 'design_sha256': sha(directory/'design.json'),
                'code_sha256': hashes, 'inputs': {str(p): sha(p) for p in
                    (BASE, Path(base['cycle']), Path(base['snapshot']))},
                'expires_at': snapshot.usage.expires_at, 'preflight': PREFLIGHT}
        write(directory/mode/'plan.json', plan)
    print({'prepared': str(directory), 'new_model_calls': 0, 'tasks_per_arm': 7}, flush=True)


def bind(task, result):
    if task['kind'] == 'membership':
        return batch.bind_membership(task['sources'], task['candidates'], task['pairs'], result)
    if task['kind'] == 'discovery': return batch.bind_discovery(task['sources'], result)
    return frames.bind(task['sources'][0], result)


def run(directory):
    if not directory.resolve().is_relative_to(Path('runs').resolve()): raise ValueError('Private run required')
    plan = read_json(directory/'plan.json')
    if plan['artifact_kind'] != VERSION or plan['preflight'] != PREFLIGHT: raise ValueError('Wrong plan')
    if (directory/'started.json').exists() or (directory/'preflight.json').exists():
        raise ValueError('No automatic retry or overwrite')
    for section in ('code_sha256', 'inputs'):
        if any(sha(p) != h for p, h in plan[section].items()): raise ValueError('Frozen input/code changed')
    if sha(plan['design_path']) != plan['design_sha256']: raise ValueError('Design changed')
    design = read_json(plan['design_path'])
    if digest(plan['tasks']) != design['task_sha256'] or len(plan['tasks']) != 7: raise ValueError('Workloads changed')
    live(plan['expires_at'])
    observation = observe(); write(directory/'preflight.json', observation)
    if observation['refusal_reasons']:
        print({'not_started': observation}, flush=True)
        return
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Model/runtime changed')
    observation = observe(); write(directory/'after-hash-preflight.json', observation)
    if observation['refusal_reasons']:
        print({'not_started_after_hash': observation}, flush=True)
        return
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
    runner = Runner(directory, plan, budget); started = time.monotonic()
    write(directory/'started.json', {'plan_sha256': sha(directory/'plan.json'), 'budget_before': budget.summary()})
    errors = []; completed = 0
    try:
        with owned_server(plan['deployment'], 'baseline', directory/'server'):
            for task in plan['tasks']:
                request = allocate(task['request'], plan['deployment']['runtime'])
                result = runner.call(task['name'], request)
                completed += 1
                if completed == 1:
                    write(directory/'first-request.json', {'response_received': result.get('raw') is not None,
                          'errors': result.get('errors'), 'elapsed_seconds': time.monotonic()-started,
                          'semantic_quality_approved': False})
                if result.get('raw') is None:
                    raise RuntimeError('No response; stop rather than repeat expensive failures')
                try:
                    bound = bind(task, result)
                    write(directory/'bound'/(task['name']+'.json'), bound)
                except (ValueError, KeyError, TypeError) as exc:
                    errors.append({'task': task['name'], 'error': str(exc)})
        write(directory/'completed.json', {'completed_calls': completed, 'binding_errors': errors,
              'elapsed_seconds': time.monotonic()-started, 'semantic_quality': 'requires_offline_review',
              'mvp_approved': False, 'budget_after': budget.summary()})
    except BaseException as exc:
        write(directory/'failed.json', {'completed_calls': completed, 'binding_errors': errors,
              'elapsed_seconds': time.monotonic()-started, 'error_type': type(exc).__name__,
              'error': str(exc), 'mvp_approved': False, 'budget_after': budget.summary()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    (prepare if args.action == 'prepare' else run)(args.directory)
