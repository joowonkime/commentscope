"""Frozen G1/G2/G3/G4 executor for the minimal-claim Factory.

All outputs are private; no downloads, external inference, retries or approvals.
Quality gates are offline reviews, never fabricated from execution completion.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
from shutil import copy2
import subprocess
import tempfile
import time

from commentscope.factory import minimal_pipeline, fact_checks, acceptance
from commentscope.factory import raw_membership_verification, candidate_consolidation, contextual_dependencies
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.framed_corpus import sources
from commentscope.ingestion import load_snapshot
from commentscope.providers import framed_embedding, evidence_nli, host_resources, context_capacity
from commentscope.providers import llama_runtime
from commentscope.providers.runtime_runner import RuntimeRunner
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.providers.exclusive_models import ExclusiveModels
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, file_hash, command
from experiments.corpus_resource_guard import host_observation
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.framed_cluster_controls import synthetic_snapshot
from experiments.framed_agent_probe import runtime_probe, QUESTIONS
from experiments.model_selection_20261016 import TRANSFER, PREFLIGHT, observe
from experiments.fresh_grounded_pipeline import Runner
from experiments.scoped_discovery_probe import code_hashes
from experiments.sequential_corpus_pipeline import SequentialRunner, runtime_check, cycle_check

VERSION = 'minimal-factory-executor-20261025-v15'
DESIGN = 'factory-implementation-20261016-v1'
AUTONOMY = 'factory-autonomy-20261016-v1'
LIMITS = {'analysis_seconds': None, 'call_seconds': 600, 'embedding_seconds': 900,
          'fact_batch_seconds': 600, 'retries': 0, 'repairs': 0}
BASE = Path('runs/model-selection-20261016/off/plan.json')
AUXILIARY = Path('runs/framed-corpus-sequential-20261015/plan.json')
FACTS = Path('runs/fact-evidence-development-20261013/plan.json')
SAMPLES = Path('runs/design-freeze-20261016/samples.json')
CYCLE = Path('runs/mvp-factory-20261014/cycle.json')
ACCEPTANCE = Path('runs/goal-reset-20261017-r5/acceptance-profile.json')


def private(directory):
    if not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('Private runs directory required')


def synthetic12():
    base = synthetic_snapshot()
    extra = tuple(replace(base.comments[0], comment_id=sid, text_original=text, parent_id=None) for sid, text, _ in TRANSFER)
    return replace(base, snapshot_id=VERSION+'-G1', comments=base.comments+extra)


def deployment_check(deployment):
    if deployment.get('version') == llama_runtime.VERSION:
        llama_runtime.validate(deployment)
        return
    runtime = deployment['runtime']
    expected = read_json(BASE)['deployment']
    if deployment != expected or runtime['reasoning'] != 'off' or runtime['gpu_layers'] != 99:
        raise ValueError('Frozen existing 8B GPU thinking-off deployment required')
    command(deployment, 'baseline')


def portable_host_observation():
    host = host_observation()
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                         capture_output=True, text=True, timeout=15, check=True)
    lines = gpu.stdout.strip().splitlines()
    if len(lines) != 1:
        raise ValueError('Exactly one observed GPU required')
    return {**host, 'gpu_free_mb': int(lines[0])}


def check_admission(gate, deployment, manifest_path, discovery_mode='free', membership_mode='raw'):
    """Prior offline reviews bind model/code/output; never model-input labels."""
    required = {'G1': (), 'G2': ('G1',), 'G3': ('G1', 'G2'), 'G4': ('G1', 'G2', 'G3')}[gate]
    if not required:
        return
    if manifest_path is None:
        raise ValueError('Passed qualification gates required before larger run')
    private(Path(manifest_path))
    manifest = read_json(manifest_path)
    current_code = code_hashes()
    for stage in required:
        row = manifest['gates'][stage]
        for key in ('run', 'packet', 'review', 'result'):
            private(Path(row[key]))
        prior = read_json(Path(row['run'])/'plan.json')
        completed = read_json(Path(row['run'])/'completed.json')
        packet, review, result = (read_json(row[k]) for k in ('packet', 'review', 'result'))
        if (prior['gate'] != stage or result['gate'] != stage or result['gate_passed'] is not True
                or not result['requirements'] or any(v is not True for v in result['requirements'].values())
                or prior['deployment'] != deployment or prior['code_sha256'] != current_code
                or prior['discovery_mode'] != discovery_mode or prior['membership_mode'] != membership_mode
                or prior['verification_contract'] != raw_membership_verification.FULL_SCOPE
                or completed['execution_complete'] is not True
                or completed['plan_sha256'] != sha(Path(row['run'])/'plan.json')
                or packet['plan_sha256'] != completed['plan_sha256']
                or packet['run'] != row['run']
                or result['review_sha256'] != sha(row['review'])
                or result['packet_sha256'] != digest(packet) or review['packet_sha256'] != digest(packet)
                or packet['output_sha256'] != completed['output_sha256']
                or packet['runtime_sha256'] != completed['runtime_sha256']
                or completed['output_sha256'] != sha(Path(row['run'])/'artifacts/output.json')
                or completed['runtime_sha256'] != sha(Path(row['run'])/'artifacts/runtime.json')):
            raise ValueError('Qualification failed or belongs to another deployment/code/output: '+stage)
        if acceptance.from_plan(prior) is None:
            raise ValueError('Qualification requires the unchanged r5 acceptance profile')
        # Recompute the existing offline evaluator from the bound full review.
        # A hand-written gate_passed flag alone cannot authorize a larger run.
        from experiments.minimal_factory_review import evaluate
        with tempfile.TemporaryDirectory(dir='runs', prefix='admission-replay-') as tmp:
            replayed = evaluate(Path(row['packet']).parent, Path(row['review']), Path(tmp)/'result.json')
        if replayed != result:
            raise ValueError('Qualification report does not match its full offline review')


def prepare(directory, gate, discovery_mode='free', membership_mode='scoped', hypothesis_file=None,
            deployment_file=None, admission_file=None):
    private(directory)
    if directory.exists(): raise ValueError('New run required; frozen plans are never overwritten')
    if gate not in ('G1', 'G2', 'G3', 'G4'): raise ValueError('Unknown implementation gate')
    if discovery_mode not in ('free','literal','contextual'):raise ValueError('Unknown Factory discovery mode')
    if membership_mode not in ('scoped','raw'):raise ValueError('Unknown membership mode')
    profile = acceptance.validate(read_json(ACCEPTANCE), acceptance.R5_DIGEST)
    settings = read_json(CYCLE); cycle_check(settings)
    deployment = read_json(deployment_file) if deployment_file is not None else read_json(BASE)['deployment']
    deployment_check(deployment)
    portable = deployment.get('version') == llama_runtime.VERSION
    if portable:
        if membership_mode != 'raw':
            raise ValueError('Portable qualification requires full original raw membership')
        check_admission(gate, deployment, admission_file, discovery_mode, membership_mode)
    auxiliary = read_json(AUXILIARY); evidence = read_json(FACTS); samples = read_json(SAMPLES)
    if gate == 'G1':
        snapshot = synthetic12(); snapshot_path = directory/'snapshot.json'
        scope = sorted(sources(snapshot))
    else:
        snapshot_path = Path(samples['snapshot']); snapshot = load_snapshot(snapshot_path).snapshot
        if sha(snapshot_path) != samples['snapshot_sha256']: raise ValueError('Frozen sample input changed')
        if gate == 'G4': scope = sorted(sources(snapshot))
        else:
            selection = samples['development' if gate == 'G2' else 'holdout']
            scope = selection['source_ids']
    fact_checks.live(snapshot.usage.expires_at)
    document = evidence['document']
    if isinstance(document, str): document = read_json(document)
    fact_checks.live(document['expires_at'])
    # Reuse source material only. Historical rows/agents and labels stay outside.
    documents = [document]; selections = evidence['selections']
    if gate == 'G1': write(snapshot_path, snapshot.to_dict())
    paths = [deployment_file or BASE, AUXILIARY, FACTS, SAMPLES, CYCLE, snapshot_path, ACCEPTANCE,
             Path(samples['meaning_reference']),
             Path('docs/MVP_EXECUTION_SPEC.md'), Path('docs/MVP_GOAL.md'), Path('docs/MVP_PRODUCT_POLICY.md'),
             Path('docs/MVP_HANDOFF_2026-10-16.md'), Path('experiments/framed_agent_probe.py')]
    if hypothesis_file is not None:
        private(hypothesis_file)
        paths.append(hypothesis_file)
    if admission_file is not None:
        private(admission_file)
        paths.append(admission_file)
    plan = {'artifact_kind': VERSION, 'design_version': DESIGN, 'autonomy_version': AUTONOMY, 'gate': gate,
            'goal_revision': profile['goal_revision'], 'acceptance_profile': deepcopy(profile),
            'acceptance_profile_sha256': digest(profile),
            'discovery_mode':discovery_mode, 'membership_mode':membership_mode,
            'verification_contract':raw_membership_verification.FULL_SCOPE,
            'representative_policy':candidate_consolidation.REPRESENTATIVE_POLICY if discovery_mode=='contextual' else None,
            'dependency_capacity_policy':contextual_dependencies.CAPACITY_POLICY if discovery_mode=='contextual' else None,
            'snapshot': str(snapshot_path), 'snapshot_sha256': sha(snapshot_path),
            'expires_at': snapshot.usage.expires_at, 'scope_ids': scope,
            'canonical_population': len(sources(snapshot)), 'processing_count': len(scope),
            'code_sha256': code_hashes(), 'inputs': {str(p): sha(p) for p in paths},
            'deployment': deepcopy(deployment), 'model_files': deepcopy(auxiliary['model_files']),
            'classifier': deepcopy(auxiliary['classifier']), 'documents': documents, 'selections': selections,
            'document_sha256': {d['id']: digest(d) for d in documents},
            'cycle': str(CYCLE), 'budget': {k: settings[k] for k in ('cycle_id', 'ledger')},
            'limits': deepcopy(LIMITS), 'preflight': deepcopy(llama_runtime.STARTUP if portable else PREFLIGHT),
            'schedule': deepcopy(minimal_pipeline.SCHEDULE),
            'resource_policy': deepcopy(host_resources.POLICY), 'questions': deepcopy(QUESTIONS),
            'sample_manifest_sha256': sha(SAMPLES), 'reference_runtime_input': False,
            'cross_run_response_reuse': False, 'quality_gate_passed': False,
            'hypothesis': 'Minimal source claims, complete-link equivalence, independent final wording support, delayed source arguments.',
            'acceptance': 'MVP_EXECUTION_SPEC section5; offline all-output review; no runtime corrections.'}
    if portable:
        plan['portable_admission_file'] = str(admission_file) if admission_file else None
    if hypothesis_file is not None:plan['frozen_experiment_hypothesis']=read_json(hypothesis_file)
    write(directory/'plan.json', plan)
    for path, expected in plan['code_sha256'].items():
        if sha(path) != expected: raise ValueError('Code changed while archiving frozen plan')
        target = directory/'frozen-code'/path
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(path, target)
    return plan


def validate(plan):
    portable = plan['deployment'].get('version') == llama_runtime.VERSION
    if acceptance.from_plan(plan) is None: raise ValueError('New executions require r5 acceptance')
    if (plan['artifact_kind'] != VERSION or plan['design_version'] != DESIGN or plan['autonomy_version'] != AUTONOMY
            or plan['discovery_mode'] not in ('free','literal','contextual')
            or plan['membership_mode'] not in ('scoped','raw')
            or plan['verification_contract'] != raw_membership_verification.FULL_SCOPE
            or plan['representative_policy'] != (candidate_consolidation.REPRESENTATIVE_POLICY if plan['discovery_mode']=='contextual' else None)
            or plan['dependency_capacity_policy'] != (contextual_dependencies.CAPACITY_POLICY if plan['discovery_mode']=='contextual' else None)
            or plan['schedule'] != minimal_pipeline.SCHEDULE
            or plan['limits'] != LIMITS or plan['preflight'] != (llama_runtime.STARTUP if portable else PREFLIGHT) or plan['questions'] != QUESTIONS
            or plan['resource_policy'] != host_resources.POLICY or plan['reference_runtime_input'] is not False
            or plan['cross_run_response_reuse'] is not False or plan['quality_gate_passed'] is not False):
        raise ValueError('Frozen Factory execution contract changed')
    settings = read_json(plan['cycle']); cycle_check(settings)
    if plan['budget'] != {k: settings[k] for k in ('cycle_id', 'ledger')}: raise ValueError('Ledger changed')
    deployment_check(plan['deployment'])
    if portable:
        check_admission(plan['gate'], plan['deployment'],
                        Path(plan['portable_admission_file']) if plan['portable_admission_file'] else None,
                        plan['discovery_mode'], plan['membership_mode'])
    for group in ('inputs', 'code_sha256', 'model_files'):
        if any(sha(p) != h for p, h in plan[group].items()): raise ValueError('Frozen code/input/model changed: '+group)
    for info in (plan['deployment']['server'], plan['deployment']['model'] if portable else plan['deployment']['models']['baseline']):
        if file_hash(info['path']) != info['sha256']: raise ValueError('Model/server changed')
    fact_checks.live(plan['expires_at'])
    for document in plan['documents']:
        fact_checks.live(document['expires_at'])
        if digest(document) != plan['document_sha256'][document['id']]: raise ValueError('Evidence changed')
    loaded = load_snapshot(Path(plan['snapshot'])); snapshot = loaded.snapshot
    if loaded.sha256 != plan['snapshot_sha256'] or len(sources(snapshot)) != plan['canonical_population']:
        raise ValueError('Snapshot changed')
    if (len(plan['scope_ids']) != len(set(plan['scope_ids'])) or not set(plan['scope_ids']) <= set(sources(snapshot))
            or len(plan['scope_ids']) != plan['processing_count']): raise ValueError('Processing scope changed')
    return snapshot


def lifetimes(directory, plan, attempt):
    root = directory/'models'/f'{attempt:04}'
    @contextmanager
    def server(sequence):
        target = root/f'llm-{sequence:04}'
        if plan['deployment'].get('version') == llama_runtime.VERSION:
            from experiments.compare_backend_discovery import check_quota
            with llama_runtime.owned_server(plan['deployment'], target/'server',
                                            portable_host_observation, check_quota) as client:
                yield client
            if read_json(target/'server/resources/finished.json')['observer_stopped'] is not True:
                raise RuntimeError('Portable resource observer shutdown not confirmed')
            return
        observation = observe()
        write(target/'preflight.json', observation)
        if observation['refusal_reasons']: raise RuntimeError('GPU deployment start refused by resource policy')
        with owned_server(plan['deployment'], 'baseline', target/'server') as process:
            yield process
        if (read_json(target/'server/stopped.json')['returncode'] != 0
                or read_json(target/'server/resources/finished.json')['observer_stopped'] is not True):
            raise RuntimeError('Server/observer shutdown not confirmed')
    @contextmanager
    def auxiliary(sequence):
        target = root/f'auxiliary-{sequence:04}'
        with host_resources.watch(target, plan['resource_policy'], host_observation): yield
        if read_json(target/'finished.json')['observer_stopped'] is not True:
            raise RuntimeError('Auxiliary observer shutdown not confirmed')
    return ExclusiveModels(server, auxiliary)


def run(directory):
    from experiments.compare_backend_discovery import check_quota, quota_watch
    check_quota()
    private(directory); started = time.monotonic(); at = datetime.now(timezone.utc).isoformat()
    with experiment_lock(directory), quota_watch():
        plan = read_json(directory/'plan.json'); snapshot = validate(plan); plan_hash = sha(directory/'plan.json')
        if (directory/'completed.json').exists():
            report = read_json(directory/'completed.json')
            if (report['plan_sha256'] != plan_hash or report['output_sha256'] != sha(directory/'artifacts/output.json')
                    or report['runtime_sha256'] != sha(directory/'artifacts/runtime.json')):
                raise ValueError('Completed artifacts changed')
            return report
        attempt = len(list((directory/'preflight').glob('*.json')))+1
        # Starting with ambiguous pending requests is forbidden even if other
        # calls are reusable. No implicit retry after interruption.
        pending = [p for p in (directory/'checkpoints').glob('*.intent.json')
                   if not p.with_name(p.name.replace('.intent.json', '.result.json')).exists()]
        if pending: raise RuntimeError('Pending requests require process/ledger reconciliation')
        portable = plan['deployment'].get('version') == llama_runtime.VERSION
        if portable:
            host = portable_host_observation()
            observation = {'host': host, 'refusal_reasons': llama_runtime.startup_reasons(host, plan['deployment'])}
        else:
            observation = observe()
        write(directory/'preflight'/f'{attempt:04}.json', observation)
        if observation['refusal_reasons']: raise RuntimeError('Factory startup resource policy refused')
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        write(directory/'attempts'/f'{attempt:04}.started.json', {'pid': os.getpid(), 'plan_sha256': plan_hash,
              'at': at, 'budget_before': budget.summary(), 'same_plan_resume': attempt > 1})
        def save(name, value):
            path = directory/'artifacts'/(name+'.json')
            if path.exists():
                if read_json(path) != value: raise ValueError('Same-plan artifact changed: '+name)
            else: write(path, value)
        try:
            with lifetimes(directory, plan, attempt) as models:
                client = llama_runtime.Client(plan['deployment']) if portable else None
                base = RuntimeRunner(directory, plan, budget, client) if portable else Runner(directory, plan, budget)
                sequential = SequentialRunner(base, models, directory/'transitions'/f'{attempt:04}')
                allocation = ({'context': 8192, 'reasoning': 'off', 'reasoning_budget': 0}
                              if portable else plan['deployment']['runtime'])
                checkpoint = CheckpointRunner(sequential, allocation)
                def inspect(req):
                    check_quota()
                    return models.invoke('llm', lambda: client.measure(req) if portable else context_capacity.measure(req))
                class CheckedRunner:
                    def call(self, stage, req):
                        measured = inspect(req)
                        if not measured['fits']: raise ValueError('Unsplit request exceeds model context')
                        result = checkpoint.call(stage, req)
                        check_quota()
                        usage = result.get('usage') or {}
                        if usage.get('prompt_tokens', 0) > measured['input_tokens'] + measured['safety_margin']:
                            raise ValueError('Actual prompt exceeds measured template allocation')
                        return result
                runner = CheckedRunner()
                def embed(stage, texts):
                    check_quota()
                    path = directory/'artifacts'/('embedding-'+stage+'.json')
                    req = {'system': framed_embedding.VERSION, 'data': {'texts': texts, 'output': str(path)}, 'schema': {}, 'max_tokens': 1}
                    result = checkpoint.call('embed-'+stage, req, provider=framed_embedding.generate, maximum=LIMITS['embedding_seconds'])
                    if result['output'] != str(path) or sha(path) != result['sha256'] or result['texts_sha256'] != digest(texts):
                        raise ValueError('Embedding artifact changed')
                    artifact = read_json(path)
                    if (artifact['texts_sha256'] != digest(texts) or artifact['model'] != framed_embedding.MODEL
                            or artifact['revision'] != framed_embedding.REVISION or artifact['local_files_only'] is not True):
                        raise ValueError('Embedding provenance changed')
                    return artifact['vectors']
                def facts(req):
                    check_quota()
                    return checkpoint.call('facts-'+digest(req)[:20], req, provider=evidence_nli.generate, maximum=LIMITS['fact_batch_seconds'])
                output = minimal_pipeline.process(snapshot, runner, embed, inspect, facts, model=plan['classifier'],
                    documents=plan['documents'], selections=plan['selections'], scope_ids=plan['scope_ids'], save=save,
                    discovery_mode=plan['discovery_mode'], membership_mode=plan['membership_mode'],verification_contract=plan['verification_contract'])
                save('output', output)
                analysis_seconds = time.monotonic()-started
                runtime = runtime_probe(output['agent_inputs']['bundle'], runner); save('runtime', runtime)
                runtime_check(runtime, output['agent_inputs']['compiled'])
            report = {'artifact_kind': VERSION, 'gate': plan['gate'], 'plan_sha256': plan_hash, 'execution_complete': True,
                      'candidates': len(output['candidates']), 'compiled_agents': len(output['agent_inputs']['compiled']['profiles']),
                      'runtime_turns': len(runtime['turns']), 'binding_errors': len(output['errors']),
                      'capacity_holds': len(output['capacity_holds']), 'unextracted': len(output['unextracted_source_ids']),
                      'analysis_seconds': analysis_seconds, 'attempt_seconds': time.monotonic()-started,
                      'same_plan_reused_calls': checkpoint.reused, 'fresh_run': attempt == 1,
                      'output_sha256': sha(directory/'artifacts/output.json'), 'runtime_sha256': sha(directory/'artifacts/runtime.json'),
                      'semantic_review_required': True, 'quality_gate_passed': False, 'budget_after': budget.summary(),
                      'server_starts': models.server_starts, 'server_stops': models.server_stops, 'auxiliary_calls': models.auxiliary_calls}
            write(directory/'completed.json', report)
            print({k: v for k, v in report.items() if k != 'budget_after'}, flush=True)
            return report
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json', {'exception': type(exc).__name__,
                  'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary()})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path); p.add_argument('--gate', choices=['G1','G2','G3','G4'], required=True)
    p.add_argument('--discovery-mode',choices=['free','literal','contextual'],default='free')
    p.add_argument('--membership-mode',choices=['scoped','raw'],default='scoped')
    p.add_argument('--hypothesis-file',type=Path)
    p.add_argument('--deployment-file',type=Path)
    p.add_argument('--admission-file',type=Path)
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        plan = prepare(args.directory, args.gate, args.discovery_mode, args.membership_mode,
                       args.hypothesis_file, args.deployment_file, args.admission_file)
        print({'prepared': str(args.directory), 'gate': args.gate, 'processing_count': plan['processing_count'], 'model_calls': 0})
    else: run(args.directory)
