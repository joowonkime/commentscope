"""Bounded cached diagnostic of every budget-unprocessed candidate, in order.

Never extends the source fresh-time result, retries rejected candidates, edits
membership, or selects a best subset. All prior screened inputs remain present.
"""
import argparse
from copy import deepcopy
from functools import cache
import os
from pathlib import Path
import time

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.providers.budget import InferenceBudget, BudgetExhausted
from commentscope.storage import write_json_exclusive as write
from experiments import candidate_completion_pipeline as pipeline
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'budget-pending-candidate-diagnostic-0.1'
SECONDS = 1800
SOURCE_FILES = ('plan.json', 'completed.json', 'candidate-queue.json',
                'all-source-analysis.json', 'bundle.json', 'compiled.json')


def pending(queue, report):
    """Select by terminal scheduling status alone, never by review/content."""
    ids = [t['proposal']['id'] for t in queue]
    outcomes = report['outcomes']
    if len(set(ids)) != len(ids) or [o['id'] for o in outcomes] != ids:
        raise ValueError('Complete ordered outcome population required')
    attempted = [a['candidate_id'] for a in report['attempts']]
    eligible = [o['id'] for o in outcomes if o['state'] == 'unprocessed_completion_budget']
    if len(set(attempted)) != len(attempted) or set(attempted) - set(ids) or set(eligible) & set(attempted):
        raise ValueError('Cannot retry an attempted candidate')
    if not 1 <= len(eligible) <= 6:
        raise ValueError('Bounded diagnostic requires one to six pending candidates')
    return [deepcopy(t) for t in queue if t['proposal']['id'] in eligible]


def source_state(source):
    old = read_json(source/'plan.json'); report = read_json(source/'completed.json')
    if old['artifact_kind'] != pipeline.VERSION or report['artifact_kind'] != pipeline.VERSION:
        raise ValueError('Expected completed candidate pipeline')
    if (old['limits'] != pipeline.LIMITS or not report['fresh_analysis']
            or old['ground_selection_contract'] != pipeline.argument_paths.VERSION):
        raise ValueError('Unknown source contract')
    bundle = read_json(source/'bundle.json'); compiled = read_json(source/'compiled.json')
    if (sha(source/'bundle.json') != report['bundle_sha256']
            or sha(source/'compiled.json') != report['compiled_sha256']
            or compile_inputs(bundle) != compiled):
        raise ValueError('Source output changed')
    tasks = pending(read_json(source/'candidate-queue.json'), report)
    if len(compiled['profiles']) + len(tasks) > 6:
        raise ValueError('No manual subset to fit the six-profile product scope')
    return old, report, tasks, bundle


def prepare(directory, source):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    old, report, tasks, _ = source_state(source)
    # New files may be added; every source execution file must remain unchanged.
    for field in ('inputs', 'code_sha256'):
        if any(sha(p) != h for p, h in old[field].items()):
            raise ValueError('Source execution binding changed')
    plan = deepcopy(old)
    plan.update(artifact_kind=VERSION, source_directory=str(source), fresh_analysis=False,
                diagnostic_seconds=SECONDS, tasks=tasks, code_sha256=code_hashes(),
                source_report_sha256=sha(source/'completed.json'),
                base_screened_inputs=report['screened_inputs'],
                quality_gate_passed=False, runtime_reference_labels=False,
                completion_capacity_scope='new_cached_diagnostic_only_not_source_fresh_run',
                review_protocol={
                    'all_merged_profiles': True, 'all_model_positive_core_sources': True,
                    'preserve_scope_conditions_attitude_and_reason_ownership': True,
                    'major_fact_premises_must_remain': True, 'manual_repairs_or_subset': False,
                    'independent_gold': False,
                    'decision': 'Additional faithful inputs motivate generic scheduling comparison; '
                                'low core yield motivates candidate/retrieval/membership diagnosis; '
                                'downstream deferrals motivate argument representation review. '
                                'No result alone approves a fresh MVP.'})
    plan['limits']['analysis_seconds'] = SECONDS
    for name in SOURCE_FILES: plan['inputs'][str(source/name)] = sha(source/name)
    write(directory/'plan.json', plan)
    print({'prepared': True, 'fresh_analysis': False, 'pending_candidates': len(tasks),
           'diagnostic_seconds': SECONDS}, flush=True)


