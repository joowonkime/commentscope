"""Bounded actual-comment development execution, never formal gate admission.

Same Factory, transport, ledger and checkpoints; a distinct immutable artifact
kind prevents development evidence from qualifying formal G2/G3/G4.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / 'src'):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from commentscope.agents.runtime_probe import runtime_probe, runtime_check
from commentscope.factory import acceptance, minimal_pipeline
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot, revalidated_snapshot
from commentscope.providers import host_resources
from commentscope.providers.checkpoint_calls import run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import units
from commentscope.storage import write_json_exclusive as write
from experiments import remote_factory_pipeline as executor

VERSION = 'actual24-development-20261110-v1'
TOOL = 'tools/actual24_development.py'
MAXIMUM = '1.50'


def guard(plan, *, call_seconds=0, allow_expired=False):
    executor.guard(plan, call_seconds=call_seconds, allow_expired=allow_expired)
    if (plan.get('artifact_kind') != VERSION or plan.get('mode') != 'development'
            or plan.get('gate') != 'G2' or plan.get('formal_admission_eligible') is not False
            or plan.get('quality_gate_passed') is not False
            or plan.get('admission_file') is not None
            or not 0 < units(plan['subcap_usd']) <= units(MAXIMUM)
            or not isinstance(plan.get('development_user_request'), str)
            or not plan['development_user_request'].strip()):
        raise ValueError('Explicit actual24 development contract required')


def bound_scope(binding_file):
    original, scope, original_file = executor.fixed_scope('G2')
    snapshot, path, inputs, binding = revalidated_snapshot.bind(
        binding_file, original, sha(original_file), scope)
    if len(scope) != 24:
        raise ValueError('Fixed actual24 source IDs required')
    return snapshot, path, scope, {str(original_file): sha(original_file), **inputs}, binding


def prepare(directory, template_file, auth_file, refresh_file, *, user_request):
    directory = Path(directory)
    for path in (directory, template_file, auth_file, refresh_file):
        executor.private(path)
    if directory.exists():
        raise ValueError('Fresh development directory required')
    template = read_json(template_file)
    if (template.get('artifact_kind') != executor.VERSION or template.get('mode') != 'factory'
            or template.get('gate') != 'G1' or template['code_sha256'] != source_code_hashes()
            or template['classifier'] != executor.model_identity()):
        raise ValueError('Current frozen all-HTTP Factory template required')
    executor.validate(Path(template_file).parent, template)
    snapshot, path, scope, inputs, binding = bound_scope(refresh_file)
    auth = read_json(auth_file)
    plan = deepcopy(template)
    inputs.update(template['inputs'])
    inputs.update({str(template_file): sha(template_file), str(auth_file): sha(auth_file), TOOL: sha(ROOT / TOOL)})
    money = executor.ledger(template['spend_policy'])
    if money.summary()['reserved_calls'] or money.summary()['uncertain_calls']:
        raise ValueError('Existing shared money hold')
    plan.update(artifact_kind=VERSION, mode='development', gate='G2',
        formal_admission_eligible=False, quality_gate_passed=False, admission_file=None,
        development_user_request=user_request, run_directory=str(directory.resolve()),
        authorization={'file':str(auth_file), 'sha256':sha(auth_file), 'authorization':auth},
        subcap_usd=MAXIMUM, opening_scope_charge_usd=money.summary(
            plan_sha256=auth['money_owner']['sha256'])['charged_usd'],
        snapshot=str(path), snapshot_sha256=sha(path), scope_ids=scope, scope_refresh=binding,
        processing_count=24, canonical_population=len(executor.sources(snapshot)),
        expires_at=snapshot.usage.expires_at, inputs=inputs,
        development_execution={'version':VERSION, 'tool_sha256':sha(ROOT / TOOL)})
    guard(plan)
    executor.replay_benchmark(Path(plan['fact_benchmark']).parent, plan, [])
    for document in plan['documents']:
        executor.fact_checks.live(document['expires_at'])
    plan['providers_at_prepare']={'generation':executor.provider_preflight(plan['deployment']),
        'verification':executor.provider_preflight(plan['verification_deployment']),
        'embedding':executor.embedding_preflight()}
    write(directory / 'plan.json', plan)
    write(directory / 'frozen.json', {'plan_sha256':sha(directory / 'plan.json')})
    executor.archive_sources(directory, plan['code_sha256'])
    executor.archive_sources(directory, {TOOL:sha(ROOT / TOOL)})
    validate(directory)
    return plan


def validate(directory, *, allow_expired=False):
    directory = Path(directory)
    executor.private(directory)
    plan = read_json(directory / 'plan.json')
    if (read_json(directory / 'frozen.json') != {'plan_sha256':sha(directory / 'plan.json')}
            or plan['code_sha256'] != source_code_hashes()
            or any(sha(path) != expected for path, expected in plan['inputs'].items())
            or plan.get('development_execution') != {'version':VERSION, 'tool_sha256':sha(ROOT / TOOL)}
            or plan['resource_policy'] != host_resources.HTTP_API_POLICY
            or plan['artifact_storage_policy'] != executor.api_resources.STORAGE_POLICY
            or plan['billing_policy'] != executor.remote.WIRE_BUDGET
            or plan['classifier'] != executor.model_identity() or plan['model_files'] != {}
            or plan['argument_audit_protocol'] != executor.argument_observations.TYPED_CHAT
            or plan['agent_source_policy'] != 'verified_subset'
            or plan['membership_retrieval_policy'] != executor.candidate_hierarchy.VERSION
            or plan['verification_contract'] != executor.raw_membership_verification.FULL_SCOPE
            or plan['extraction_protocol'] != executor.compact_claims.PROPOSALS
            or plan['questions'] != executor.QUESTIONS or plan['schedule'] != minimal_pipeline.SCHEDULE
            or plan['reference_runtime_input'] is not False or plan['cross_run_response_reuse'] is not False):
        raise ValueError('Frozen actual24 implementation or policy changed')
    guard(plan, allow_expired=allow_expired)
    run_origin(plan, directory, attempt=1)
    snapshot, path, scope, _, binding = bound_scope(plan['scope_refresh']['file'])
    if (plan['scope_ids'] != scope or plan['scope_refresh'] != binding
            or plan['snapshot'] != str(path) or plan['snapshot_sha256'] != sha(path)
            or plan['processing_count'] != 24 or plan['canonical_population'] != len(executor.sources(snapshot))):
        raise ValueError('Fixed actual24 snapshot changed')
    acceptance.check_scope(acceptance.from_plan(plan), 'G2', 24, 19)
    executor.replay_benchmark(Path(plan['fact_benchmark']).parent, plan, [])
    if 'torch' in sys.modules or 'transformers' in sys.modules:
        raise ValueError('Local model runtime imported')
    return plan


def run(directory):
    directory = Path(directory)
    with experiment_lock(directory), executor.quota_watch():
        plan = validate(directory)
        if (directory / 'completed.json').exists():
            done = read_json(directory / 'completed.json')
            if (done.get('artifact_kind') != VERSION or done.get('formal_admission_eligible') is not False
                    or done['plan_sha256'] != sha(directory / 'plan.json')
                    or done['output_sha256'] != sha(directory / 'artifacts/output.json')
                    or done['runtime_sha256'] != sha(directory / 'artifacts/runtime.json')):
                raise ValueError('Completed development artifacts changed')
            return done
        attempt = len(list((directory / 'attempts').glob('*.started.json'))) + 1
        origin = run_origin(plan, directory, attempt=attempt)
        dispatch = host_resources.RemoteCallGuard()
        session = executor.RemoteSession(directory, plan, dispatch, authorization_guard=guard)
        write(directory / 'attempts' / f'{attempt:04}.started.json',
            {'at':datetime.now(timezone.utc).isoformat(), **origin})

        def save(name, value):
            path = directory / 'artifacts' / (name + '.json')
            if not path.resolve().is_relative_to((directory / 'artifacts').resolve()):
                raise ValueError('Foreign artifact path')
            if path.exists():
                if read_json(path) != value:
                    raise ValueError('Same-plan artifact changed')
            else:
                session.storage.before_write(value)
                write(path, value)
        try:
            for deployment in (plan['deployment'], plan['verification_deployment']):
                executor.provider_preflight(deployment)
            executor.embedding_preflight()
            with host_resources.watch(directory / 'resources' / f'{attempt:04}', plan['resource_policy'],
                    host_resources.observe_wsl_host, interrupt=dispatch.request_stop, workload='http_api'):
                snapshot = load_snapshot(Path(plan['snapshot'])).snapshot
                output = minimal_pipeline.process(snapshot, session, session.embed, session.inspect,
                    lambda request:session.call('facts-' + digest(request)[:20], request),
                    model=plan['classifier'], documents=plan['documents'], selections=plan['selections'],
                    scope_ids=plan['scope_ids'], save=save, discovery_mode='free', membership_mode='raw',
                    verification_contract=plan['verification_contract'], extraction_protocol=plan['extraction_protocol'],
                    argument_audit_protocol=plan['argument_audit_protocol'], agent_source_policy=plan['agent_source_policy'],
                    membership_retrieval_policy=plan['membership_retrieval_policy'])
                save('output', output)
                runtime = runtime_probe(output['agent_inputs']['bundle'], session,
                    save_turn=lambda row:save('runtime-turns/' + row['candidate_id'] + '/' + row['question_id'], row))
                save('runtime', runtime)
                runtime_check(runtime, output['agent_inputs']['compiled'], questions=plan['questions'])
            done={'artifact_kind':VERSION, 'execution_complete':True,
                'formal_admission_eligible':False, 'quality_gate_passed':False,
                'plan_sha256':sha(directory / 'plan.json'),
                'compiled_agents':len(output['agent_inputs']['compiled']['profiles']),
                'runtime_turns':len(runtime['turns']), 'binding_errors':len(output['errors']),
                'capacity_holds':len(output['capacity_holds']), 'unextracted':len(output['unextracted_source_ids']),
                'output_sha256':sha(directory / 'artifacts/output.json'),
                'runtime_sha256':sha(directory / 'artifacts/runtime.json'),
                'spending':session.money.summary(),
                'run_spending':session.money.summary(plan_sha256=plan['spend_scope_sha256']), **origin}
            write(directory / 'completed.json', done)
            return done
        except BaseException as error:
            write(directory / 'attempts' / f'{attempt:04}.failed.json',
                {'exception':type(error).__name__, 'spending':session.money.summary()})
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_subparsers(dest='action', required=True)
    p=actions.add_parser('prepare')
    p.add_argument('directory', type=Path)
    for name in ('template', 'authorization', 'scope-refresh'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--user-request', required=True)
    p=actions.add_parser('run')
    p.add_argument('directory', type=Path)
    p.add_argument('--key-file', type=Path, required=True)
    p.add_argument('--live', action='store_true', required=True)
    args=parser.parse_args()
    if args.action=='prepare':
        plan=prepare(args.directory, args.template, args.authorization, args.scope_refresh, user_request=args.user_request)
        print(json.dumps({'prepared':str(args.directory), 'scope':len(plan['scope_ids']),
            'maximum_usd':plan['subcap_usd'], 'formal_admission_eligible':False, 'new_model_calls':0}))
        return
    os.environ['OPENROUTER_API_KEY']=args.key_file.read_text().strip()
    done=run(args.directory)
    print(json.dumps({key:done[key] for key in ('execution_complete','compiled_agents','runtime_turns',
        'binding_errors','formal_admission_eligible','spending','run_spending')}))


if __name__=='__main__':
    main()
