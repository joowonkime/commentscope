"""Fixed six-control/24-original pilot using the existing sequential runner.

Preparation freezes inputs, not quality. Run each arm explicitly; no automatic
whole-corpus launch, response repair or extra model download is provided here.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import time

from commentscope.factory import batched_corpus as corpus, batch_stances
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.file_integrity import file_sha256
from commentscope.ingestion import load_snapshot
from commentscope.providers import framed_embedding
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments import sequential_corpus_pipeline as sequential
from experiments.framed_cluster_controls import synthetic_snapshot
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'batched-cluster-fixed-pilot-0.1'
BASE_PLAN = Path('runs/framed-corpus-sequential-20261015/plan.json')
CRITERIA = {'control_shared_abc_required': True, 'control_conditional_d_not_counted': True,
            'control_opposed_e_and_unrelated_f_not_counted': True,
            'all_generated_candidates_reviewed': True, 'all_counted_supports_reviewed': True,
            'observed_false_counted_supports': 0, 'observed_essential_condition_loss': 0,
            'source_omissions_reported': True, 'timing_and_call_volume_reported': True,
            'assistant_review_is_independent_gold': False, 'pilot_proves_corpus_utilization': False}


def select_ids(snapshot, arm):
    ids = list(corpus.sources(snapshot))
    if arm == 'controls':
        if set(ids) != set('ABCDEF'): raise ValueError('Fixed six-control population required')
        return sorted(ids)
    if arm != 'real' or len(ids) < 24: raise ValueError('Fixed 24-original pilot population required')
    return sorted(ids, key=lambda sid: (hashlib.sha256(sid.encode('utf-8')).hexdigest(), sid))[:24]


def embedding_files(base):
    marker = 'models--' + framed_embedding.MODEL.replace('/', '--') + '/snapshots/' + framed_embedding.REVISION + '/'
    result = {p: h for p, h in base['model_files'].items() if marker in p}
    if not result or not any(p.endswith('/model.safetensors') for p in result):
        raise ValueError('Existing pinned embedding model required')
    return result


def prepare(directory, arm, base_path=BASE_PLAN):
    sequential.private(directory)
    if directory.exists(): raise ValueError('Never overwrite a pilot plan')
    base = read_json(base_path)
    settings = read_json(base['cycle']); sequential.cycle_check(settings)
    sequential.deployment_check(base['deployment'])
    qualification = sequential.qualification(Path(base['deployment_source']), base['deployment'])
    if arm == 'controls':
        snapshot = synthetic_snapshot(); snapshot_path = directory/'snapshot.json'
    else:
        snapshot_path = Path(base['snapshot']); snapshot = load_snapshot(snapshot_path).snapshot
    selected = select_ids(snapshot, arm); live(snapshot.usage.expires_at)
    original = corpus.sources(snapshot)
    if arm == 'controls': write(snapshot_path, snapshot.to_dict())
    paths = [base_path, snapshot_path, Path(base['cycle']), Path(base['deployment_source']),
             Path('docs/MVP_GOAL.md'), Path('docs/MVP_PRODUCT_POLICY.md'), Path('docs/MVP_EXECUTION_SPEC.md'),
             *qualification]
    plan = {'artifact_kind': VERSION, 'goal_revision': settings['goal_revision'], 'arm': arm,
        'base_plan': str(base_path), 'snapshot': str(snapshot_path), 'snapshot_file_sha256': sha(snapshot_path),
        'expires_at': snapshot.usage.expires_at, 'cycle': base['cycle'],
        'deployment_source': base['deployment_source'], 'deployment': deepcopy(base['deployment']),
        'model_files': embedding_files(base), 'budget': {k: settings[k] for k in ('cycle_id', 'ledger')},
        'limits': deepcopy(sequential.LIMITS), 'preflight': deepcopy(sequential.HOST_ONLY_PREFLIGHT),
        'model_lifetime': deepcopy(sequential.LIFETIME), 'retrieval': deepcopy(corpus.RETRIEVAL),
        'inputs': {str(p): sha(p) for p in paths}, 'code_sha256': code_hashes(),
        'sample': {'source_ids': selected, 'source_sha256': {sid: digest(original[sid]) for sid in selected},
                   'canonical_population': len(original), 'parent_context': 'complete_snapshot_not_subset',
                   'selection': 'all_six_controls' if arm == 'controls' else 'first24_sorted_sha256_utf8_canonical_id'},
        'review_criteria': deepcopy(CRITERIA), 'cross_run_response_reuse': False,
        'runtime_reference_labels': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    return plan


def validate(plan, *, models=False):
    if (plan['artifact_kind'] != VERSION or plan['review_criteria'] != CRITERIA
            or plan['limits'] != sequential.LIMITS or plan['preflight'] != sequential.HOST_ONLY_PREFLIGHT
            or plan['model_lifetime'] != sequential.LIFETIME or plan['retrieval'] != corpus.RETRIEVAL
            or plan['cross_run_response_reuse'] is not False or plan['runtime_reference_labels'] is not False
            or plan['quality_gate_passed'] is not False):
        raise ValueError('Pilot execution contract changed')
    settings = read_json(plan['cycle']); sequential.cycle_check(settings)
    if (plan['budget'] != {k: settings[k] for k in ('cycle_id', 'ledger')}
            or plan['goal_revision'] != settings['goal_revision']):
        raise ValueError('Current ledger binding changed')
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen pilot input/code changed')
    base = read_json(plan['base_plan'])
    if plan['deployment'] != base['deployment'] or plan['model_files'] != embedding_files(base):
        raise ValueError('Existing model binding changed')
    sequential.deployment_check(plan['deployment'])
    sequential.qualification(Path(plan['deployment_source']), plan['deployment'])
    loaded = load_snapshot(Path(plan['snapshot'])); snapshot = loaded.snapshot
    live(snapshot.usage.expires_at)
    selected = select_ids(snapshot, plan['arm']); originals = corpus.sources(snapshot)
    if (loaded.sha256 != plan['snapshot_file_sha256'] or plan['expires_at'] != snapshot.usage.expires_at
            or plan['sample'] != {'source_ids': selected, 'source_sha256': {sid: digest(originals[sid]) for sid in selected},
                'canonical_population': len(originals), 'parent_context': 'complete_snapshot_not_subset',
                'selection': 'all_six_controls' if plan['arm'] == 'controls' else 'first24_sorted_sha256_utf8_canonical_id'}):
        raise ValueError('Fixed pilot population/context changed')
    if plan['arm'] == 'controls' and snapshot.to_dict() != synthetic_snapshot().to_dict():
        raise ValueError('Authored control inputs changed')
    if models:
        files = {**plan['model_files']}
        for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']): files[info['path']] = info['sha256']
        if any(file_sha256(p) != h for p, h in files.items()): raise ValueError('Local model/server files changed')
    return snapshot


def run(directory):
    sequential.private(directory)
    with sequential.experiment_lock(directory):
        plan = read_json(directory/'plan.json'); snapshot = validate(plan); plan_hash = sha(directory/'plan.json')
        if (directory/'completed.json').exists():
            report = read_json(directory/'completed.json'); output = read_json(directory/'artifacts/output.json')
            if report['plan_sha256'] != plan_hash or report['output_sha256'] != digest(output):
                raise ValueError('Completed pilot changed')
            if batch_stances.assemble_map(snapshot, output['discoveries'], output['candidates'], output['membership_batches']) != output['map']:
                raise ValueError('Completed map changed')
            return report
        # Refuse insufficient resources before reading large weights or opening
        # the usage ledger. Model lifetimes re-check before each actual load.
        sequential.preflight(directory, plan)
        validate(plan, models=True)
        started = time.monotonic(); at = datetime.now(timezone.utc).isoformat()
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        attempt = len(list((directory/'attempts').glob('*.started.json'))) + 1
        if not (directory/'started.json').exists():
            write(directory/'started.json', {'plan_sha256': plan_hash, 'started_at': at, 'budget_before': budget.summary()})
        origin = read_json(directory/'started.json')
        if origin['plan_sha256'] != plan_hash: raise ValueError('Same-plan resume required')
        write(directory/'attempts'/f'{attempt:04}.started.json', {'pid': os.getpid(), 'plan_sha256': plan_hash,
                                                               'started_at': at, 'same_plan_resume': attempt > 1})

        def save(name, value):
            path = directory/'artifacts'/(name + '.json')
            if path.exists():
                if read_json(path) != value: raise ValueError('Same-plan stage output changed')
            else: write(path, value)

        try:
            with sequential.lifetimes(directory, plan, attempt) as models:
                base = Runner(directory, plan, budget); base.started = started
                wrapped = sequential.SequentialRunner(base, models, directory/'transitions'/f'{attempt:04}')
                runner = CheckpointRunner(wrapped, plan['deployment']['runtime'])

                def embed(stage, texts):
                    path = directory/'embeddings'/(stage + '.json')
                    req = {'system': framed_embedding.VERSION, 'data': {'texts': texts, 'output': str(path)},
                           'schema': {}, 'max_tokens': 1}
                    result = runner.call('embed-' + stage, req, provider=framed_embedding.generate,
                                         maximum=plan['limits']['embedding_seconds'])
                    if (result['output'] != str(path) or sha(path) != result['sha256']
                            or result['texts_sha256'] != digest(texts)):
                        raise ValueError('Embedding artifact changed')
                    artifact = read_json(path)
                    if (artifact['texts_sha256'] != digest(texts) or artifact['model'] != result['model']
                            or artifact['revision'] != result['revision'] or artifact['model'] != framed_embedding.MODEL
                            or artifact['revision'] != framed_embedding.REVISION or artifact['local_files_only'] is not True):
                        raise ValueError('Embedding input/model changed')
                    return artifact['vectors']

                output = corpus.process(snapshot, runner, embed, save=save, limits=plan['retrieval'],
                                        source_ids=plan['sample']['source_ids'])
                save('output', output)
            report = {'artifact_kind': VERSION, 'plan_sha256': plan_hash, 'execution_complete': True,
                'arm': plan['arm'], 'scheduled_originals': len(plan['sample']['source_ids']),
                'canonical_population': plan['sample']['canonical_population'], 'discovered_candidates': len(output['candidates']),
                'membership_judgments': len(output['map']['memberships']), 'errors': output['errors'],
                'attempt_seconds': time.monotonic()-started, 'same_plan_reused_calls_this_attempt': runner.reused,
                'model_lifetime': {'server_starts': models.server_starts, 'server_stops': models.server_stops,
                                   'auxiliary_calls': models.auxiliary_calls},
                'output_sha256': digest(output), 'semantic_review_required': True, 'quality_gate_passed': False,
                'correct_comment_utilization': None, 'agent_generation_state': 'not_in_pilot', 'budget_after': budget.summary()}
            write(directory/'completed.json', report)
            print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True)
            return report
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json', {'exception_type': type(exc).__name__,
                  'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary()})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--arm', choices=('controls', 'real'), required=True); p.add_argument('--base-plan', type=Path, default=BASE_PLAN)
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        plan = prepare(args.directory, args.arm, args.base_plan)
        print({'prepared': True, 'arm': plan['arm'], 'originals': len(plan['sample']['source_ids']), 'new_model_calls': 0})
    else: run(args.directory)
