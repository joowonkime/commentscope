"""Frozen synthetic S1/S2 diagnostic; execution never grants semantic admission."""
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from pathlib import Path
import re

from commentscope.factory import compact_claims as compact, source_interpretation as si
from commentscope.factory import source_semantics as semantics, minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.file_integrity import source_code_hashes
from commentscope.providers import openrouter
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner, run_origin
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import PaidBudget, SpendLedger, units
from commentscope.storage import write_json_exclusive as write
from experiments.openrouter_factory_pipeline import provider_preflight, archive_sources
from experiments.openrouter_factory_probe import private, validate_spend_policy, key_metadata

VERSION = 'source-semantics-diagnostic-20261105-v1'
CYCLE_VERSION = 'commentscope-autonomous-cycle-20261105-v1'
FIXTURE = Path('tests/fixtures/source-semantics-diagnostic.json')


def fixture():
    return read_json(FIXTURE)


def cycle_guard(cycle, *, call_seconds=0, allow_expired=False):
    if (cycle.get('version') != CYCLE_VERSION or 'TASK-004' not in cycle.get('tasks', [])
            or not 0 < units(cycle['maximum_additional_usd']) <= units('5')):
        raise ValueError('Explicit bounded cycle authorization required')
    start = datetime.fromisoformat(cycle['started_at'])
    end = datetime.fromisoformat(cycle['deadline'])
    now = datetime.now(timezone.utc)
    if (start.utcoffset() is None or end.utcoffset() is None
            or not timedelta(0) < end-start <= timedelta(hours=7)):
        raise ValueError('At most seven hours with explicit timezone required')
    if not allow_expired and not start <= now < end-timedelta(seconds=call_seconds+3):
        raise TimeoutError('Cycle deadline cannot cover another bounded operation')


def control_interpretation(case):
    """Author-specified review input; not a model extraction or a support."""
    source = case['source']; text = mc.normalize(case['proposal'])
    proposal = {'id': mc.claim_id(text), 'text': text, 'source_id': source['id'],
                'source_sha256': digest(source), 'record_id': 'ME'+digest({
                    'authored_review_control': case['id'], 'source': source, 'proposal': text}),
                'authorship': 'asserted', 'evidence': mc.validate_source(source),
                'essential_conditions': []}
    return si.bind(source, proposal)


def control_outcome(case, review):
    declaration = review['decisions'][0]['declaration']
    observed = {**declaration, 'nomination_eligible': review['decisions'][0]['nomination_eligible']}
    return {'id': case['id'], 'expected': case['expected'], 'observed': observed,
            'pass': all(type(observed.get(k)) is type(v) and observed.get(k) == v
                        for k, v in case['expected'].items()),
            'review': review, 'authored_control_not_generated_extraction': True}


def prepare(directory, cycle_file):
    private(directory); private(cycle_file)
    cycle = read_json(cycle_file); cycle_guard(cycle)
    deployment = openrouter.validate(cycle['selected_deployment'])
    allocation = openrouter.generation_allocation(deployment, require_explicit=True)
    policy = validate_spend_policy(read_json(Path(cycle['shared_policy_file'])))
    inputs = fixture(); ids = []
    for source in inputs['sources']:
        mc.validate_source(source); ids.append(source['id'])
    if len(ids) != len(set(ids)): raise ValueError('Unique fixed source IDs required')
    for ident in ids+[c['id'] for c in inputs['controls']]:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', ident): raise ValueError('Safe fixture IDs required')
    if len({c['id'] for c in inputs['controls']}) != len(inputs['controls']):
        raise ValueError('Unique control IDs required')
    requests = [compact.request(s, protocol=compact.TRACED_PROPOSALS) for s in inputs['sources']]
    requests += [si.review_request([control_interpretation(c)], protocol=si.TYPED_REVIEW)
                 for c in inputs['controls']]
    client = openrouter.Client(deployment)
    if any(not client.measure(r)['fits'] for r in requests):
        raise ValueError('Frozen requests exceed provider context')
    prices = openrouter.billing_prices(deployment)
    maximum_output = max([r['max_tokens'] for r in requests]+[4096])+allocation['reasoning_budget']
    reservation = ((Decimal(deployment['context'])*Decimal(str(prices['prompt']))
                    +maximum_output*Decimal(str(prices['completion'])))/1_000_000
                   +Decimal(str(prices['request'])))
    if units(reservation) > units(cycle['maximum_additional_usd']):
        raise ValueError('Cycle cannot cover one maximum request reservation')
    provider = provider_preflight(deployment)
    if directory.exists(): raise ValueError('New diagnostic directory required')
    plan = {'artifact_kind': VERSION, 'run_directory': str(directory.resolve()),
            'cycle_file': str(cycle_file.resolve()), 'spend_scope_sha256': sha(cycle_file),
            'cycle': cycle, 'spend_policy': policy, 'deployment': deployment,
            'provider_at_prepare': provider, 'generation_allocation': allocation,
            'inputs': inputs, 'inputs_sha256': digest(inputs),
            'extraction_request_sha256s': [digest(r) for r in requests[:len(ids)]],
            'max_requests': len(inputs['controls'])+3*len(ids),
            'maximum_request_reservation_usd': str(reservation),
            'maximum_cost_usd': cycle['maximum_additional_usd'],
            'code_sha256': source_code_hashes(), 'cross_run_response_reuse': False,
            'quality_gate_passed': False, 'limits': {'call_seconds': deployment['call_seconds'],
                                                    'analysis_seconds': None}}
    write(directory/'plan.json', plan)
    write(directory/'frozen.json', {'plan_sha256': sha(directory/'plan.json')})
    archive_sources(directory, plan['code_sha256'])
    return plan


