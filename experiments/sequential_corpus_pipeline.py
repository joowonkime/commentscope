"""Whole-corpus execution with exclusive local-model lifetimes.

Separate frozen contract from the historical always-resident runner. Semantic
processing is shared, not reimplemented: only deployment ownership/deadlines
change. A completed execution is never a utilization or Agent quality approval.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import time

from commentscope.factory import framed_corpus as corpus
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.ingestion import load_snapshot
from commentscope.providers import framed_embedding, evidence_nli, host_resources
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.providers.exclusive_models import ExclusiveModels, VERSION as LIFETIME_VERSION
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash, command
from experiments.corpus_resource_guard import host_observation
from experiments.framed_corpus_pipeline import experiment_lock, reference_check
from experiments.framed_agent_probe import runtime_probe, QUESTIONS
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes
from experiments.source_bound_comparison import qualification, preflight, HOST_ONLY_PREFLIGHT

VERSION = 'sequential-whole-framed-corpus-pipeline-0.1'
PRIVATE_ROOT = Path('runs')
LIMITS = {'analysis_seconds': None, 'call_seconds': 1800, 'embedding_seconds': 900,
          'fact_batch_seconds': 600, 'retries': 0}
LIFETIME = {'version': LIFETIME_VERSION, 'ownership': 'uncached_call_below_checkpoint',
            'auxiliary_resource_policy': deepcopy(host_resources.POLICY)}


def private(directory):
    if not directory.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Research outputs must remain in the private runs tree')


def cycle_check(settings):
    if (settings['goal_revision'] != 'factory-goal-20261014-r4'
            or settings['cycle_id'] != 'mvp-factory-20261014'
            or settings['limit_seconds'] is not None or settings['analysis_seconds'] is not None):
        raise ValueError('Current uncapped Factory cycle required')


def deployment_check(deployment):
    runtime = deployment['runtime']
    if (runtime.get('memory_profile', {}).get('version') != 'local-memory-profile-0.4'
            or runtime.get('max_seconds_per_model') is not None
            or runtime.get('retries') != 0 or runtime.get('repairs') != 0):
        raise ValueError('Qualified uncapped CPU deployment required')
    command(deployment, 'baseline')


def prepare(directory, snapshot_path, reference_path, deployment_source, auxiliary_source, cycle, *,
            implementation_plan=Path('runs/sequential-corpus-integration-20261015-plan.json')):
    private(directory)
    if directory.exists(): raise ValueError('Never overwrite a pipeline plan')
    loaded = load_snapshot(snapshot_path); snapshot = loaded.snapshot
    corpus.sources(snapshot); live(snapshot.usage.expires_at)
    reference = read_json(reference_path); reference_hash = digest(reference)
    reference_check(snapshot, reference, reference_hash)
    settings = read_json(cycle); cycle_check(settings)
    deployment = deepcopy(read_json(deployment_source)['deployment']); deployment_check(deployment)
    qualified_paths = qualification(deployment_source, deployment)
    auxiliary = read_json(auxiliary_source)
    for info in (deployment['server'], deployment['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Existing deployment changed')
    if any(sha(p) != h for p, h in auxiliary['model_files'].items()):
        raise ValueError('Existing embedding/NLI files changed')
    for doc in auxiliary['documents']: live(doc['expires_at'])
    paths = [snapshot_path, reference_path, deployment_source, auxiliary_source, cycle, *qualified_paths,
             Path('docs/MVP_GOAL.md'), Path('docs/MVP_PRODUCT_POLICY.md'),
             Path(implementation_plan)]
    plan = {'artifact_kind': VERSION, 'goal_revision': settings['goal_revision'], 'snapshot': str(snapshot_path),
        'snapshot_file_sha256': loaded.sha256, 'expires_at': snapshot.usage.expires_at,
        'reference': {'path': str(reference_path), 'sha256': reference_hash, 'runtime_input': False},
        'deployment_source': str(deployment_source), 'auxiliary_source': str(auxiliary_source), 'cycle': str(cycle),
        'deployment': deployment, 'model_files': deepcopy(auxiliary['model_files']),
        'classifier': deepcopy(auxiliary['classifier']), 'documents': deepcopy(auxiliary['documents']),
        'selections': deepcopy(auxiliary['selections']), 'inputs': {str(p): sha(p) for p in paths},
        'code_sha256': code_hashes(), 'budget': {k: settings[k] for k in ('cycle_id', 'ledger')},
        'limits': deepcopy(LIMITS), 'preflight': deepcopy(HOST_ONLY_PREFLIGHT), 'model_lifetime': deepcopy(LIFETIME),
        'retrieval': deepcopy(corpus.RETRIEVAL), 'questions': deepcopy(QUESTIONS),
        'canonical_population': len(corpus.sources(snapshot)), 'cross_run_response_reuse': False,
        'runtime_reference_labels': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    return plan


def validate_contract(plan):
    """Check execution policy/budget binding without opening model files."""
    if (plan['artifact_kind'] != VERSION or plan['limits'] != LIMITS or plan['model_lifetime'] != LIFETIME
            or plan['preflight'] != HOST_ONLY_PREFLIGHT or plan['questions'] != QUESTIONS
            or plan['retrieval'] != corpus.RETRIEVAL or plan['cross_run_response_reuse'] is not False
            or plan['runtime_reference_labels'] is not False or plan['reference']['runtime_input'] is not False
            or plan['quality_gate_passed'] is not False):
        raise ValueError('Unknown/changed sequential execution contract')
    settings = read_json(plan['cycle']); cycle_check(settings)
    if (plan['goal_revision'] != settings['goal_revision']
            or plan['budget'] != {k: settings[k] for k in ('cycle_id', 'ledger')}):
        raise ValueError('Current cycle binding changed')
    deployment_check(plan['deployment'])


def validate(plan):
    validate_contract(plan)
    for field in ('inputs', 'code_sha256', 'model_files'):
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen input/code/model changed')
    qualification(Path(plan['deployment_source']), plan['deployment'])
    auxiliary = read_json(plan['auxiliary_source'])
    if any(plan[k] != auxiliary[k] for k in ('model_files', 'classifier', 'documents', 'selections')):
        raise ValueError('Auxiliary deployment/evidence binding changed')
    for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    live(plan['expires_at'])
    for doc in plan['documents']: live(doc['expires_at'])
    snapshot = load_snapshot(Path(plan['snapshot']))
    if (snapshot.sha256 != plan['snapshot_file_sha256']
            or snapshot.snapshot.usage.expires_at != plan['expires_at']
            or len(corpus.sources(snapshot.snapshot)) != plan['canonical_population']):
        raise ValueError('Snapshot population changed')
    reference_check(snapshot.snapshot, read_json(plan['reference']['path']), plan['reference']['sha256'])
    return snapshot.snapshot


class SequentialRunner:
    """A base-call adapter; CheckpointRunner stays outside this boundary."""
    def __init__(self, base, models, directory):
        self.base, self.models = base, models
        self.directory, self.plan_sha = base.directory, base.plan_sha
        self.events = directory; self.event_sequence = 0

    @property
    def seq(self): return self.base.seq

    @seq.setter
    def seq(self, value): self.base.seq = value

    def call(self, stage, req, *, provider=None, maximum=None):
        if provider is not None and provider not in (framed_embedding.generate, evidence_nli.generate):
            raise ValueError('Unrecognized auxiliary model provider')
        self.event_sequence += 1
        path = self.events/f'{self.event_sequence:05}'
        kind = 'llm' if provider is None else 'auxiliary'
        write(path.with_suffix('.started.json'), {'kind': kind, 'stage': stage, 'plan_sha256': self.plan_sha,
              'request_sha256': digest(req), 'at': datetime.now(timezone.utc).isoformat()})
        try:
            result = self.models.invoke(kind, lambda: self.base.call(stage, req, provider=provider, maximum=maximum))
        except BaseException as exc:
            write(path.with_suffix('.failed.json'), {'exception_type': type(exc).__name__, 'stage': stage})
            raise
        write(path.with_suffix('.finished.json'), {'stage': stage, 'at': datetime.now(timezone.utc).isoformat(),
              'server_starts': self.models.server_starts, 'server_stops': self.models.server_stops,
              'auxiliary_calls': self.models.auxiliary_calls})
        return result


def lifetimes(directory, plan, attempt):
    root = directory/'models'/f'{attempt:04}'

    @contextmanager
    def server(sequence):
        preflight(directory, plan)
        target = root/f'llm-{sequence:04}'
        with owned_server(plan['deployment'], 'baseline', target) as proc:
            yield proc
        # owned_server waits for its child and observer; verify the durable
        # cleanup evidence before permitting an auxiliary model to start.
        stopped = read_json(target/'stopped.json')
        finished = read_json(target/'resources/finished.json')
        if stopped['returncode'] != 0 or finished['observer_stopped'] is not True:
            raise RuntimeError('Owned server or resource observer cleanup not confirmed')

    @contextmanager
    def auxiliary(sequence):
        target = root/f'auxiliary-{sequence:04}'
        with host_resources.watch(target, plan['model_lifetime']['auxiliary_resource_policy'], host_observation):
            yield
        if read_json(target/'finished.json')['observer_stopped'] is not True:
            raise RuntimeError('Auxiliary resource observer cleanup not confirmed')

    return ExclusiveModels(server, auxiliary)


def runtime_check(runtime, compiled):
    ids = [p['candidate_id'] for p in compiled['profiles']]
    expected = {(cid, q['id']) for cid in ids for q in QUESTIONS}
    actual = {(r['candidate_id'], r['question_id']) for r in runtime['turns']}
    if (runtime['all_compiled_candidate_ids'] != ids or actual != expected or len(runtime['turns']) != len(expected)
            or any(r['turn']['compiled_sha256'] != digest(compiled) for r in runtime['turns'])):
        raise ValueError('Same-plan runtime artifact changed')


def run(directory):
    private(directory); started = time.monotonic(); at = datetime.now(timezone.utc).isoformat()
    with experiment_lock(directory):
        plan = read_json(directory/'plan.json'); snapshot = validate(plan); plan_hash = sha(directory/'plan.json')
        if (directory/'completed.json').exists():
            report = read_json(directory/'completed.json')
            if (report['plan_sha256'] != plan_hash
                    or report['output_sha256'] != digest(read_json(directory/'artifacts/output.json'))
                    or report['runtime_sha256'] != digest(read_json(directory/'artifacts/runtime.json'))):
                raise ValueError('Completed plan/output/runtime changed')
            return report
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        attempt = len(list((directory/'attempts').glob('*.started.json'))) + 1
        if not (directory/'started.json').exists():
            write(directory/'started.json', {'plan_sha256': plan_hash, 'started_at': at, 'budget_before': budget.summary()})
        origin = read_json(directory/'started.json')
        if origin['plan_sha256'] != plan_hash: raise ValueError('Cannot resume a different plan')
        write(directory/'attempts'/f'{attempt:04}.started.json', {'pid': os.getpid(), 'plan_sha256': plan_hash,
              'started_at': at, 'same_plan_resume': attempt > 1})

        def save(name, value):
            path = directory/'artifacts'/(name + '.json')
            if path.exists():
                if read_json(path) != value: raise ValueError('Same-plan stage artifact changed')
            else: write(path, value)

        try:
            with lifetimes(directory, plan, attempt) as models:
                base = Runner(directory, plan, budget); base.started = started
                wrapped = SequentialRunner(base, models, directory/'transitions'/f'{attempt:04}')
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

                def facts(req):
                    return runner.call('fact-' + digest(req)[:24], req, provider=evidence_nli.generate,
                                       maximum=plan['limits']['fact_batch_seconds'])

                output = corpus.process(snapshot, runner, embed, facts, model=plan['classifier'],
                    documents=plan['documents'], selections=plan['selections'], save=save, limits=plan['retrieval'])
                save('output', output)
                timing_path = directory/'artifacts/analysis-finished.json'
                if not timing_path.exists(): save('analysis-finished', {'at': datetime.now(timezone.utc).isoformat()})
                analysis_finished = datetime.fromisoformat(read_json(timing_path)['at'])
                runtime_path = directory/'artifacts/runtime.json'
                if runtime_path.exists(): runtime = read_json(runtime_path)
                else:
                    runtime = runtime_probe(output['agent_inputs']['bundle'], runner); save('runtime', runtime)
                runtime_check(runtime, output['agent_inputs']['compiled'])
            inputs = output['agent_inputs']
            report = {'artifact_kind': VERSION, 'plan_sha256': plan_hash, 'execution_complete': True,
                'canonical_population': plan['canonical_population'], 'discovered_candidates': len(output['candidates']),
                'membership_judgments': len(output['memberships']), 'compiled_profiles': len(inputs['compiled']['profiles']),
                'runtime_turns': len(runtime['turns']), 'errors': output['errors'],
                'analysis_seconds_including_resume_downtime': (analysis_finished-datetime.fromisoformat(origin['started_at'])).total_seconds(),
                'attempt_seconds': time.monotonic()-started, 'same_plan_reused_calls_this_attempt': runner.reused,
                'model_lifetime': {'server_starts': models.server_starts, 'server_stops': models.server_stops,
                                   'auxiliary_calls': models.auxiliary_calls},
                'cross_run_response_reuse': False, 'runtime_reference_labels': False, 'correct_comment_utilization': None,
                'output_sha256': digest(output), 'runtime_sha256': digest(runtime),
                'bundle_sha256': digest(inputs['bundle']), 'compiled_sha256': digest(inputs['compiled']),
                'semantic_review_required': True, 'quality_gate_passed': False, 'budget_after': budget.summary()}
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
    p.add_argument('--snapshot', type=Path, required=True); p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--deployment-source', type=Path, default=Path('runs/resource-host-only-probe-20261014/plan.json'))
    p.add_argument('--auxiliary-source', type=Path, default=Path('runs/fresh-direct-product-20261014/plan.json'))
    p.add_argument('--cycle', type=Path, default=Path('runs/mvp-factory-20261014/cycle.json'))
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepared = prepare(args.directory, args.snapshot, args.reference, args.deployment_source, args.auxiliary_source, args.cycle)
        print({'prepared': True, 'canonical_population': prepared['canonical_population'], 'new_model_calls': 0}, flush=True)
    else: run(args.directory)