def validate(plan):
    expected = deepcopy(pipeline.LIMITS); expected['analysis_seconds'] = SECONDS
    if (plan['artifact_kind'] != VERSION or plan['limits'] != expected
            or plan['diagnostic_seconds'] != SECONDS or plan['fresh_analysis'] is not False
            or plan['runtime_reference_labels'] is not False):
        raise ValueError('Unknown diagnostic limits')
    hashed = cache(sha)
    for field in ('inputs', 'code_sha256', 'model_files'):
        if any(hashed(p) != h for p, h in plan[field].items()): raise ValueError('Frozen file changed')
    for d in plan['deployments'].values():
        for info in (d['server'], d['models']['baseline']):
            if hashed(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    source = Path(plan['source_directory']); old, report, tasks, bundle = source_state(source)
    for key in ('membership_policy', 'deployments', 'budget', 'classifier', 'documents', 'selections',
                'expires_at', 'profile_extra_tokens', 'evaluation', 'ground_selection_contract'):
        if plan[key] != old[key]: raise ValueError('Cached diagnostic changed a source policy')
    if tasks != plan['tasks'] or sha(source/'completed.json') != plan['source_report_sha256']:
        raise ValueError('Pending population changed')
    return source, report, tasks, bundle


def run_tasks(directory, plan, runner, tasks, records, base):
    relations = pipeline.legacy.Relations(runner); bundles = [base]; outcomes = []
    for task in tasks:
        p = task['proposal']
        if not runner.allocation.begin(p['id']):
            outcomes.append({'id': p['id'], 'state': runner.allocation.refusal}); continue
        try:
            bundle, state = pipeline.complete_candidate(p, directory, plan, runner, relations, records)
            if bundle is not None: bundles.append(bundle)
        except BudgetExhausted: raise
        except (TimeoutError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            state = 'candidate_failed_'+type(exc).__name__
            write(directory/'candidates'/p['id']/'failed.json', {'exception_type': type(exc).__name__})
        runner.allocation.finish(state)
        outcomes.append({'id': p['id'], 'state': state})
        write(directory/'candidates'/p['id']/'outcome.json', outcomes[-1])
    merged = pipeline.merge_bundles(bundles, plan)
    compiled = compile_inputs(merged)
    # Retained base profiles must be byte-for-byte equivalent after compilation.
    profiles = {p['candidate_id']: p for p in compiled['profiles']}
    for p in compile_inputs(base)['profiles']:
        if profiles.get(p['candidate_id']) != p: raise ValueError('Base profile changed')
    write(directory/'bundle.json', merged); write(directory/'compiled.json', compiled)
    write(directory/'relation-call-map.json', relations.trace)
    write(directory/'all-source-analysis.json', list(records.values()))
    return outcomes, compiled


def execute(directory):
    started = time.monotonic(); plan = read_json(directory/'plan.json'); live(plan['expires_at'])
    source, previous, tasks, base = validate(plan)
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'])
    runner = pipeline.CompletionRunner(directory, plan, budget); runner.started = started
    write(directory/'started.json', {'plan_sha256': runner.plan_sha, 'fresh_analysis': False,
                                    'budget_before': budget.summary()})
    try:
        records = {r['source_id']: r for r in read_json(source/'all-source-analysis.json')}
        outcomes, compiled = run_tasks(directory, plan, runner, tasks, records, base)
        report = dict(artifact_kind=VERSION, fresh_analysis=False,
                      diagnostic_seconds=time.monotonic()-started,
                      source_fresh_analysis_seconds=previous['fresh_analysis_seconds'],
                      source_report_sha256=sha(source/'completed.json'),
                      base_screened_inputs=previous['screened_inputs'],
                      screened_inputs=len(compiled['profiles']), qualified_agents=0,
                      quality_gate_passed=False, runtime_reference_labels=False,
                      attempts=runner.allocation.attempts, completion_attempts=runner.allocation.completions,
                      outcomes=outcomes, bundle_sha256=sha(directory/'bundle.json'),
                      compiled_sha256=sha(directory/'compiled.json'), budget_after=budget.summary())
        write(directory/'completed.json', report)
        print({k:report[k] for k in ('fresh_analysis', 'diagnostic_seconds', 'base_screened_inputs',
                                    'screened_inputs', 'qualified_agents', 'outcomes')}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type':type(exc).__name__,
              'elapsed_seconds':time.monotonic()-started, 'quality_gate_passed':False,
              'budget_after':budget.summary()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--directory', type=Path, required=True)
    prep.add_argument('--source', type=Path, required=True)
    run = sub.add_parser('run'); run.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.directory, args.source)
    else: execute(args.directory)
