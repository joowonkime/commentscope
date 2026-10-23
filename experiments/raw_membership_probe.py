"""Frozen Qwen original/parent/candidate diagnostic; no candidate generation.

Stored proposals isolate comparison from extraction. They never become the
Factory's production candidate source. Offline criteria never enter requests.
"""
import argparse
from pathlib import Path
from shutil import copy2
import time

from commentscope.factory import raw_membership as raw, minimal_claims as mc
from commentscope.factory import raw_membership_verification as verification
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.context_capacity import measure
from commentscope.storage import write_json_exclusive as write
from experiments.minimal_factory_pipeline import BASE, CYCLE, private, deployment_check
from experiments.audit_model_compare import owned_server, file_hash
from experiments.fresh_grounded_pipeline import Runner
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.model_selection_20261016 import observe
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'raw-membership-diagnostic-20261017-v1'


def prepare(directory, controls, criteria, verify_prior=None):
    for path in (directory, controls, criteria): private(path)
    if directory.exists(): raise ValueError('New diagnostic directory required')
    data = read_json(controls)
    if set(data) != {'sources', 'candidates', 'pairs'}: raise ValueError('Unlabeled diagnostic inputs required')
    sources = mc.source_index(data['sources']); candidates = {c['id']: mc.validate_candidate(c) for c in data['candidates']}
    if len(candidates) != len(data['candidates']): raise ValueError('Duplicate candidates')
    calls = []; seen = set()
    for pair in data['pairs']:
        sid, cid = pair['source_id'], pair['candidate_id']
        if set(pair) != {'source_id', 'candidate_id'} or (sid, cid) in seen: raise ValueError('Unique pairs required')
        seen.add((sid, cid)); req = raw.request(sources[sid], candidates[cid])
        calls.append({'pair': pair, 'request_sha256': digest(req)})
    prior_paths = []
    if verify_prior is not None:
        private(verify_prior)
        prior_paths = [verify_prior/'output.json', verify_prior/'completed.json', verify_prior/'plan.json']
        completion = read_json(prior_paths[1])
        if (completion['output_sha256'] != sha(prior_paths[0]) or completion['plan_sha256'] != sha(prior_paths[2])
                or completion['binding_errors'] or completion['capacity_holds']):
            raise ValueError('Complete immutable raw baseline required')
        records = read_json(prior_paths[0])['records']
        if len(records) != len(calls): raise ValueError('Complete same-pair baseline required')
        new_calls = []
        for task, record in zip(calls, records):
            raw.validate(record); pair = task['pair']
            if (record['source'] != sources[pair['source_id']] or record['candidate'] != candidates[pair['candidate_id']]
                    or record['request_sha256'] != task['request_sha256']):
                raise ValueError('Baseline original/parent/candidate/request changed')
            if record['passed']:
                for kind, req in [('route', verification.route_request(record['candidate'], sources[min(record['candidate']['nominees'])])),
                                  ('evidence', verification.evidence_request(record))]:
                    new_calls.append({'kind': kind, 'pair': pair, 'request_sha256': digest(req)})
        calls = new_calls
    deployment = read_json(BASE)['deployment']; deployment_check(deployment)
    settings = read_json(CYCLE)
    if settings['limit_seconds'] is not None or settings['analysis_seconds'] is not None: raise ValueError('Existing uncapped ledger required')
    plan = {'artifact_kind': VERSION, 'controls': str(controls), 'criteria': str(criteria),
            'hypothesis': 'Raw source plus parent resolves supported comparisons independently of held normalization; explicit ambiguity/conditions/attribution remain guarded.',
            'deployment': deployment, 'budget': {k: settings[k] for k in ('cycle_id', 'ledger')},
            'limits': {'analysis_seconds': None, 'call_seconds': 600},
            'inputs': {str(p): sha(p) for p in (controls, criteria, BASE, CYCLE, *prior_paths)},
            'code_sha256': code_hashes(), 'calls': calls, 'transport_retries': 0,
            'reference_runtime_input': False, 'full_factory_run': False, 'quality_gate_passed': False}
    if verify_prior is not None:
        plan.update(verification_of_prior=str(verify_prior),
            hypothesis='Separate candidate-only routing and selected-own-evidence verification; reuse immutable exact raw baseline decisions for isolated diagnosis, not fresh Factory evidence.')
    write(directory/'plan.json', plan)
    for name, expected in plan['code_sha256'].items():
        if sha(name) != expected: raise ValueError('Code changed while freezing')
        target = directory/'frozen-code'/name; target.parent.mkdir(parents=True, exist_ok=True); copy2(name, target)
    return {'prepared': True, 'requests': len(calls)}


