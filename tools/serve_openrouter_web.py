"""Serve the existing grounded HTTP app with a bounded OpenRouter provider.

Run from the repository root. Preparation spends nothing on inference. Plans,
responses and browser sessions stay under runs; credentials stay in the process.
This entry point does not run Factory or grant its quality gates.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT/'src'):
    if str(path) not in sys.path: sys.path.insert(0, str(path))

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.agents.grounded_web import GroundedApp, GroundedServer
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.file_integrity import source_code_hashes
from commentscope.providers import openrouter
from commentscope.providers.budget import InferenceBudget, BudgetExhausted
from commentscope.providers.checkpoint_calls import CheckpointRunner, PendingCallError, run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import PaidBudget, SpendLedger, units
from commentscope.storage import write_json_exclusive as write
from experiments.openrouter_factory_pipeline import provider_preflight
from experiments.openrouter_factory_probe import key_metadata, private, validate_spend_policy

VERSION = 'openrouter-grounded-web-20261104-v2'


def prepare(directory, bundle_file, deployment, spend_policy, maximum_cost_usd):
    directory, bundle_file = Path(directory), Path(bundle_file)
    private(directory); private(bundle_file)
    if directory.exists(): raise ValueError('New private server plan directory required')
    deployment = openrouter.validate(deployment); policy = validate_spend_policy(spend_policy)
    allocation = openrouter.generation_allocation(deployment, require_explicit=True)
    if units(maximum_cost_usd) <= 0: raise ValueError('Explicit positive server cost ceiling required')
    compile_inputs(read_json(bundle_file))
    provider = provider_preflight(deployment)
    plan = {'artifact_kind': VERSION, 'run_directory': str(directory.resolve()),
            'bundle': str(bundle_file.resolve()), 'bundle_sha256': sha(bundle_file),
            'deployment': deployment, 'provider_at_prepare': provider, 'spend_policy': policy,
            'generation_allocation': allocation,
            'maximum_cost_usd': maximum_cost_usd, 'code_sha256': source_code_hashes(),
            'entrypoint_sha256': sha(Path(__file__)), 'cross_run_response_reuse': False,
            'limits': {'call_seconds': deployment['call_seconds'], 'analysis_seconds': None},
            'quality_gate_passed': False}
    write(directory/'plan.json', plan)
    write(directory/'frozen.json', {'plan_sha256': sha(directory/'plan.json')})
    return plan


def validate(directory):
    directory = Path(directory); private(directory)
    plan = read_json(directory/'plan.json'); run_origin(plan, directory, attempt=1)
    if (read_json(directory/'frozen.json') != {'plan_sha256': sha(directory/'plan.json')}
            or plan['artifact_kind'] != VERSION or plan['quality_gate_passed'] is not False
            or plan['code_sha256'] != source_code_hashes()
            or plan['entrypoint_sha256'] != sha(Path(__file__))
            or units(plan['maximum_cost_usd']) <= 0):
        raise ValueError('Frozen server plan or implementation changed')
    deployment = openrouter.validate(plan['deployment']); validate_spend_policy(plan['spend_policy'])
    if plan.get('generation_allocation') != openrouter.generation_allocation(deployment, require_explicit=True):
        raise ValueError('Frozen server generation allocation changed')
    if plan['limits'] != {'call_seconds': deployment['call_seconds'], 'analysis_seconds': None}:
        raise ValueError('Frozen server deadlines changed')
    bundle_file = Path(plan['bundle']); private(bundle_file)
    if sha(bundle_file) != plan['bundle_sha256']: raise ValueError('Source bundle changed')
    bundle = read_json(bundle_file); compile_inputs(bundle)
    return plan, bundle


def build_app(directory):
    """Caller holds the server-plan lock for the complete HTTP lifetime."""
    directory = Path(directory); plan, bundle = validate(directory)
    if not os.environ.get('OPENROUTER_API_KEY', '').strip():
        raise ValueError('OPENROUTER_API_KEY is not configured')
    pending = [p for p in (directory/'checkpoints').glob('*.intent.json')
               if not p.with_name(p.name.replace('.intent.json', '.result.json')).exists()]
    if pending: raise PendingCallError('Pending request needs reconciliation before restart')
    policy = plan['spend_policy']
    ledger = SpendLedger(Path(policy['ledger']), policy['account_id'],
                         maximum_usd=policy['maximum_usd'], opening_charge_usd=policy['opening_charge_usd'])
    status = ledger.summary()
    if status['reserved_calls'] or status['uncertain_calls']:
        raise BudgetExhausted('Shared API charge needs reconciliation')
    provider_preflight(plan['deployment'])
    plan_sha = sha(directory/'plan.json'); client = openrouter.Client(plan['deployment'])
    base = InferenceBudget(directory/'inference.sqlite', VERSION, limit_seconds=None)
    paid = PaidBudget(base, ledger, plan_sha256=plan_sha, deployment=plan['deployment'],
                      maximum_run_usd=plan['maximum_cost_usd'], paid_provider=client.generate,
                      key_metadata=key_metadata)
    runner = CheckpointRunner(openrouter.Runner(directory, plan, paid, client),
                              plan['generation_allocation'])
    remote = {'status': 'ready'}

    class RemoteApp(GroundedApp):
        def public(self, item):
            state = super().public(item)
            state['remote_status'] = remote['status']
            if remote['status'] != 'ready': state['can_ask'] = False
            return state

    def revalidate():
        if (sha(directory/'plan.json') != plan_sha
                or sha(Path(plan['bundle'])) != plan['bundle_sha256']
                or sha(Path(__file__)) != plan['entrypoint_sha256']
                or source_code_hashes() != plan['code_sha256']):
            raise ValueError('Server inputs or implementation changed')

    def provider(system, data, schema, *, max_tokens):
        revalidate()
        if remote['status'] != 'ready': raise BudgetExhausted('Remote inference is held')
        request = {'system': system, 'data': data, 'schema': schema, 'max_tokens': max_tokens}
        measured = client.measure(request)
        if not measured['fits']: raise ValueError('Runtime request exceeds model context')
        try:
            result = runner.call('runtime', request)
        except BudgetExhausted:
            remote['status'] = 'reconcile_required' if ledger.summary()['uncertain_calls'] else 'budget_exhausted'
            raise
        if result.get('errors') or not isinstance(result.get('output'), dict):
            if ledger.summary()['uncertain_calls']: remote['status'] = 'reconcile_required'
            raise ValueError('No valid completed runtime response; automatic retry disabled')
        tokens = (result.get('usage') or {}).get('prompt_tokens')
        if type(tokens) is not int or not 0 <= tokens <= measured['input_upper_bound_tokens']+measured['provider_margin']:
            raise ValueError('Runtime prompt usage outside its bound')
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result['output'])}}]}

    return RemoteApp(bundle, directory/'sessions', provider=provider, revalidate=revalidate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='action', required=True)
    p = commands.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--bundle-file', type=Path, required=True); p.add_argument('--deployment-file', type=Path, required=True)
    p.add_argument('--spend-policy', type=Path, required=True); p.add_argument('--maximum-cost-usd', required=True)
    p = commands.add_parser('serve'); p.add_argument('directory', type=Path)
    p.add_argument('--experimental', action='store_true', required=True)
    p.add_argument('--port', type=int, default=8766); p.add_argument('--key-file', type=Path)
    args = parser.parse_args(argv)
    try:
        if Path.cwd().resolve() != ROOT: raise ValueError('Run from the repository root')
        if args.action == 'prepare':
            prepare(args.directory, args.bundle_file, read_json(args.deployment_file),
                    read_json(args.spend_policy), args.maximum_cost_usd)
            print(json.dumps({'prepared': str(args.directory), 'inference_calls': 0, 'quality_gate_passed': False}))
        else:
            if args.key_file is not None: os.environ['OPENROUTER_API_KEY'] = args.key_file.read_text().strip()
            with experiment_lock(args.directory):
                plan, _ = validate(args.directory)
                app = build_app(args.directory); server = GroundedServer(app, args.port)
                print(f'Grounded OpenRouter UI: http://127.0.0.1:{server.server_address[1]}', flush=True)
                try: server.serve_forever()
                except KeyboardInterrupt: pass
                finally:
                    server.server_close()
                    if app.busy: print('Finishing the active bounded request before shutdown.', flush=True)
                    # key_metadata has its own 30-second HTTP deadline; the
                    # provider subprocess has a further 3-second cleanup margin.
                    deadline = time.monotonic()+2*(30+plan['limits']['call_seconds']+3)+10
                    while app.busy and time.monotonic() < deadline: time.sleep(.1)
                    if app.busy: raise PendingCallError('Active request shutdown is unconfirmed')
    except (ValueError, OSError, BudgetExhausted, PendingCallError) as exc:
        print(json.dumps({'status': 'blocked', 'failure_type': type(exc).__name__,
                          'automatic_retry': False, 'quality_gate_passed': False}))
        return 2
    return 0


if __name__ == '__main__': raise SystemExit(main())
