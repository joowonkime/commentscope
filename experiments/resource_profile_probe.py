"""Six fixed source-frame calls to qualify deployment execution, not quality."""
import argparse
from copy import deepcopy
from pathlib import Path
import time

from commentscope.factory import position_frames as frames
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.generation_limits import allocate
from commentscope.providers.host_resources import POLICY
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import command, file_hash, owned_server
from experiments.framed_cluster_controls import synthetic_snapshot, FIXTURE
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'local-resource-profile-probe-0.1'


def prepare(directory, source_path, cycle_path, *, compact=False, mapped=False, host_only=False):
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('New private experiment directory required')
    source, cycle = read_json(source_path), read_json(cycle_path)
    if (cycle['cycle_id'] != 'mvp-factory-20261014' or cycle['goal_revision'] != 'factory-goal-20261014-r4'
            or cycle['limit_seconds'] is not None or cycle['analysis_seconds'] is not None):
        raise ValueError('Current uncapped cycle required')
    deployment = deepcopy(source['deployment'])
    deployment['runtime']['memory_profile'] = {
        'version': 'local-memory-profile-0.1', 'load_mode': 'dio', 'cache_ram_mib': 0,
        'cache_idle_slots': False, 'host_resource_policy': deepcopy(POLICY)}
    if compact or mapped or host_only:
        deployment['runtime']['memory_profile'].update(
            version='local-memory-profile-0.2', kv_cache={'k': 'q8_0', 'v': 'q8_0'},
            flash_attention='on', batch_size=512, ubatch_size=128)
    if mapped or host_only:
        deployment['runtime']['memory_profile'].update(
            version='local-memory-profile-0.3', load_mode='mmap', host_buffer=False, repack=False)
    if host_only:
        deployment['runtime']['gpu_layers'] = 0
        deployment['runtime']['memory_profile'].update(
            version='local-memory-profile-0.4', device='none', op_offload=False)
    command(deployment, 'baseline')
    for info in (deployment['server'], deployment['models']['baseline']):
        if file_hash(info['path']) != info['sha256']:
            raise ValueError('Existing model/server changed')
    snapshot = synthetic_snapshot()
    requests = []
    for comment in snapshot.comments:
        packet = frames.source_packet(snapshot, comment.comment_id)
        request = allocate(frames.invocation(packet), deployment['runtime'])
        requests.append({'id': comment.comment_id, 'source': packet, 'request': request,
                         'request_sha256': digest(request)})
    plan = {'artifact_kind': VERSION, 'deployment': deployment, 'requests': requests,
            'budget': {k: cycle[k] for k in ('cycle_id', 'ledger')},
            'limits': {'analysis_seconds': None, 'call_seconds': 1800 if host_only else 180},
            'inputs': {str(p): sha(p) for p in (source_path, cycle_path, FIXTURE,
                Path('docs/MVP_GOAL.md'), Path('docs/MVP_PRODUCT_POLICY.md'),
                Path('runs/resource-host-only-20261014-plan.json' if host_only else
                     'runs/resource-mapped-20261014-plan.json' if mapped else
                     'runs/resource-compact-20261014-plan.json' if compact else 'runs/resource-profile-20261014-plan.json'))},
            'code_sha256': code_hashes(), 'runtime_reference_labels': False,
            'criteria': {'calls': 6, 'call_errors': 0, 'frame_binding_errors': 0, 'resource_stop': False},
            'quality_gate_passed': False, 'fresh_corpus_analysis': False}
    write(directory/'plan.json', plan)
    # Interface consumed by the existing full-corpus prepare command. Its use
    # is conditional on a later successful execution trial, never on prepare.
    write(directory/'deployment-source.json', {
        'deployments': {'profile': deployment},
        **{k: deepcopy(source[k]) for k in ('model_files', 'classifier', 'documents', 'selections')},
        'provenance': {'source_plan': str(source_path), 'source_sha256': sha(source_path),
                       'probe_plan_sha256': sha(directory/'plan.json')}})
    print({'prepared': True, 'requests': len(requests), 'new_model_calls': 0}, flush=True)


def run(directory):
    plan = read_json(directory/'plan.json')
    if plan['artifact_kind'] != VERSION or len(plan['requests']) != 6:
        raise ValueError('Unexpected resource probe')
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != h for p, h in plan[field].items()):
            raise ValueError('Frozen input/code changed')
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']:
            raise ValueError('Existing deployment changed')
    if any(digest(r['request']) != r['request_sha256'] for r in plan['requests']):
        raise ValueError('Request changed')
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
    runner = Runner(directory, plan, budget)
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'budget_before': budget.summary()})
    results = []; binding_errors = []
    try:
        with owned_server(plan['deployment'], 'baseline', directory/'server'):
            for row in plan['requests']:
                result = runner.call('frame-'+row['id'], row['request'])
                results.append(result)
                try:
                    write(directory/'frames'/(row['id']+'.json'), frames.bind(row['source'], result))
                except (ValueError, KeyError, TypeError):
                    binding_errors.append(row['id'])
        observations = [read_json(p) for p in sorted((directory/'server/resources').glob('[0-9]*.json'))]
        valid = [r['observation'] for r in observations if 'observation' in r]
        stopped = (directory/'server/resources/stop-requested.json').exists()
        errors = sum(bool(r['errors']) for r in results)
        report = {'artifact_kind': VERSION, 'plan_sha256': runner.plan_sha, 'completed_calls': len(results),
                  'call_errors': errors, 'frame_binding_errors': binding_errors, 'resource_stop': stopped,
                  'eligible_for_whole_corpus_trial': len(results) == 6 and errors == 0 and not binding_errors and not stopped,
                  'minimum_available_mb': min(r['available_mb'] for r in valid),
                  'minimum_commit_headroom_bytes': min(r['commit_limit']-r['committed_bytes'] for r in valid),
                  'minimum_disk_free_bytes': min(r['disk_free_bytes'] for r in valid),
                  'maximum_observed_commit_percent': max(r['commit_percent'] for r in valid),
                  'observation_errors': sum('observation_error' in r for r in observations),
                  'elapsed_seconds': time.monotonic()-runner.started,
                  'quality_gate_passed': False, 'fresh_corpus_analysis': False, 'budget_after': budget.summary()}
        write(directory/'completed.json', report)
        print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type': type(exc).__name__, 'budget_after': budget.summary()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--source', type=Path, default=Path('runs/framed-corpus-20261014/plan.json'))
    p.add_argument('--cycle', type=Path, default=Path('runs/mvp-factory-20261014/cycle.json'))
    p.add_argument('--compact', action='store_true', help='Explicitly test quantized KV and smaller compute buffers')
    p.add_argument('--mapped', action='store_true', help='Explicitly test compact mmap without host-pinned buffers or CPU repacking')
    p.add_argument('--host-only', action='store_true', help='Explicitly disable device/operation offloading and test CPU mmap with finite1800second calls')
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.directory, args.source, args.cycle, compact=args.compact, mapped=args.mapped, host_only=args.host_only)
    else: run(args.directory)
