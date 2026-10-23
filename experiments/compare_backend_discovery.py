"""Frozen proposal-only pass over the backend's complete development scope.

No evaluation labels, semantic approval, manual candidate choice or full Factory
rerun. Existing GPU deployment, ledger, exact checkpoints and resource guards
are reused. Oversized original groups are split by the actual model template.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from commentscope.factory import shared_claims
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.framed_corpus import sources
from commentscope.ingestion import load_snapshot
from commentscope.providers import context_capacity, framed_embedding, host_resources
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import file_hash
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.fresh_grounded_pipeline import Runner
from experiments.minimal_factory_pipeline import deployment_check, lifetimes
from experiments.model_selection_20261016 import observe
from experiments.scoped_discovery_probe import code_hashes
from experiments.sequential_corpus_pipeline import SequentialRunner

VERSION = 'compare-backend-discovery-20261023-v1'
SCOPE = Path('runs/minimal-factory-r5-g3-20261018-v1/plan.json')
EMBEDDINGS = SCOPE.parent/'artifacts/embedding-sources.json'
ACCEPTANCE = Path('runs/compare-backend-20261023-v1/acceptance-profile.json')
QUOTA = Path('runs/factory-r5-20261017-v1/account_quota_guard.py')


class QuotaThresholdReached(RuntimeError): pass
class QuotaMetadataUnavailable(RuntimeError): pass


def check_quota(*, wait_for_fresh=True):
    while True:
        try:
            result = subprocess.run([sys.executable, str(QUOTA), 'check'],
                                    capture_output=True, text=True, timeout=10)
            state=json.loads(result.stdout)
            if not isinstance(state,dict):raise ValueError('Invalid quota observation')
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
            if not wait_for_fresh:raise QuotaMetadataUnavailable(str(exc)) from exc
            time.sleep(5);continue
        if result.returncode==2 or state.get('threshold_latched'):
            raise QuotaThresholdReached('Quota stop threshold reached: '+result.stdout.strip())
        if result.returncode==0:return
        if not wait_for_fresh:
            raise QuotaMetadataUnavailable('Quota metadata unavailable: '+result.stdout.strip())
        # A complete in-flight response may be durably recorded; no new task or
        # semantic binding starts until a fresh above-threshold observation.
        time.sleep(5)


@contextmanager
def quota_watch(*, poll_seconds=15):
    check_quota()
    stop = threading.Event()

    def monitor():
        while not stop.wait(poll_seconds):
            try:
                check_quota(wait_for_fresh=False)
            except QuotaMetadataUnavailable:
                continue
            except QuotaThresholdReached:
                if not stop.is_set():
                    os.kill(os.getpid(), signal.SIGINT)
                return
    thread = threading.Thread(target=monitor, daemon=True, name='backend-quota-guard')
    thread.start()
    try:
        yield
    finally:
        stop.set(); thread.join(timeout=12)
        if thread.is_alive():
            raise RuntimeError('Quota observer shutdown unconfirmed')


def input_groups(plan):
    snapshot = load_snapshot(Path(plan['snapshot'])).snapshot
    registry = sources(snapshot, include_video_context=True)
    originals = [registry[sid] for sid in plan['scope_ids']]
    artifact = read_json(EMBEDDINGS)
    if (artifact['texts_sha256'] != digest({s['id']: s['text'] for s in originals})
            or artifact['model'] != framed_embedding.MODEL
            or artifact['revision'] != framed_embedding.REVISION
            or artifact['local_files_only'] is not True):
        raise ValueError('Exact source embedding provenance required')
    groups = shared_claims.batches(originals, artifact['vectors'])
    if [[s['id'] for s in group] for group in groups] != plan['groups']:
        raise ValueError('Source grouping changed')
    return groups


def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('New private run required')
    previous = read_json(SCOPE); deployment_check(previous['deployment'])
    snapshot = load_snapshot(Path(previous['snapshot'])).snapshot
    registry = sources(snapshot, include_video_context=True)
    originals = [registry[sid] for sid in previous['scope_ids']]
    # Reuse only exact embedding data. Prior memberships, labels and generated
    # candidates are deliberately absent from the proposal requests.
    groups = shared_claims.batches(originals, read_json(EMBEDDINGS)['vectors'])
    paths = [SCOPE, EMBEDDINGS, ACCEPTANCE, Path(previous['snapshot']), QUOTA,
             Path('runs/compare-backend-20261023-v1/M1-adapter-plan.json'),
             Path('runs/compare-backend-20261023-v1/M1-discovery-v1-review.json'),
             Path('runs/compare-backend-20261023-v1/M1-repair-v2-plan.json'),
             Path('runs/compare-backend-20261023-v1/M1-repair-v2-result.json')]
    contract = shared_claims.COMMON
    plan = {'artifact_kind': VERSION, 'proposal_contract': contract,
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'hypothesis': 'Automatically proposed bare common stances can reach multiple original supporters while separable personal reasons remain source-owned.',
        'decision': 'Only >=2-author intersections; empty is valid and all unshared originals stay in the inventory. Review all proposed intersections before membership. Do not rerun the failed v1 singleton enumeration.',
        'prior_failure_boundary': 'No generated frame condition fields and no legacy frame-fidelity support gate; nominations have no semantic approval.',
        'snapshot': previous['snapshot'], 'scope_ids': previous['scope_ids'],
        'groups': [[s['id'] for s in group] for group in groups],
        'logical_request_sha256': [digest(shared_claims.request(g,version=contract)) for g in groups],
        'inputs': {str(p): sha(p) for p in paths}, 'code_sha256': code_hashes(),
        'deployment': previous['deployment'], 'resource_policy': host_resources.POLICY,
        'budget': previous['budget'], 'limits': previous['limits'],
        'expected_calls': {'before_template_splitting': len(groups),
                           'maximum_after_splitting': len(originals),
                           'answer_reservation_per_call': 1024,
                           'estimated_prompt_tokens': [30000, 40000],
                           'estimate_basis': 'Same96 originals used37864 prompt tokens in v1; smaller output reservation and common-only schema may reduce splitting.',
                           'actual_template_measurement_required': True},
        'evaluation': {'whole_frozen_scope': True, 'review_every_proposal': True,
                       'nominees_are_support': False, 'manual_candidate_selection': False,
                       'actual_agents_after_proposals_only': 0},
        'quality_gate_passed': False}
    input_groups(plan)
    write(directory/'plan.json', plan)
    return plan


def run(directory):
    check_quota()
    with experiment_lock(directory), quota_watch():
        plan = read_json(directory/'plan.json'); plan_hash = sha(directory/'plan.json')
        if plan['artifact_kind'] != VERSION:
            raise ValueError('Wrong proposal contract')
        for path, expected in {**plan['inputs'], **plan['code_sha256']}.items():
            if sha(path) != expected:
                raise ValueError('Frozen input/code changed: '+path)
        deployment_check(plan['deployment'])
        for item in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
            if file_hash(item['path']) != item['sha256']:
                raise ValueError('Existing model/server changed')
        groups = input_groups(plan)
        contract = plan.get('proposal_contract',shared_claims.VERSION)
        if [digest(shared_claims.request(g,version=contract)) for g in groups] != plan['logical_request_sha256']:
            raise ValueError('Frozen logical requests changed')
        if (directory/'completed.json').exists():
            done = read_json(directory/'completed.json')
            if done['plan_sha256'] != plan_hash or done['output_sha256'] != sha(directory/'artifacts/output.json'):
                raise ValueError('Completed proposal output changed')
            return done
        pending = [p for p in (directory/'checkpoints').glob('*.intent.json')
                   if not p.with_name(p.name.replace('.intent.json', '.result.json')).exists()]
        if pending:
            raise RuntimeError('Pending requests need process/ledger reconciliation')
        attempt = len(list((directory/'attempts').glob('*.started.json')))+1
        observed = observe(); write(directory/'preflight'/f'{attempt:04}.json', observed)
        if observed['refusal_reasons']:
            raise RuntimeError('Existing resource preflight refused startup')
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        write(directory/'attempts'/f'{attempt:04}.started.json',
              {'pid': os.getpid(), 'plan_sha256': plan_hash, 'budget_before': budget.summary()})
        started = time.monotonic()

        def save(name, value):
            path = directory/'artifacts'/(name+'.json')
            if path.exists():
                if read_json(path) != value:
                    raise ValueError('Same-plan artifact changed: '+name)
            else:
                write(path, value)
        try:
            with lifetimes(directory, plan, attempt) as models:
                sequential = SequentialRunner(Runner(directory, plan, budget), models,
                                              directory/'transitions'/f'{attempt:04}')
                checkpoint = CheckpointRunner(sequential, plan['deployment']['runtime'])
                records = []; holds = []; errors = []
                for group in groups:
                    check_quota()
                    fitted, deferred = context_capacity.partition(group,
                        lambda rows:shared_claims.request(rows,version=contract),
                        lambda req: models.invoke('llm', lambda: context_capacity.measure(req)),
                        minimum=2 if contract==shared_claims.COMMON else 1)
                    holds.extend(deferred)
                    for task in fitted:
                        check_quota()
                        req = task['request']; key = digest(req)[:24]
                        save('capacity/'+key, task['capacity'])
                        result = checkpoint.call('shared-proposal-'+key, req)
                        check_quota()
                        try:
                            record = shared_claims.bind(task['items'], result,version=contract)
                        except (ValueError, KeyError, TypeError) as exc:
                            errors.append({'request_sha256': digest(req), 'error': str(exc),
                                           'source_ids': [s['id'] for s in task['items']]})
                            save('errors/'+key, {'result': result, 'error': errors[-1]})
                            if result.get('raw') is None and result.get('errors'):
                                raise RuntimeError('No completed response; do not retry')
                            continue
                        save('proposals/'+key, record); records.append(record)
                output = {'records': records, 'candidates': shared_claims.candidates(records),
                          'capacity_holds': holds, 'errors': errors, 'actual_agents': 0,
                          'semantic_approval': False, 'quality_gate_passed': False}
                save('output', output)
            report = {'artifact_kind': VERSION, 'plan_sha256': plan_hash,
                      'output_sha256': sha(directory/'artifacts/output.json'),
                      'completed_proposal_calls': len(records), 'candidates': len(output['candidates']),
                      'processed_source_ids': sorted({s['id'] for r in records for s in r['sources']}),
                      'errors': errors, 'capacity_holds': holds, 'actual_agents': 0,
                      'elapsed_seconds': time.monotonic()-started, 'same_plan_reused_calls': checkpoint.reused,
                      'budget_after': budget.summary(), 'quality_gate_passed': False}
            write(directory/'completed.json', report)
            return report
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json',
                  {'exception': type(exc).__name__, 'elapsed_seconds': time.monotonic()-started,
                   'budget_after': budget.summary()})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = prepare(args.directory) if args.action == 'prepare' else run(args.directory)
    print({k: result[k] for k in ('artifact_kind', 'quality_gate_passed')}, flush=True)
