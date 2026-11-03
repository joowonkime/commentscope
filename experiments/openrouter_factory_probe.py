"""Eight synthetic Factory requests on OpenRouter; never a quality admission.

Freeze a new plan instead of rebinding an existing local-model experiment.
The complete batch must fit its explicit price ceiling before any inference.
"""
import argparse
import json
import math
import os
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.file_integrity import source_code_hashes
from commentscope.providers import openrouter
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner, run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.local_llama import NoRedirect
from commentscope.providers.generation_limits import allocate
from commentscope.providers.openrouter_budget import SpendLedger, PaidBudget, units
from commentscope.storage import write_json_exclusive as write
from experiments.compare_backend_discovery import check_quota, quota_watch
from experiments.compare_local_codex import request_pack

VERSION = 'openrouter-factory-development-probe-0.2'


def private(path):
    if not Path(path).resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('Private run directory required')


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def charge_ceiling(deployment, pack):
    allocation = openrouter.generation_allocation(deployment, require_explicit=True)
    prices = deployment.get('provider', {}).get('max_price')
    if not prices or not deployment['provider'].get('only'):
        raise ValueError('Pinned provider and explicit price ceilings required')
    # Reserve the entire declared model context for every input, even though
    # these short synthetic prompts are much smaller. Prices are USD/million.
    return sum((deployment['context'] * prices['prompt']
                + allocate(c['request'], allocation)['max_tokens'] * prices['completion']) / 1_000_000
               + prices['request'] for c in pack['cases'])


def key_metadata():
    key = os.environ.get('OPENROUTER_API_KEY', '').strip()
    if not key: raise ValueError('OPENROUTER_API_KEY is not configured')
    req = Request('https://openrouter.ai/api/v1/key', headers={'Authorization': 'Bearer '+key})
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=30) as response:
        data = json.load(response)['data']
    return {k: data.get(k) for k in ('limit', 'limit_remaining', 'usage')}


def validate_spend_policy(policy):
    if (not isinstance(policy, dict)
            or set(policy) != {'account_id', 'ledger', 'maximum_usd', 'opening_charge_usd'}
            or not isinstance(policy['account_id'], str) or not policy['account_id'].strip()
            or not isinstance(policy['ledger'], str)):
        raise ValueError('Complete shared API spending policy required')
    private(Path(policy['ledger']))
    if units(policy['maximum_usd']) <= 0 or units(policy['opening_charge_usd']) > units(policy['maximum_usd']):
        raise ValueError('Valid shared API limit and opening charge required')
    return dict(policy)


def prepare(directory, deployment, maximum_cost_usd, *, spend_policy=None):
    private(directory)
    deployment = openrouter.validate(deployment); pack = request_pack()
    ceiling = charge_ceiling(deployment, pack)
    if not positive(maximum_cost_usd) or ceiling > maximum_cost_usd:
        raise ValueError('Whole synthetic batch exceeds the explicit cost ceiling')
    if directory.exists(): raise ValueError('New remote experiment directory required')
    write(directory/'requests.json', pack)
    plan = {'artifact_kind': VERSION, 'run_directory': str(directory.resolve()),
            'deployment': deployment, 'request_pack_sha256': sha(directory/'requests.json'),
            'code_sha256': source_code_hashes(), 'maximum_cost_usd': maximum_cost_usd,
            'reserved_charge_ceiling_usd': ceiling, 'cross_run_response_reuse': False,
            'limits': {'call_seconds': deployment['call_seconds'], 'analysis_seconds': None},
            'quality_gate_passed': False, 'source_kind': 'synthetic'}
    if spend_policy is not None:
        plan['spend_policy'] = validate_spend_policy(spend_policy)
    write(directory/'plan.json', plan)
    return {'prepared': str(directory), 'cases': len(pack['cases']),
            'reserved_charge_ceiling_usd': ceiling, 'inference_calls': 0}