def run(directory):
    private(directory)
    with experiment_lock(directory):
        plan = read_json(directory/'plan.json')
        if plan['artifact_kind'] != VERSION or (directory/'started.json').exists(): raise ValueError('Frozen fresh diagnostic required')
        for group in ('inputs', 'code_sha256'):
            if any(sha(p) != h for p, h in plan[group].items()): raise ValueError('Frozen input/code changed')
        deployment_check(plan['deployment'])
        for info in (plan['deployment']['server'], plan['deployment']['models']['baseline']):
            if file_hash(info['path']) != info['sha256']: raise ValueError('Model/server changed')
        observation = observe(); write(directory/'preflight.json', observation)
        if observation['refusal_reasons']: raise RuntimeError('Resource preflight refused')
        data = read_json(plan['controls']); sources = mc.source_index(data['sources'])
        candidates = {c['id']: c for c in data['candidates']}
        budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'], limit_seconds=None)
        runner = Runner(directory, plan, budget); started = time.monotonic()
        write(directory/'started.json', {'plan_sha256': sha(directory/'plan.json'), 'budget_before': budget.summary()})
        records = []; errors = []; holds = []
        prior = {}; checks = {}
        if plan.get('verification_of_prior'):
            original_records = read_json(Path(plan['verification_of_prior'])/'output.json')['records']
            prior = {(r['source']['id'], r['candidate']['id']): r for r in original_records}
        try:
            with owned_server(plan['deployment'], 'baseline', directory/'server'):
                for index, task in enumerate(plan['calls']):
                    pair = task['pair']; source, candidate = sources[pair['source_id']], candidates[pair['candidate_id']]
                    key = (source['id'], candidate['id']); kind = task.get('kind', 'raw')
                    origin = sources[min(candidate['nominees'])]
                    req = (verification.route_request(candidate, origin) if kind == 'route' else
                           verification.evidence_request(prior[key]) if kind == 'evidence' else raw.request(source, candidate))
                    if digest(req) != task['request_sha256']: raise ValueError('Frozen call changed')
                    capacity = measure(req); write(directory/'capacity'/f'{index:03}.json', capacity)
                    if not capacity['fits']:
                        holds.append(pair); continue
                    response = runner.call(f'{kind}-{index:03}', req)
                    if response.get('raw') is None and response.get('errors'): raise RuntimeError('Incomplete transport; reconcile ledger before recovery')
                    try:
                        bound = (verification.bind_route(candidate, response, origin) if kind == 'route' else
                                 verification.bind_evidence(prior[key], response) if kind == 'evidence' else raw.bind(source, candidate, response))
                        if kind == 'raw': records.append(bound)
                        else: checks[key, kind] = bound
                        write(directory/'bound'/f'{index:03}.json', bound)
                    except (ValueError, KeyError, TypeError) as exc:
                        errors.append({'pair': pair, 'error': str(exc)})
            if prior:
                records = [verification.assessment(record, checks.get((key, 'route')), checks.get((key, 'evidence')))
                           for key, record in prior.items()]
            write(directory/'output.json', {'records': records, 'errors': errors, 'holds': holds})
            report = {'execution_complete': True, 'plan_sha256': sha(directory/'plan.json'),
                      'output_sha256': sha(directory/'output.json'), 'calls': runner.seq,
                      'binding_errors': len(errors), 'capacity_holds': len(holds),
                      'elapsed_seconds': time.monotonic()-started, 'budget_after': budget.summary(),
                      'full_factory_run': False, 'quality_gate_passed': False}
            write(directory/'completed.json', report)
            return {k: v for k, v in report.items() if k != 'budget_after'}
        except BaseException as exc:
            write(directory/'failed.json', {'exception': type(exc).__name__, 'message': str(exc), 'budget_after': budget.summary()})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('directory', type=Path)
    p.add_argument('--controls', type=Path, required=True); p.add_argument('--criteria', type=Path, required=True)
    p.add_argument('--verify-prior', type=Path)
    p = sub.add_parser('run'); p.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(prepare(args.directory, args.controls, args.criteria, args.verify_prior) if args.action == 'prepare' else run(args.directory), flush=True)
