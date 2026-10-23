"""Paired discovery-input diagnostic with every generated candidate evaluated.

Both arms use the same six cached source frames and the same deployment. Only
the discovery input boundary changes. Every candidate is judged against every
original by the existing membership module; nominations never count as support.
This is not a fresh-corpus run, an independent gold evaluation or Agent approval.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import time

from commentscope.factory import framed_clusters as clusters, position_frames as frames
from commentscope.factory import source_bound_discovery as boundary, stance_membership as stance
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.providers import host_resources
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import command, owned_server, file_hash
from experiments.fresh_grounded_pipeline import Runner
from experiments.framed_cluster_controls import synthetic_snapshot, CASES
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.scoped_discovery_probe import code_hashes
from experiments.corpus_resource_guard import host_observation

VERSION = 'paired-source-bound-discovery-0.2'
ARMS = ('frame_views', 'source_bound')
PRIVATE_ROOT = Path('runs')
PREFLIGHT = {'minimum_idle_commit_headroom_bytes': 10*1024**3,
             'minimum_idle_available_mb': 6144}
HOST_ONLY_PREFLIGHT = {'minimum_idle_commit_headroom_bytes': 8*1024**3,
                      'minimum_idle_available_mb': 7168}
ORDER = ['frame_views-proposals', 'source_bound-proposals',
         'frame_views-all-memberships', 'source_bound-all-memberships']


def execution_contract(deployment):
    host_only = deployment.get('runtime', {}).get('memory_profile', {}).get('version') == 'local-memory-profile-0.4'
    if host_only:
        command(deployment, 'baseline')  # Reject mixed device/offload settings.
    return (deepcopy(HOST_ONLY_PREFLIGHT if host_only else PREFLIGHT),
            {'analysis_seconds': None, 'call_seconds': 1800 if host_only else 180, 'retries': 0})


def qualification(source_path, deployment):
    """Bind a completed same-deployment six-call trial, not semantic approval."""
    if deployment['runtime'].get('memory_profile', {}).get('version') != 'local-memory-profile-0.4':
        return []
    directory = source_path.parent
    source = read_json(source_path); done = read_json(directory/'completed.json')
    stopped = read_json(directory/'server/stopped.json'); runtime = read_json(directory/'server/runtime.json')
    if (source['deployment'] != deployment or source['artifact_kind'] != 'local-resource-profile-probe-0.1'
            or done['plan_sha256'] != sha(source_path) or done['completed_calls'] != 6
            or done['call_errors'] != 0 or done['frame_binding_errors'] != []
            or done['resource_stop'] is not False or done['observation_errors'] != 0
            or done['eligible_for_whole_corpus_trial'] is not True or stopped['returncode'] != 0
            or runtime['command'] != command(deployment, 'baseline')):
        raise ValueError('Completed unchanged CPU deployment trial required')
    policy = deployment['runtime']['memory_profile']['host_resource_policy']
    host_resources.validate(policy)
    if (done['minimum_commit_headroom_bytes'] < policy['minimum_commit_headroom_bytes']
            or done['minimum_available_mb'] < policy['minimum_available_mb']
            or done['minimum_disk_free_bytes'] < policy['minimum_disk_free_bytes']):
        raise ValueError('Deployment trial crossed a live resource guard')
    return [directory/'completed.json', directory/'server/stopped.json', directory/'server/runtime.json']


def preflight(directory, plan, *, observe=None):
    """Require measured capacity before loading; do not weaken the live guard."""
    expected, _ = execution_contract(plan.get('deployment', {}))
    if plan['preflight'] != expected:
        raise ValueError('Unknown initial resource admission policy')
    report = {'at': datetime.now(timezone.utc).isoformat(), 'plan_sha256': sha(directory/'plan.json'),
              'new_model_calls': 0, 'quality_gate_passed': False}
    try:
        value = (observe or host_observation)()
        reasons = host_resources.reasons(value, host_resources.POLICY)
        if value['commit_limit']-value['committed_bytes'] < expected['minimum_idle_commit_headroom_bytes']:
            reasons.append('insufficient_idle_commit_for_model_loading')
        if value['available_mb'] < expected['minimum_idle_available_mb']:
            reasons.append('insufficient_idle_ram_for_model_loading')
        report.update(observation=value, reasons=reasons, admitted=not reasons)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        report.update(observation_error=type(exc).__name__, reasons=['resource_observation_failed'], admitted=False)
    sequence = len(list((directory/'preflight').glob('*.json')))+1
    write(directory/'preflight'/f'{sequence:04}.json', report)
    if not report['admitted']:
        raise RuntimeError('Model not started: initial host resource headroom is insufficient')
    return report


def prepare(directory, frame_source, deployment_source, cycle, *,
            discovery_plan=Path('runs/source-bound-discovery-20261014-plan.json'),
            host_plan=Path('runs/source-bound-comparison-host-20261015-plan.json')):
    if directory.exists() or not directory.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('A new private directory is required')
    settings = read_json(cycle)
    if (settings['goal_revision'] != 'factory-goal-20261014-r4'
            or settings['cycle_id'] != 'mvp-factory-20261014'
            or settings['limit_seconds'] is not None or settings['analysis_seconds'] is not None):
        raise ValueError('Current uncapped Factory cycle required')
    original = read_json(frame_source/'plan.json'); finished = read_json(frame_source/'completed.json')
    if (finished['plan_sha256'] != sha(frame_source/'plan.json')
            or finished['completed_calls'] != 6 or finished['call_errors'] or finished['frame_binding_errors']):
        raise ValueError('Six complete bound source frames required')
    paths = [frame_source/'frames'/(sid+'.json') for sid, _, _ in CASES]
    frame_paths = [str(p) for p in paths]
    records = [read_json(p) for p in paths]; snapshot = synthetic_snapshot()
    clusters.assemble_map(snapshot, records, [], [])
    if {r['source']['id'] for r in records} != {sid for sid, _, _ in CASES}:
        raise ValueError('Fixed six-source population changed')
    for record in records:
        row = next((r for r in original['requests'] if r['id'] == record['source']['id']), None)
        if row is None or row['source'] != record['source']:
            raise ValueError('Frame source differs from recorded extraction request')
    source = read_json(deployment_source)
    deployment = deepcopy(source['deployment'])
    admission, limits = execution_contract(deployment)
    qualification_paths = qualification(deployment_source, deployment)
    for item in (deployment['server'], deployment['models']['baseline']):
        if file_hash(item['path']) != item['sha256']: raise ValueError('Existing deployment changed')
    paths += [*qualification_paths, frame_source/'plan.json', frame_source/'completed.json', deployment_source, cycle,
              Path('docs/MVP_GOAL.md'), Path('docs/MVP_PRODUCT_POLICY.md'),
              Path(discovery_plan), Path(host_plan)]
    requests = {'frame_views': clusters.proposal_request(records), 'source_bound': boundary.invocation(records)}
    plan = {'artifact_kind': VERSION, 'arms': list(ARMS), 'records': records, 'frame_paths': frame_paths,
        'snapshot_sha256': digest(snapshot.to_dict()), 'requests': requests,
        'request_sha256': {k:digest(v) for k,v in requests.items()},
        'inputs': {str(p):sha(p) for p in paths}, 'code_sha256': code_hashes(),
        'deployment': deployment, 'budget': {k:settings[k] for k in ('cycle_id','ledger')},
        'limits': limits, 'preflight': admission, 'deployment_source': str(deployment_source),
        'evaluation': {'sources_per_candidate': 6, 'manual_candidate_selection': False,
            'all_counted_supports_require_review': True, 'membership_reference_labels_in_runtime': False,
            'fixed_order': ORDER, 'order_randomized': False,
            'structural_control': 'Shared A/B/C stance, D restriction, E opposition, F different target; review all output contracts.'},
        'cached_frames': True, 'fresh_corpus_analysis': False, 'runtime_reference_labels': False,
        'quality_gate_passed': False, 'resumable': True, 'cross_run_response_reuse': False}
    write(directory/'plan.json', plan)
    print({'prepared': True, 'arms': list(ARMS), 'cached_frame_sources': len(records), 'new_model_calls': 0}, flush=True)


def propose(records, runner, save, arm):
    if arm not in ARMS:
        raise ValueError('Unknown comparison arm')
    req = clusters.proposal_request(records) if arm == 'frame_views' else boundary.invocation(records)
    result = runner.call(arm+'-proposals', req)
    errors = []; candidates = []
    try:
        candidates = clusters.proposals(records, result) if arm == 'frame_views' else boundary.bind(records, result)
    except (ValueError, KeyError, TypeError):
        errors.append({'stage': 'proposal', 'reason': 'proposal_contract_error'})
    row = {'request_sha256': digest(req), 'result': result, 'candidates': candidates, 'errors': errors}
    save(arm+'/proposals', row)
    return row


def compare(snapshot, records, runner, save):
    """No evaluation labels or hand-picked candidate enters this execution API."""
    clusters.assemble_map(snapshot, records, [], [])
    output = {}
    for arm in ARMS:
        proposal = propose(records, runner, save, arm)
        candidates = proposal['candidates']; errors = deepcopy(proposal['errors'])
        memberships = []; scheduled = []
        for candidate in candidates:
            for comment in snapshot.comments:
                sid = comment.comment_id; source = frames.source_packet(snapshot, sid)
                pair = {'candidate_id': candidate['id'], 'source_id': sid}; scheduled.append(pair)
                row = runner.call(arm+'-'+candidate['id']+'-'+sid, stance.invocation(source, candidate))
                try:
                    membership = stance.bind(source, candidate, row)
                    memberships.append(membership)
                    save(arm+'/memberships/'+candidate['id']+'-'+sid, membership)
                except (ValueError, KeyError, TypeError):
                    errors.append({**pair, 'stage': 'membership', 'reason': 'membership_contract_error'})
        mapped = stance.assemble_map(snapshot, records, candidates, memberships)
        counts = {p['id']: p['counts'] for p in mapped['opinion_map']['perspectives']}
        output[arm] = {'candidates': candidates, 'scheduled_pairs': scheduled,
            'memberships': memberships, 'map': mapped, 'errors': errors,
            'candidate_count': len(candidates), 'scheduled_pair_count': len(scheduled),
            'completed_pair_count': len(memberships), 'model_counts': counts,
            'semantic_review_required': True, 'quality_gate_passed': False}
        save(arm+'/output', output[arm])
    return output


def save_unchanged(path, value):
    if path.exists():
        if read_json(path) != value:
            raise ValueError('Same-plan stage artifact changed')
    else:
        write(path, value)


def proposal_checkpoint(directory, plan_hash):
    stage = read_json(directory/'proposals-completed.json')
    rows = {arm:read_json(directory/'artifacts'/arm/'proposals.json') for arm in ARMS}
    if (stage['plan_sha256'] != plan_hash or stage['phase'] != 'proposals'
            or stage['proposals_sha256'] != digest(rows) or stage['membership_judgments'] != 0
            or stage['execution_complete'] is not False or stage['quality_gate_passed'] is not False):
        raise ValueError('Proposal checkpoint changed')
    return stage


def run(directory, *, proposals_only=False):
    if not directory.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Private directory required')
    with experiment_lock(directory):
        if (directory/'started.json').exists() and not (directory/'plan.json').exists():
            raise ValueError('Incomplete experiment cannot be silently retried')
        plan = read_json(directory/'plan.json'); snapshot = synthetic_snapshot()
        admission, limits = execution_contract(plan.get('deployment', {}))
        if (plan['artifact_kind'] != VERSION or plan['arms'] != list(ARMS)
                or plan['snapshot_sha256'] != digest(snapshot.to_dict())
                or plan['limits'] != limits or plan['preflight'] != admission
                or plan['runtime_reference_labels'] is not False or plan['resumable'] is not True
                or plan['cross_run_response_reuse'] is not False or plan['evaluation']['fixed_order'] != ORDER):
            raise ValueError('Comparison population or protocol changed')
        for field in ('inputs','code_sha256'):
            if any(sha(p) != h for p,h in plan[field].items()): raise ValueError('Frozen input/code changed')
        records = plan['records']; clusters.assemble_map(snapshot, records, [], [])
        if (len(records) != 6 or {r['source']['id'] for r in records} != {sid for sid,_,_ in CASES}
                or len(plan['frame_paths']) != 6 or any(p not in plan['inputs'] for p in plan['frame_paths'])
                or records != [read_json(p) for p in plan['frame_paths']]):
            raise ValueError('Cached frame evidence changed')
        requests = {'frame_views': clusters.proposal_request(records), 'source_bound': boundary.invocation(records)}
        if (requests != plan['requests'] or {k:digest(v) for k,v in requests.items()} != plan['request_sha256']):
            raise ValueError('Frozen comparison requests changed')
        for item in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
            if file_hash(item['path']) != item['sha256']: raise ValueError('Deployment changed')
        qualification_paths = qualification(Path(plan['deployment_source']), plan['deployment'])
        if any(str(p) not in plan['inputs'] for p in qualification_paths):
            raise ValueError('Deployment qualification was not frozen')
        plan_hash = sha(directory/'plan.json')
        if (directory/'started.json').exists() and read_json(directory/'started.json')['plan_sha256'] != plan_hash:
            raise ValueError('Started plan changed')
        if (directory/'completed.json').exists():
            report = read_json(directory/'completed.json')
            output = {arm: read_json(directory/'artifacts'/arm/'output.json') for arm in ARMS}
            if report['plan_sha256'] != plan_hash or report['output_sha256'] != digest(output):
                raise ValueError('Completed output changed')
            return report
        if proposals_only and (directory/'proposals-completed.json').exists():
            return proposal_checkpoint(directory, plan_hash)
        preflight(directory, plan)
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        base = Runner(directory, plan, budget); runner = CheckpointRunner(base, plan['deployment']['runtime'])
        started = time.monotonic()
        if not (directory/'started.json').exists():
            write(directory/'started.json', {'pid': os.getpid(), 'at':datetime.now(timezone.utc).isoformat(),
                'plan_sha256':plan_hash, 'budget_before':budget.summary()})
        attempt = len(list((directory/'attempts').glob('*.started.json')))+1
        write(directory/'attempts'/f'{attempt:04}.started.json', {'pid':os.getpid(), 'plan_sha256':plan_hash,
            'at':datetime.now(timezone.utc).isoformat(), 'proposals_only':proposals_only})
        save = lambda name,value:save_unchanged(directory/'artifacts'/(name+'.json'),value)
        try:
            with owned_server(plan['deployment'], 'baseline', directory/'servers'/f'{attempt:04}'):
                proposals = {arm:propose(records,runner,save,arm) for arm in ARMS}
                stage = {'artifact_kind':VERSION, 'plan_sha256':plan_hash, 'phase':'proposals',
                    'arms': {arm:{'candidate_count':len(row['candidates']), 'errors':row['errors']} for arm,row in proposals.items()},
                    'proposals_sha256':digest(proposals), 'membership_judgments':0,
                    'execution_complete':False, 'semantic_review_required':True, 'quality_gate_passed':False}
                save_unchanged(directory/'proposals-completed.json',stage)
                if not proposals_only:
                    output = compare(snapshot, records, runner, save)
            if proposals_only:
                print(stage,flush=True)
                return stage
            report = {'artifact_kind':VERSION, 'plan_sha256':plan_hash, 'execution_complete':True,
                'arms': {arm:{k:output[arm][k] for k in ('candidate_count','scheduled_pair_count','completed_pair_count','errors')} for arm in ARMS},
                'output_sha256':digest(output), 'elapsed_seconds_this_attempt':time.monotonic()-started,
                'same_plan_reused_calls_this_attempt':runner.reused, 'cross_run_response_reuse':False,
                'cached_frames':True, 'fresh_corpus_analysis':False, 'runtime_reference_labels':False,
                'semantic_review_required':True, 'quality_gate_passed':False, 'budget_after':budget.summary()}
            write(directory/'completed.json',report)
            print({k:v for k,v in report.items() if k!='budget_after'},flush=True)
            return report
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json',{'exception_type':type(exc).__name__, 'elapsed_seconds':time.monotonic()-started,
                'plan_sha256':plan_hash, 'budget_after':budget.summary()})
            raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare'); p.add_argument('directory',type=Path)
    p.add_argument('--frames',type=Path,default=Path('runs/resource-compact-probe-20261014'))
    p.add_argument('--deployment',type=Path,required=True)
    p.add_argument('--cycle',type=Path,default=Path('runs/mvp-factory-20261014/cycle.json'))
    p=sub.add_parser('run'); p.add_argument('directory',type=Path)
    p.add_argument('--proposals-only',action='store_true',help='Checkpoint both proposal arms without membership calls or quality approval')
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.directory,args.frames,args.deployment,args.cycle)
    else:run(args.directory,proposals_only=args.proposals_only)