def validate(directory):
    private(directory); plan = read_json(directory/'plan.json')
    run_origin(plan, directory, attempt=1)
    cycle_file = Path(plan['cycle_file']); cycle = read_json(cycle_file)
    if (plan.get('artifact_kind') != VERSION
            or read_json(directory/'frozen.json') != {'plan_sha256': sha(directory/'plan.json')}
            or plan['spend_scope_sha256'] != sha(cycle_file) or plan['cycle'] != cycle
            or plan['maximum_cost_usd'] != cycle['maximum_additional_usd']
            or plan['deployment'] != cycle['selected_deployment']
            or plan['inputs_sha256'] != digest(plan['inputs']) or plan['inputs'] != fixture()
            or plan['code_sha256'] != source_code_hashes()
            or plan['max_requests'] != len(plan['inputs']['controls'])+3*len(plan['inputs']['sources'])
            or plan['quality_gate_passed'] is not False):
        raise ValueError('Frozen diagnostic plan, cycle, inputs or code changed')
    cycle_guard(cycle, allow_expired=(directory/'completed.json').exists())
    if plan['spend_policy'] != validate_spend_policy(read_json(Path(cycle['shared_policy_file']))):
        raise ValueError('Shared account policy changed')
    return plan


def publish(path, value):
    if path.exists():
        if read_json(path) != value: raise ValueError('Existing diagnostic artifact changed')
    else: write(path, value)


