"""Measure all budget-unprocessed cores before choosing another architecture.

No rejected candidate is retried or repaired. This cached diagnostic cannot
extend the original fresh timing, approve an agent, or reset the cycle budget.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import time

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.core_admission_bound import CoreAdmissionBound
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments import fresh_direct_pipeline as source
from experiments.pending_candidate_probe import pending
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'pending-core-population-diagnostic-0.1'
SECONDS = 1200
INFERENCE_SECONDS = 600
FOLLOWUP_SECONDS = 600


def population(directory):
    plan = read_json(directory/'plan.json'); report = read_json(directory/'completed.json')
    if plan['artifact_kind'] != source.VERSION or report['artifact_kind'] != source.VERSION:
        raise ValueError('Completed fresh direct diagnostic required')
    for key in ('bundle', 'compiled'):
        if sha(directory/(key+'.json')) != report[key+'_sha256']:
            raise ValueError('Source result changed')
    queue = [{'proposal': p} for p in read_json(directory/'selected-queue.json')]
    tasks = pending(queue, report)
    if sum(len(t['proposal']['sources']) for t in tasks) > 48:
        raise ValueError('Whole pending population exceeds diagnostic capacity')
    return plan, report, tasks


def prepare(directory, previous):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    old, report, tasks = population(previous); source.validate(old)
    plan = deepcopy(old)
    plan.update(artifact_kind=VERSION, source_directory=str(previous), tasks=tasks,
                inference_seconds=INFERENCE_SECONDS, followup_seconds=FOLLOWUP_SECONDS,
                fresh_analysis=False, quality_gate_passed=False, runtime_reference_labels=False,
                code_sha256=code_hashes(), base_screened_inputs=report['screened_inputs'],
                purpose='all_unprocessed_core_measurement_no_repair_or_agent_approval')
    plan['limits']['analysis_seconds'] = SECONDS
    for name in ('plan.json','completed.json','selected-queue.json','bundle.json','compiled.json'):
        path = previous/name; plan['inputs'][str(path)] = sha(path)
    write(directory/'plan.json', plan)
    print({'prepared': True, 'pending_candidates': len(tasks),
           'inference_seconds': INFERENCE_SECONDS, 'followup_seconds': FOLLOWUP_SECONDS}, flush=True)


def validate(plan):
    old, report, tasks = population(Path(plan['source_directory'])); source.validate(old)
    expected = deepcopy(old['limits']); expected['analysis_seconds'] = SECONDS
    if (plan['artifact_kind'] != VERSION or plan['tasks'] != tasks or plan['limits'] != expected
            or plan['inference_seconds'] != INFERENCE_SECONDS or plan['followup_seconds'] != FOLLOWUP_SECONDS
            or plan['fresh_analysis'] is not False or plan['runtime_reference_labels'] is not False
            or plan['quality_gate_passed'] is not False or plan['base_screened_inputs'] != report['screened_inputs']):
        raise ValueError('Frozen diagnostic contract changed')
    if any(plan[k] != old[k] for k in source.CONFIG_FIELDS):
        raise ValueError('No source policy, deployment, or budget changes allowed')
    for field in ('inputs','code_sha256'):
        if any(sha(p) != h for p,h in plan[field].items()): raise ValueError('Frozen inputs/code changed')


class Runner(source.base.Runner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial_charge = self.budget.summary()['charged_seconds']

    def timeout(self, maximum):
        b = self.budget.summary()
        allowance = min(INFERENCE_SECONDS-(b['charged_seconds']-self.initial_charge),
                        b['remaining_seconds']-FOLLOWUP_SECONDS)-3
        if allowance <= 0: raise TimeoutError('Core allowance exhausted; followup retained')
        return min(super().timeout(maximum), allowance)


def measure(directory, plan, runner):
    relations = source.base.legacy.Relations(runner); outcomes = []; exhausted = False
    for task in plan['tasks']:
        p = task['proposal']; cd = directory/'candidates'/p['id']
        rows = source.base.source_rows([p], plan['membership_policy'])
        for row in rows: row['id'] = p['id']+'-'+row['id']
        bound = CoreAdmissionBound(rows); actual = {}; budget_unprocessed = []
        for row in rows:
            if not exhausted:
                try:
                    # Preflight prevents a phantom call record on budget exhaustion.
                    runner.timeout(plan['limits']['call_seconds'])
                    actual.update(relations.judge([row], 'core-'+p['id'], admission_bound=bound))
                    continue
                except TimeoutError: exhausted = True
            actual[row['id']] = 'unassessed'; budget_unprocessed.append(row['id'])
        supported = sum(v == 'supported' for v in actual.values())
        upper = supported + sum(v == 'unassessed' for v in actual.values())
        state = ('minimum_met_incomplete_not_agent' if supported >= 3 and budget_unprocessed else
                 'core_ready_not_agent' if supported >= 3 else
                 'insufficient_core_support' if upper < 3 else 'unprocessed_core_budget')
        write(cd/'membership.json', {'proposals':[p], 'rows':rows, 'actual':actual,
            'admission_bound':bound.report(), 'budget_unprocessed':budget_unprocessed})
        outcome = {'id':p['id'], 'state':state, 'model_support_count':supported, 'support_upper_bound':upper}
        outcomes.append(outcome); write(cd/'outcome.json', outcome)
    write(directory/'relation-call-map.json', relations.trace)
    return outcomes


def execute(directory):
    plan = read_json(directory/'plan.json'); validate(plan)
    budget = InferenceBudget(Path(plan['budget']['ledger']), plan['budget']['cycle_id'])
    runner = Runner(directory, plan, budget); started = time.monotonic()
    write(directory/'started.json', {'plan_sha256':runner.plan_sha, 'budget_before':budget.summary()})
    try:
        with source.base.owned_server(plan['deployments']['membership'], 'baseline', directory/'server'):
            outcomes = measure(directory, plan, runner)
        report = {'artifact_kind':VERSION, 'fresh_analysis':False, 'quality_gate_passed':False,
            'elapsed_seconds':time.monotonic()-started, 'outcomes':outcomes,
            'new_agents':0, 'base_screened_inputs':plan['base_screened_inputs'],
            'budget_after':budget.summary(), 'runtime_reference_labels':False}
        write(directory/'completed.json', report)
        print({k:report[k] for k in ('elapsed_seconds','outcomes','new_agents')}, flush=True)
    except BaseException as exc:
        write(directory/'failed.json', {'exception_type':type(exc).__name__, 'quality_gate_passed':False,
                                        'budget_after':budget.summary()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare','run']); parser.add_argument('directory', type=Path)
    parser.add_argument('--source', type=Path); args = parser.parse_args()
    if args.phase == 'prepare':
        if args.source is None: parser.error('--source required')
        prepare(args.directory, args.source)
    else: execute(args.directory)
