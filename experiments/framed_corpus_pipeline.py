"""Private, frozen whole-snapshot Factory execution with same-plan checkpoints.

The full meaningful-comment reference is validated before any corpus output but
never passed into runtime scheduling or requests. Completion here is execution,
not utilization/Agent quality approval; output review remains required.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
try:
    import fcntl
except ImportError:
    fcntl = None
    import msvcrt
import os
from pathlib import Path
import time

from commentscope.factory import framed_corpus as corpus, comment_utilization as utilization
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.ingestion import load_snapshot
from commentscope.providers import framed_embedding, evidence_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash
from experiments.fresh_grounded_pipeline import Runner
from experiments.framed_agent_probe import runtime_probe, QUESTIONS
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'frozen-whole-framed-corpus-pipeline-0.1'
PRIVATE_ROOT = Path('runs')


def reference_check(snapshot, reference, expected):
    utilization._validate_reference(snapshot, reference, expected)
    if reference['scope'] != 'full_corpus' or any(r['eligibility'] == 'uncertain' for r in reference['rows']):
        raise ValueError('Complete pre-output meaningful reference required; never drop unresolved sources')


def prepare(directory, snapshot_path, reference_path, deployment_source, cycle):
    if directory.exists(): raise ValueError('Never overwrite a pipeline plan')
    if not directory.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Research outputs must remain in the private runs tree')
    loaded = load_snapshot(snapshot_path); snapshot = loaded.snapshot
    corpus.sources(snapshot); live(snapshot.usage.expires_at)
    reference = read_json(reference_path); reference_hash = digest(reference)
    reference_check(snapshot, reference, reference_hash)
    settings = read_json(cycle)
    if (settings['goal_revision'] != 'factory-goal-20261014-r4' or settings['cycle_id'] != 'mvp-factory-20261014'
            or settings['limit_seconds'] is not None or settings['analysis_seconds'] is not None):
        raise ValueError('Current uncapped Factory cycle required')
    source = read_json(deployment_source); deployment = deepcopy(source['deployments']['profile'])
    deployment['runtime']['max_seconds_per_model'] = None
    for info in (deployment['server'], deployment['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Existing deployment changed')
    if any(sha(p) != h for p, h in source['model_files'].items()): raise ValueError('Existing embedding/NLI files changed')
    for doc in source['documents']: live(doc['expires_at'])
    paths = [snapshot_path, reference_path, deployment_source, cycle, Path('docs/MVP_GOAL.md'), Path('docs/MVP_PRODUCT_POLICY.md')]
    plan = {'artifact_kind': VERSION, 'goal_revision': settings['goal_revision'], 'snapshot': str(snapshot_path),
            'snapshot_file_sha256': loaded.sha256, 'expires_at': snapshot.usage.expires_at,
            'reference': {'path': str(reference_path), 'sha256': reference_hash, 'runtime_input': False},
            'deployment': deployment, 'model_files': deepcopy(source['model_files']),
            'classifier': deepcopy(source['classifier']), 'documents': deepcopy(source['documents']),
            'selections': deepcopy(source['selections']), 'inputs': {str(p): sha(p) for p in paths},
            'code_sha256': code_hashes(), 'budget': {k: settings[k] for k in ('cycle_id', 'ledger')},
            'limits': {'analysis_seconds': None, 'call_seconds': 180, 'embedding_seconds': 900,
                       'fact_batch_seconds': 600, 'retries': 0}, 'retrieval': deepcopy(corpus.RETRIEVAL),
            'questions': deepcopy(QUESTIONS), 'canonical_population': len(corpus.sources(snapshot)),
            'cross_run_response_reuse': False, 'runtime_reference_labels': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    print({'prepared': True, 'canonical_population': plan['canonical_population'],
           'reference_frozen': True, 'analysis_seconds': None, 'new_model_calls': 0}, flush=True)


@contextmanager
def experiment_lock(directory):
    # Existence is not liveness. The OS advisory lock, not this empty file, owns
    # a running attempt; opening a stale file after a crash is safe.
    with (directory/'execution.lock').open('a+b') as stream:
        if fcntl is None and os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'\0'); stream.flush()
        stream.seek(0)
        try:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            import errno
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK): raise
            raise RuntimeError('This experiment already has a live executor') from None
        try: yield
        finally:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_UN)
            else:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def validate(plan):
    if (plan['artifact_kind'] != VERSION or plan['questions'] != QUESTIONS or plan['retrieval'] != corpus.RETRIEVAL
            or plan['limits']['analysis_seconds'] is not None or plan['cross_run_response_reuse'] is not False):
        raise ValueError('Unknown/changed corpus execution contract')
    live(plan['expires_at'])
    for field in ('inputs', 'code_sha256', 'model_files'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen input/code/model changed')
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    snapshot = load_snapshot(Path(plan['snapshot'])).snapshot
    if sha(plan['snapshot']) != plan['snapshot_file_sha256'] or len(corpus.sources(snapshot)) != plan['canonical_population']:
        raise ValueError('Snapshot population changed')
    reference_check(snapshot, read_json(plan['reference']['path']), plan['reference']['sha256'])
    return snapshot


def run(directory):
    attempt_started = datetime.now(timezone.utc); started = time.monotonic()
    if not directory.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Research outputs must remain in the private runs tree')
    with experiment_lock(directory):
        plan = read_json(directory/'plan.json'); snapshot = validate(plan); plan_hash = sha(directory/'plan.json')
        if (directory/'completed.json').exists():
            report = read_json(directory/'completed.json')
            output = read_json(directory/'artifacts/output.json')
            if report['plan_sha256'] != plan_hash or report['output_sha256'] != digest(output):
                raise ValueError('Completed plan or output changed')
            print({'already_executed': True, 'quality_gate_passed': False}, flush=True); return report
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        base = Runner(directory, plan, budget); base.started = started
        runner = CheckpointRunner(base, plan['deployment']['runtime'])
        attempt = len(list((directory/'attempts').glob('*.started.json'))) + 1
        if not (directory/'started.json').exists():
            write(directory/'started.json', {'plan_sha256': plan_hash, 'started_at': attempt_started.isoformat(),
                  'budget_before': budget.summary()})
        origin = read_json(directory/'started.json')
        if origin['plan_sha256'] != plan_hash: raise ValueError('Cannot resume a different plan')
        write(directory/'attempts'/f'{attempt:04}.started.json', {'pid': os.getpid(), 'plan_sha256': plan_hash,
              'started_at': attempt_started.isoformat(), 'same_plan_resume': attempt > 1})

        def save(name, value):
            path = directory/'artifacts'/(name + '.json')
            if path.exists():
                if read_json(path) != value: raise ValueError('Same-plan stage artifact changed')
            else: write(path, value)

        def embed(stage, texts):
            path = directory/'embeddings'/(stage + '.json')
            req = {'system': framed_embedding.VERSION, 'data': {'texts': texts, 'output': str(path)},
                   'schema': {}, 'max_tokens': 1}
            result = runner.call('embed-' + stage, req, provider=framed_embedding.generate,
                                 maximum=plan['limits']['embedding_seconds'])
            if result['output'] != str(path) or sha(path) != result['sha256'] or result['texts_sha256'] != digest(texts):
                raise ValueError('Embedding artifact changed')
            artifact = read_json(path)
            if (artifact['texts_sha256'] != digest(texts) or artifact['model'] != result['model']
                    or artifact['revision'] != result['revision'] or artifact['model'] != framed_embedding.MODEL
                    or artifact['revision'] != framed_embedding.REVISION or artifact['local_files_only'] is not True):
                raise ValueError('Embedding input/model changed')
            return artifact['vectors']

        def facts(req):
            return runner.call('fact-' + digest(req)[:24], req, provider=evidence_nli.generate,
                               maximum=plan['limits']['fact_batch_seconds'])
        try:
            with owned_server(plan['deployment'], 'baseline', directory/'servers'/f'{attempt:04}'):
                output = corpus.process(snapshot, runner, embed, facts, model=plan['classifier'],
                                        documents=plan['documents'], selections=plan['selections'], save=save, limits=plan['retrieval'])
                save('output', output)
                timing_path = directory/'artifacts/analysis-finished.json'
                if not timing_path.exists(): save('analysis-finished', {'at': datetime.now(timezone.utc).isoformat()})
                analysis_finished = datetime.fromisoformat(read_json(timing_path)['at'])
                runtime_path = directory/'artifacts/runtime.json'
                if runtime_path.exists():
                    runtime = read_json(runtime_path)
                    compiled = output['agent_inputs']['compiled']
                    ids = [p['candidate_id'] for p in compiled['profiles']]
                    expected = {(cid, q['id']) for cid in ids for q in QUESTIONS}
                    actual = {(r['candidate_id'], r['question_id']) for r in runtime['turns']}
                    if (runtime['all_compiled_candidate_ids'] != ids or actual != expected
                            or len(runtime['turns']) != len(expected)
                            or any(r['turn']['compiled_sha256'] != digest(compiled) for r in runtime['turns'])):
                        raise ValueError('Same-plan runtime artifact changed')
                else:
                    runtime = runtime_probe(output['agent_inputs']['bundle'], runner); save('runtime', runtime)
            inputs = output['agent_inputs']; report = {
                'artifact_kind': VERSION, 'plan_sha256': plan_hash, 'execution_complete': True,
                'canonical_population': plan['canonical_population'], 'discovered_candidates': len(output['candidates']),
                'membership_judgments': len(output['memberships']), 'compiled_profiles': len(inputs['compiled']['profiles']),
                'runtime_turns': len(runtime['turns']), 'errors': output['errors'],
                'analysis_seconds_including_resume_downtime': (analysis_finished-datetime.fromisoformat(origin['started_at'])).total_seconds(),
                'attempt_seconds': time.monotonic()-started, 'same_plan_reused_calls_this_attempt': runner.reused,
                'cross_run_response_reuse': False, 'runtime_reference_labels': False, 'correct_comment_utilization': None,
                'output_sha256': digest(output), 'bundle_sha256': digest(inputs['bundle']), 'compiled_sha256': digest(inputs['compiled']),
                'semantic_review_required': True, 'quality_gate_passed': False, 'budget_after': budget.summary()}
            write(directory/'completed.json', report)
            print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True); return report
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json', {'exception_type': type(exc).__name__,
                  'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary()})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--snapshot', type=Path, required=True); p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--deployment-source', type=Path, default=Path('runs/fresh-direct-product-20261014/plan.json'))
    p.add_argument('--cycle', type=Path, default=Path('runs/mvp-factory-20261014/cycle.json'))
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.directory, args.snapshot, args.reference, args.deployment_source, args.cycle)
    else: run(args.directory)