def run(directory):
    with experiment_lock(directory):
        plan = validate(directory); plan_sha = sha(directory/'plan.json')
        if (directory/'completed.json').exists():
            report = read_json(directory/'completed.json')
            if (report['plan_sha256'] != plan_sha
                    or report['source_records_sha256'] != sha(directory/'source-records.json')
                    or report['control_results_sha256'] != sha(directory/'control-results.json')):
                raise ValueError('Completed diagnostic changed')
            return report
        if (directory/'stopped.json').exists():
            raise RuntimeError('Stopped diagnostic requires review, never an automatic paid retry')
        provider_preflight(plan['deployment'])
        policy = plan['spend_policy']
        ledger = SpendLedger(policy['ledger'], policy['account_id'], maximum_usd=policy['maximum_usd'],
                             opening_charge_usd=policy['opening_charge_usd'])
        attempt = len(list((directory/'preflight').glob('*.json')))+1
        write(directory/'preflight'/f'{attempt:04}.json', {
            'key': key_metadata(), 'shared': ledger.summary(),
            'cycle': ledger.summary(plan_sha256=plan['spend_scope_sha256'])})
        client = openrouter.Client(plan['deployment'])
        budget = PaidBudget(InferenceBudget(directory/'inference.sqlite', VERSION, limit_seconds=None), ledger,
                            plan_sha256=plan_sha, deployment=plan['deployment'],
                            maximum_run_usd=plan['maximum_cost_usd'], paid_provider=client.generate,
                            key_metadata=key_metadata, spend_scope_sha256=plan['spend_scope_sha256'])
        runner = CheckpointRunner(openrouter.Runner(directory, plan, budget, client),
                                  plan['generation_allocation'])
        logical_requests = 0
        def call(stage, request):
            nonlocal logical_requests
            cycle_guard(plan['cycle'], call_seconds=plan['limits']['call_seconds'])
            logical_requests += 1
            if logical_requests > plan['max_requests']: raise RuntimeError('Frozen request count exceeded')
            if not client.measure(request)['fits']: raise ValueError('Provider context capacity exceeded')
            result = runner.call(stage, request)
            if result.get('errors'): raise RuntimeError('First diagnostic result failed: '+stage)
            print(json.dumps({'stage': stage, 'cost_usd': result.get('usage', {}).get('cost'),
                              'cycle_charged_usd': ledger.summary(
                                  plan_sha256=plan['spend_scope_sha256'])['charged_usd']}), flush=True)
            return result
        try:
            controls = []
            for case in plan['inputs']['controls']:
                interpretations = [control_interpretation(case)]
                result = call('control-'+case['id'], si.review_request(interpretations, protocol=si.TYPED_REVIEW))
                review = si.bind_review(interpretations, result, protocol=si.TYPED_REVIEW)
                outcome = control_outcome(case, review)
                publish(directory/('control-'+case['id']+'.json'), outcome); controls.append(outcome)
                if not outcome['pass']: raise RuntimeError('Semantic control failed: '+case['id'])
            records = []
            for source in plan['inputs']['sources']:
                result = call('extract-'+source['id'], compact.request(source, protocol=compact.TRACED_PROPOSALS))
                extraction = compact.bind(source, result, protocol=compact.TRACED_PROPOSALS)
                publish(directory/('extraction-'+source['id']+'.json'), extraction)
                if extraction['status'] == 'partial': raise RuntimeError('Source partial; no continuation in this diagnostic')
                interpretations = [c['source_interpretation'] for c in extraction['claims']]
                reviews = []
                for offset in range(0, len(interpretations), si.REVIEW_BATCH_SIZE):
                    group = interpretations[offset:offset+si.REVIEW_BATCH_SIZE]
                    result = call('review-'+source['id']+'-'+str(offset), si.review_request(group, protocol=si.TYPED_REVIEW))
                    reviews.append(si.bind_review(group, result, protocol=si.TYPED_REVIEW))
                record = semantics.bind(extraction, reviews, snapshot_sha256=plan['inputs_sha256'])
                semantics.validate(record, snapshot_sha256=plan['inputs_sha256'], source=source)
                publish(directory/('record-'+source['id']+'.json'), record); records.append(record)
            publish(directory/'source-records.json', records)
            publish(directory/'control-results.json', controls)
            report = {'artifact_kind': VERSION, 'plan_sha256': plan_sha,
                      'source_records_sha256': sha(directory/'source-records.json'),
                      'control_results_sha256': sha(directory/'control-results.json'),
                      'generated_sources': len(records), 'controls_passed': len(controls),
                      'new_requests': runner.base.seq, 'same_plan_reused_calls': runner.reused,
                      'spending_scope': ledger.summary(plan_sha256=plan['spend_scope_sha256']),
                      'shared_spending': ledger.summary(), 'key_after': key_metadata(),
                      'quality_gate_passed': False, 'semantic_review_required': True,
                      'cost_saving_adopted': False}
            write(directory/'completed.json', report)
            return report
        except BaseException as exc:
            write(directory/'stopped.json', {'exception_type': type(exc).__name__,
                  'logical_requests': logical_requests, 'spending_scope': ledger.summary(
                      plan_sha256=plan['spend_scope_sha256']), 'quality_gate_passed': False})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    p = actions.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--cycle-file', type=Path, required=True)
    p = actions.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = prepare(args.directory, args.cycle_file) if args.action == 'prepare' else run(args.directory)
    print(json.dumps(result if args.action == 'run' else {
        'prepared': str(args.directory), 'max_requests': result['max_requests'],
        'maximum_request_reservation_usd': result['maximum_request_reservation_usd']}, ensure_ascii=False))