def validate(directory):
    private(directory); plan = read_json(directory/'plan.json'); pack = read_json(directory/'requests.json')
    run_origin(plan, directory, attempt=1)
    deployment = openrouter.validate(plan['deployment'])
    if plan.get('spend_policy') is not None: validate_spend_policy(plan['spend_policy'])
    if (plan['artifact_kind'] != VERSION or plan['source_kind'] != 'synthetic'
            or plan['quality_gate_passed'] is not False
            or plan['request_pack_sha256'] != sha(directory/'requests.json')
            or plan['code_sha256'] != source_code_hashes()
            or pack != request_pack() or not positive(plan['maximum_cost_usd'])
            or plan['reserved_charge_ceiling_usd'] != charge_ceiling(deployment, pack)
            or plan['reserved_charge_ceiling_usd'] > plan['maximum_cost_usd']
            or plan['limits'] != {'call_seconds': deployment['call_seconds'], 'analysis_seconds': None}):
        raise ValueError('Frozen remote plan, requests or source code changed')
    return plan, pack


def run(directory):
    check_quota()
    with experiment_lock(directory), quota_watch():
        plan, pack = validate(directory)
        if (directory/'completed.json').exists():
            done = read_json(directory/'completed.json')
            if done['plan_sha256'] != sha(directory/'plan.json') or done['outputs_sha256'] != sha(directory/'outputs.json'):
                raise ValueError('Completed remote artifacts changed')
            return done
        pending = [p for p in (directory/'checkpoints').glob('*.intent.json')
                   if not p.with_name(p.name.replace('.intent.json', '.result.json')).exists()]
        if pending: raise RuntimeError('Pending calls require process and ledger reconciliation')
        metadata = key_metadata()
        remaining = metadata['limit_remaining']
        if type(remaining) not in (int, float) or not math.isfinite(remaining) or remaining < plan['reserved_charge_ceiling_usd']:
            raise ValueError('API key cannot cover the frozen whole-batch price ceiling')
        attempt = len(list((directory/'preflight').glob('*.json')))+1
        write(directory/'preflight'/f'{attempt:04}.json', metadata)
        budget = InferenceBudget(directory/'inference.sqlite', VERSION, limit_seconds=None)
        client = openrouter.Client(plan['deployment']); spending = None
        if plan.get('spend_policy') is not None:
            policy = validate_spend_policy(plan['spend_policy'])
            spending = SpendLedger(Path(policy['ledger']), policy['account_id'],
                                   maximum_usd=policy['maximum_usd'], opening_charge_usd=policy['opening_charge_usd'])
            budget = PaidBudget(budget, spending, plan_sha256=sha(directory/'plan.json'),
                                deployment=plan['deployment'], maximum_run_usd=plan['maximum_cost_usd'],
                                paid_provider=client.generate, key_metadata=key_metadata)
        base = openrouter.Runner(directory, plan, budget, client)
        runner = CheckpointRunner(base, openrouter.generation_allocation(plan['deployment'], require_explicit=True))
        outputs = []; cost = 0
        for case in pack['cases']:
            check_quota()
            result = runner.call('probe-'+case['id'], case['request'])
            if result['errors']: raise RuntimeError('Remote case failed; first result retained: '+case['id'])
            usage = result.get('usage') or {}; charged = usage.get('cost')
            if type(charged) not in (int, float) or not math.isfinite(charged) or charged < 0:
                raise ValueError('Missing API charge; reconcile before further inference')
            cost += charged
            if cost > plan['reserved_charge_ceiling_usd']:
                raise ValueError('Actual charge exceeded its frozen ceiling; evidence retained')
            outputs.append({'id': case['id'], 'result': result})
            print(json.dumps({'case': case['id'], 'cost_usd': charged, 'seconds': result['seconds']}), flush=True)
        write(directory/'outputs.json', outputs)
        report = {'artifact_kind': VERSION, 'plan_sha256': sha(directory/'plan.json'),
                  'outputs_sha256': sha(directory/'outputs.json'), 'cases': len(outputs),
                  'cost_usd': cost, 'key_after': key_metadata(), 'same_plan_reused_calls': runner.reused,
                  'quality_gate_passed': False, 'semantic_review_required': True,
                  'source_kind': 'synthetic', 'local_model_started': False}
        if spending is not None: report['spending'] = spending.summary()
        write(directory/'completed.json', report)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); actions = parser.add_subparsers(dest='action', required=True)
    p = actions.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--deployment-file', type=Path, required=True); p.add_argument('--maximum-cost-usd', type=float, required=True)
    p.add_argument('--spend-policy', type=Path)
    p = actions.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = (prepare(args.directory, read_json(args.deployment_file), args.maximum_cost_usd,
                      spend_policy=read_json(args.spend_policy) if args.spend_policy is not None else None)
              if args.action == 'prepare' else run(args.directory))
    print(json.dumps(result, ensure_ascii=False))
