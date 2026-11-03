"""Frozen G1/G2/G3/G4 Factory on OpenRouter with pinned local embedding/NLI.

Execution completion is never semantic admission. All outputs, charges and
failed turns remain private. Larger gates require bound, fully replayed prior qualification reviews.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import shutil
import time
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler

from commentscope.agents.runtime_probe import QUESTIONS, runtime_probe, runtime_check
from commentscope.factory import acceptance, fact_checks, minimal_pipeline, raw_membership_verification
from commentscope.factory import compact_claims, raw_membership, source_context_observations
from commentscope.factory import candidate_consolidation
from commentscope.factory import statement_worlds
from commentscope.factory.pipeline_work import ModelResponseUnavailable
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.framed_corpus import sources
from commentscope.file_integrity import source_code_hashes as code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.providers import evidence_nli, framed_embedding, host_resources, openrouter
from commentscope.providers.budget import InferenceBudget, BudgetExhausted
from commentscope.providers.checkpoint_calls import CheckpointRunner, run_origin, PendingCallError
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.local_llama import NoRedirect
from commentscope.providers.openrouter_budget import PaidBudget, SpendLedger, units
from commentscope.storage import write_json_exclusive as write
from experiments.compare_backend_discovery import check_quota, quota_watch
from experiments.minimal_factory_pipeline import synthetic12, check_admission as prior_admission
from experiments.openrouter_factory_probe import key_metadata, private, validate_spend_policy

VERSION = 'minimal-factory-openrouter-executor-20261104-v14'
SAMPLES = Path('runs/design-freeze-20261016/samples.json')


def provider_preflight(deployment):
    selected = deployment.get('provider', {}).get('only', [])
    if len(selected) != 1 or not deployment['provider'].get('max_price'):
        raise ValueError('One pinned provider and finite price ceilings required')
    url = 'https://openrouter.ai/api/v1/models/'+quote(deployment['model'], safe='/')+'/endpoints'
    with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=30) as response:
        endpoints = json.load(response)['data']['endpoints']
    matches = [e for e in endpoints if e['tag'] == selected[0]]
    if len(matches) != 1: raise ValueError('Pinned provider endpoint unavailable')
    endpoint = matches[0]; caps = deployment['provider']['max_price']
    if (endpoint.get('status') != 0 or endpoint['context_length'] != deployment['context']
            or not openrouter.required_parameters(deployment) <= set(endpoint['supported_parameters'])
            or any(Decimal(str(endpoint['pricing'].get(k, 0))) > Decimal(str(caps[k]))/(1 if k == 'request' else 1_000_000)
                   for k in ('prompt', 'completion', 'request'))):
        raise ValueError('Provider context, availability, parameters or price changed')
    return {k: endpoint[k] for k in ('tag', 'provider_name', 'context_length', 'pricing', 'supported_parameters')}


def archive_sources(directory, manifest):
    for path, expected in manifest.items():
        if sha(path) != expected: raise ValueError('Code changed while freezing remote plan')
        target = directory/'frozen-code'/path
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)


def check_admission(gate, deployment, admission_file, materials, policy, *, discovery_mode='literal'):
    prior_admission(gate, deployment, admission_file, discovery_mode, 'raw')
    required = {'G1': (), 'G2': ('G1',), 'G3': ('G1', 'G2'), 'G4': ('G1', 'G2', 'G3')}[gate]
    if not required: return
    manifest = read_json(admission_file)
    for stage in required:
        previous = read_json(Path(manifest['gates'][stage]['run'])/'plan.json')
        if (previous['artifact_kind'] != VERSION or previous['spend_policy'] != policy
                or previous['extraction_protocol'] != (compact_claims.PROPOSALS if discovery_mode == 'free' else None)
                or previous.get('assertion_equivalence_protocol') != (candidate_consolidation.BILATERAL if discovery_mode == 'free' else None)
                or previous.get('membership_observation_protocol') != (raw_membership.WORLD_CONTEXT if discovery_mode == 'free' else raw_membership.VERSION)
                or previous.get('source_context_protocol') != (source_context_observations.VERSION if discovery_mode == 'free' else None)
                or previous.get('world_observation_protocol') != (statement_worlds.VERSION if discovery_mode == 'free' else None)
                or previous.get('evidence_observation_protocol') != (raw_membership_verification.QUALIFIED if discovery_mode == 'free' else raw_membership_verification.EXPLAINED)
                or any(previous[k] != materials[k] for k in ('classifier', 'model_files', 'documents', 'selections'))):
            raise ValueError('Qualification uses another remote executor, auxiliary model, evidence or shared budget')


def fixed_scope(gate):
    if gate == 'G1': return synthetic12(), list('ABCDEFGHIJKL'), None
    samples = read_json(SAMPLES); path = Path(samples['snapshot'])
    if sha(path) != samples['snapshot_sha256']:
        raise ValueError('Frozen sample snapshot changed')
    snapshot = load_snapshot(path).snapshot; ids = set(sources(snapshot))
    if len(ids) != 999 or samples['canonical_population'] != 999:
        raise ValueError('Fixed canonical population must remain 999')
    development = samples['development']['source_ids']; holdout = samples['holdout']['source_ids']
    for selected, count in ((development, 24), (holdout, 96)):
        if (not isinstance(selected, list) or len(selected) != count
                or len(set(selected)) != count or not set(selected) <= ids):
            raise ValueError('Fixed unique development/holdout source scope required')
    if set(development) & set(holdout): raise ValueError('Development and holdout must be disjoint')
    scope = sorted(ids) if gate == 'G4' else development if gate == 'G2' else holdout
    return snapshot, list(scope), path


def prepare(directory, deployment, materials_file, spend_policy, maximum_cost_usd, *, gate='G1', admission_file=None, discovery_mode='literal'):
    private(directory); private(materials_file)
    if directory.exists(): raise ValueError('New remote Factory directory required')
    if gate not in ('G1', 'G2', 'G3', 'G4'): raise ValueError('Unknown implementation gate')
    if discovery_mode not in ('literal', 'free'): raise ValueError('Unknown remote discovery mode')
    deployment = openrouter.validate(deployment); policy = validate_spend_policy(spend_policy)
    allocation = openrouter.generation_allocation(deployment, require_explicit=True)
    if units(maximum_cost_usd) <= 0: raise ValueError('Explicit positive run cost ceiling required')
    materials = read_json(materials_file)
    if set(materials) != {'classifier', 'model_files', 'documents', 'selections'}:
        raise ValueError('Pinned classifier, model files and evidence required')
    if admission_file is not None: private(admission_file)
    check_admission(gate, deployment, admission_file, materials, policy, discovery_mode=discovery_mode)
    snapshot, scope, original_path = fixed_scope(gate)
    provider = provider_preflight(deployment)
    fact_checks.live(snapshot.usage.expires_at)
    for document in materials['documents']: fact_checks.live(document['expires_at'])
    if any(sha(p) != h for p, h in materials['model_files'].items()): raise ValueError('Auxiliary model changed')
    profile = acceptance.validate(read_json('tests/fixtures/factory-acceptance-r5.json'), acceptance.R5_DIGEST)
    if gate == 'G1': acceptance.check_scope(profile, gate, len(scope), None)
    elif len(scope) != profile['gates'][gate]['sources']: raise ValueError('Fixed r5 processing count changed')
    if gate == 'G1': write(directory/'snapshot.json', snapshot.to_dict())
    snapshot_path = directory/'snapshot.json' if gate == 'G1' else original_path
    inputs = {str(materials_file): sha(materials_file)}
    if gate != 'G1': inputs[str(SAMPLES)] = sha(SAMPLES)
    if admission_file is not None: inputs[str(admission_file)] = sha(admission_file)
    plan = {'artifact_kind': VERSION, 'run_directory': str(directory.resolve()), 'gate': gate,
            'goal_revision': acceptance.R5, 'acceptance_profile': profile, 'acceptance_profile_sha256': digest(profile),
            'deployment': deployment, 'provider_at_prepare': provider, 'spend_policy': policy,
            'maximum_cost_usd': maximum_cost_usd, 'discovery_mode': discovery_mode, 'membership_mode': 'raw',
            'extraction_protocol': compact_claims.PROPOSALS if discovery_mode == 'free' else None,
            'assertion_equivalence_protocol': candidate_consolidation.BILATERAL if discovery_mode == 'free' else None,
            'membership_observation_protocol': raw_membership.WORLD_CONTEXT if discovery_mode == 'free' else raw_membership.VERSION,
            'source_context_protocol': source_context_observations.VERSION if discovery_mode == 'free' else None,
            'world_observation_protocol': statement_worlds.VERSION if discovery_mode == 'free' else None,
            'evidence_observation_protocol': raw_membership_verification.QUALIFIED if discovery_mode == 'free' else raw_membership_verification.EXPLAINED,
            'verification_contract': raw_membership_verification.FULL_SCOPE,
            'capacity_policy': openrouter.CAPACITY_VERSION, 'provider_margin': openrouter.PROVIDER_MARGIN,
            'generation_allocation': allocation,
            'snapshot': str(snapshot_path), 'snapshot_sha256': sha(snapshot_path),
            'canonical_population': len(sources(snapshot)), 'processing_count': len(scope),
            'sample_file': str(SAMPLES) if gate != 'G1' else None,
            'admission_file': str(admission_file) if admission_file is not None else None,
            'scope_ids': scope, 'expires_at': snapshot.usage.expires_at,
            'inputs': inputs, 'code_sha256': code_hashes(),
            **deepcopy(materials), 'questions': deepcopy(QUESTIONS), 'schedule': deepcopy(minimal_pipeline.SCHEDULE),
            'resource_policy': deepcopy(host_resources.POLICY),
            'limits': {'analysis_seconds': None, 'call_seconds': deployment['call_seconds'],
                       'embedding_seconds': 900, 'fact_batch_seconds': 600},
            'reference_runtime_input': False, 'cross_run_response_reuse': False, 'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    write(directory/'frozen.json', {'plan_sha256': sha(directory/'plan.json')})
    archive_sources(directory, plan['code_sha256'])
    return plan


def validate(directory, plan):
    run_origin(plan, directory, attempt=1)
    if read_json(directory/'frozen.json') != {'plan_sha256': sha(directory/'plan.json')}:
        raise ValueError('Frozen remote plan changed')
    deployment = openrouter.validate(plan['deployment']); validate_spend_policy(plan['spend_policy'])
    allocation = openrouter.generation_allocation(deployment, require_explicit=True)
    profile = acceptance.from_plan(plan)
    if (plan['artifact_kind'] != VERSION or plan['gate'] not in ('G1', 'G2', 'G3', 'G4') or profile is None
            or plan['discovery_mode'] not in ('literal', 'free') or plan['membership_mode'] != 'raw'
            or plan['extraction_protocol'] != (compact_claims.PROPOSALS if plan['discovery_mode'] == 'free' else None)
            or plan.get('assertion_equivalence_protocol') != (candidate_consolidation.BILATERAL if plan['discovery_mode'] == 'free' else None)
            or plan.get('membership_observation_protocol') != (raw_membership.WORLD_CONTEXT if plan['discovery_mode'] == 'free' else raw_membership.VERSION)
            or plan.get('source_context_protocol') != (source_context_observations.VERSION if plan['discovery_mode'] == 'free' else None)
            or plan.get('world_observation_protocol') != (statement_worlds.VERSION if plan['discovery_mode'] == 'free' else None)
            or plan.get('evidence_observation_protocol') != (raw_membership_verification.QUALIFIED if plan['discovery_mode'] == 'free' else raw_membership_verification.EXPLAINED)
            or plan['verification_contract'] != raw_membership_verification.FULL_SCOPE
            or plan['capacity_policy'] != openrouter.CAPACITY_VERSION or plan['provider_margin'] != openrouter.PROVIDER_MARGIN
            or plan.get('generation_allocation') != allocation
            or plan['questions'] != QUESTIONS or plan['schedule'] != minimal_pipeline.SCHEDULE
            or plan['resource_policy'] != host_resources.POLICY or units(plan['maximum_cost_usd']) <= 0
            or plan['reference_runtime_input'] is not False or plan['cross_run_response_reuse'] is not False
            or plan['quality_gate_passed'] is not False
            or plan['limits'] != {'analysis_seconds': None, 'call_seconds': deployment['call_seconds'],
                                  'embedding_seconds': 900, 'fact_batch_seconds': 600}):
        raise ValueError('Frozen remote execution contract changed')
    if plan['gate'] == 'G1': acceptance.check_scope(profile, 'G1', len(plan['scope_ids']), None)
    elif len(plan['scope_ids']) != profile['gates'][plan['gate']]['sources']: raise ValueError('Fixed r5 processing count changed')
    if (plan['code_sha256'] != code_hashes()
            or any(sha(p) != h for group in ('inputs', 'model_files') for p, h in plan[group].items())):
        raise ValueError('Frozen remote code, input or model changed')
    material = {k: plan[k] for k in ('classifier', 'model_files', 'documents', 'selections')}
    admission_file = Path(plan['admission_file']) if plan['admission_file'] is not None else None
    check_admission(plan['gate'], deployment, admission_file, material, plan['spend_policy'], discovery_mode=plan['discovery_mode'])
    expected_snapshot, expected_scope, original_path = fixed_scope(plan['gate'])
    expected_path = directory/'snapshot.json' if plan['gate'] == 'G1' else original_path
    if (Path(plan['snapshot']).resolve() != expected_path.resolve()
            or plan['sample_file'] != (str(SAMPLES) if plan['gate'] != 'G1' else None)
            or plan['scope_ids'] != expected_scope or plan['processing_count'] != len(expected_scope)
            or plan['expires_at'] != expected_snapshot.usage.expires_at
            or plan['canonical_population'] != len(sources(expected_snapshot))): raise ValueError('Fixed remote scope changed')
    loaded = load_snapshot(Path(plan['snapshot']))
    if loaded.sha256 != plan['snapshot_sha256'] or digest(loaded.snapshot.to_dict()) != digest(expected_snapshot.to_dict()):
        raise ValueError('Original fixed snapshot changed')
    fact_checks.live(loaded.snapshot.usage.expires_at)
    for document in plan['documents']: fact_checks.live(document['expires_at'])
    return loaded.snapshot


def run(directory):
    private(directory); check_quota(); started = time.monotonic()
    with experiment_lock(directory), quota_watch():
        plan = read_json(directory/'plan.json'); snapshot = validate(directory, plan)
        plan_sha = sha(directory/'plan.json')
        if (directory/'completed.json').exists():
            report = read_json(directory/'completed.json')
            if (report['plan_sha256'] != plan_sha
                    or report['output_sha256'] != sha(directory/'artifacts/output.json')
                    or report['runtime_sha256'] != sha(directory/'artifacts/runtime.json')):
                raise ValueError('Completed remote artifacts changed')
            return report
        pending = [p for p in (directory/'checkpoints').glob('*.intent.json')
                   if not p.with_name(p.name.replace('.intent.json', '.result.json')).exists()]
        if pending: raise RuntimeError('Pending requests require process and ledger reconciliation')
        policy = plan['spend_policy']
        spending = SpendLedger(Path(policy['ledger']), policy['account_id'], maximum_usd=policy['maximum_usd'],
                               opening_charge_usd=policy['opening_charge_usd'])
        status = spending.summary()
        if status['reserved_calls'] or status['uncertain_calls']:
            raise BudgetExhausted('Shared API charge requires reconciliation before model work')
        time_budget = InferenceBudget(directory/'inference.sqlite', VERSION, limit_seconds=None)
        client = openrouter.Client(plan['deployment'])
        paid_budget = PaidBudget(time_budget, spending, plan_sha256=plan_sha, deployment=plan['deployment'],
                                 maximum_run_usd=plan['maximum_cost_usd'], paid_provider=client.generate,
                                 key_metadata=key_metadata,
                                 local_providers=(framed_embedding.generate, evidence_nli.generate))
        checkpoint = CheckpointRunner(openrouter.Runner(directory, plan, paid_budget, client),
                                     plan['generation_allocation'])
        dispatch = host_resources.RemoteCallGuard()
        attempt = len(list((directory/'attempts').glob('*.started.json')))+1
        origin = run_origin(plan, directory, attempt=attempt)
        write(directory/'attempts'/f'{attempt:04}.started.json', {
            'at': datetime.now(timezone.utc).isoformat(), 'plan_sha256': plan_sha,
            'spending_before': spending.summary(), **origin})
        def save(name, value):
            path = directory/'artifacts'/(name+'.json')
            if not path.resolve().is_relative_to((directory/'artifacts').resolve()):
                raise ValueError('Artifact path left its private run')
            if path.exists():
                if digest(read_json(path)) != digest(value): raise ValueError('Same-plan artifact changed: '+name)
            else: write(path, value)
        def inspect(request):
            dispatch.check()
            check_quota(); return client.measure(request)
        class CheckedRunner:
            def call(self, stage, request):
                measured = inspect(request)
                if not measured['fits']: raise ValueError('Unsplit remote request exceeds its context bound')
                with dispatch.remote_call():
                    result = checkpoint.call(stage, request)
                check_quota()
                if result.get('errors'):
                    # The raw receipt, charge and checkpoint already exist.
                    # Stop every Factory/runtime stage before any follow-up call.
                    save('errors/'+stage+'-'+digest(request)[:20], {
                        'stage': stage, 'request_sha256': digest(request),
                        'result': result, 'automatic_retry': False})
                    raise ModelResponseUnavailable(stage, digest(request), digest(request['data']))
                count = (result.get('usage') or {}).get('prompt_tokens')
                if type(count) is not int or not 0 <= count <= measured['input_upper_bound_tokens']+measured['provider_margin']:
                    raise ValueError('Actual API prompt usage exceeded or omitted its declared bound')
                return result
        def embed(stage, texts):
            dispatch.check()
            check_quota(); path = directory/'artifacts'/('embedding-'+stage+'.json')
            request = {'system': framed_embedding.VERSION, 'data': {'texts': texts, 'output': str(path)},
                       'schema': {}, 'max_tokens': 1}
            result = checkpoint.call('embed-'+stage, request, provider=framed_embedding.generate,
                                     maximum=plan['limits']['embedding_seconds'])
            if result['output'] != str(path) or result['sha256'] != sha(path): raise ValueError('Embedding artifact changed')
            artifact = read_json(path)
            if (artifact['texts_sha256'] != digest(texts) or artifact['model'] != framed_embedding.MODEL
                    or artifact['revision'] != framed_embedding.REVISION or artifact['local_files_only'] is not True):
                raise ValueError('Embedding provenance changed')
            return artifact['vectors']
        def facts(request):
            dispatch.check()
            check_quota()
            return checkpoint.call('facts-'+digest(request)[:20], request, provider=evidence_nli.generate,
                                   maximum=plan['limits']['fact_batch_seconds'])
        try:
            provider = provider_preflight(plan['deployment'])
            write(directory/'attempts'/f'{attempt:04}.provider.json', provider)
            with host_resources.watch(directory/'resources'/f'{attempt:04}', plan['resource_policy'],
                                      host_resources.observe_wsl_host, interrupt=dispatch.request_stop):
                output = minimal_pipeline.process(snapshot, CheckedRunner(), embed, inspect, facts,
                    model=plan['classifier'], documents=plan['documents'], selections=plan['selections'],
                    scope_ids=plan['scope_ids'], save=save, discovery_mode=plan['discovery_mode'],
                    membership_mode=plan['membership_mode'], verification_contract=plan['verification_contract'],
                    extraction_protocol=plan['extraction_protocol'])
                save('output', output)
                runtime = runtime_probe(output['agent_inputs']['bundle'], CheckedRunner(),
                    save_turn=lambda row: save('runtime-turns/'+row['candidate_id']+'/'+row['question_id'], row))
                save('runtime', runtime); runtime_check(runtime, output['agent_inputs']['compiled'], questions=plan['questions'])
            report = {'artifact_kind': VERSION, 'gate': plan['gate'], 'plan_sha256': plan_sha, 'execution_complete': True,
                      'candidates': len(output['candidates']), 'compiled_agents': len(output['agent_inputs']['compiled']['profiles']),
                      'runtime_turns': len(runtime['turns']), 'binding_errors': len(output['errors']),
                      'capacity_holds': len(output['capacity_holds']), 'unextracted': len(output['unextracted_source_ids']),
                      'output_sha256': sha(directory/'artifacts/output.json'), 'runtime_sha256': sha(directory/'artifacts/runtime.json'),
                      'attempt_seconds': time.monotonic()-started, 'same_plan_reused_calls': checkpoint.reused,
                      'spending': spending.summary(), 'run_spending': spending.summary(plan_sha256=plan_sha),
                      'semantic_review_required': True, 'quality_gate_passed': False, 'local_llm_started': False, **origin}
            write(directory/'completed.json', report); return report
        except BaseException as exc:
            write(directory/'attempts'/f'{attempt:04}.failed.json', {
                'exception': type(exc).__name__, 'elapsed_seconds': time.monotonic()-started,
                **({'diagnostic': exc.diagnostic} if isinstance(exc, ModelResponseUnavailable) else {}),
                'spending': spending.summary(), 'budget_after': time_budget.summary()})
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='action', required=True)
    p = commands.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--gate', choices=['G1','G2','G3','G4'], default='G1'); p.add_argument('--admission-file', type=Path)
    p.add_argument('--discovery-mode', choices=['literal', 'free'], default='literal')
    p.add_argument('--deployment-file', type=Path, required=True); p.add_argument('--materials-file', type=Path, required=True)
    p.add_argument('--spend-policy', type=Path, required=True); p.add_argument('--maximum-cost-usd', type=float, required=True)
    p = commands.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            plan = prepare(args.directory, read_json(args.deployment_file), args.materials_file,
                           read_json(args.spend_policy), args.maximum_cost_usd, gate=args.gate,
                           admission_file=args.admission_file, discovery_mode=args.discovery_mode)
            result = {'prepared': str(args.directory), 'gate': plan['gate'], 'sources': len(plan['scope_ids']),
                      'maximum_cost_usd': plan['maximum_cost_usd'], 'inference_calls': 0}
        else: result = run(args.directory)
    except (ModelResponseUnavailable, PendingCallError, BudgetExhausted,
            host_resources.ResourceStopRequested, ValueError, OSError) as exc:
        reason = ('model_response_unavailable' if isinstance(exc, ModelResponseUnavailable)
                  else 'pending_call' if isinstance(exc, PendingCallError)
                  else 'budget_blocked' if isinstance(exc, BudgetExhausted)
                  else 'host_resources' if isinstance(exc, host_resources.ResourceStopRequested)
                  else 'validation_failed' if isinstance(exc, ValueError) else 'io_unavailable')
        print(json.dumps({'status': 'blocked', 'reason': reason, 'directory': str(args.directory),
                          'failure_type': type(exc).__name__,
                          'execution_complete': False, 'automatic_retry': False, 'quality_gate_passed': False,
                          **({'diagnostic': exc.diagnostic} if isinstance(exc, ModelResponseUnavailable) else {})},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
