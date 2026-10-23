"""Cached comparison of neighborhood proposals through the unchanged agent path.

All discovery neighborhoods are eligible before outcomes; no best-two selection,
old membership reuse, source repair, or fact-policy change. Not a fresh-time test.
"""
import argparse
from copy import deepcopy
from functools import cache
import os
from pathlib import Path
import time

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.factory import common_position as common
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.providers.budget import InferenceBudget, BudgetExhausted
from commentscope.storage import write_json_exclusive as write
from experiments import candidate_completion_pipeline as pipeline
from experiments.scoped_discovery_probe import code_hashes

VERSION = 'cached-common-position-product-0.1'
SECONDS = 2400
GENERATION_SECONDS = 900


def prepare(directory, source):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    old = read_json(source/'plan.json'); report = read_json(source/'completed.json')
    if old['artifact_kind'] != pipeline.VERSION or report['artifact_kind'] != pipeline.VERSION:
        raise ValueError('Completed unchanged source pipeline required')
    tasks = read_json(source/'candidate-queue.json')
    if not 1 <= len(tasks) <= 24 or len({t['proposal']['id'] for t in tasks}) != len(tasks):
        raise ValueError('Bounded unique complete neighborhood population required')
    if (len(tasks) != report['queue_candidates']
            or [t['proposal']['id'] for t in tasks] != [o['id'] for o in report['outcomes']]):
        raise ValueError('Cannot select a subset of the completed neighborhood population')
    for field in ('inputs','code_sha256'):
        if any(sha(p) != h for p,h in old[field].items()): raise ValueError('Source execution changed')
    for key in ('bundle','compiled'):
        if sha(source/(key+'.json')) != report[key+'_sha256']: raise ValueError('Source report changed')
    plan = deepcopy(old)
    plan.update(artifact_kind=VERSION, source_directory=str(source), tasks=tasks, fresh_analysis=False,
                common_position_contract=common.VERSION, generation_seconds=GENERATION_SECONDS,
                generation_tokens=common.TOKENS, code_sha256=code_hashes(),
                quality_gate_passed=False, runtime_reference_labels=False,
                baseline_screened_inputs=report['screened_inputs'],
                comparison_scope='cached_original_neighborhoods_new_cores_and_new_membership',
                review_protocol={'review_all_exposed_profiles':True,
                    'review_all_model_positive_originals':True, 'independent_gold':False,
                    'manual_subset_or_repair':False,
                    'acceptance':'At least two distinct, source-faithful profiles with canonical support >=3; '
                        'no polarity/condition/attitude distortion, reason transfer, omitted major fact or fabricated citation. '
                        'Witness proposals are not support counts. Existing benchmark failures remain visible. '
                        'Cached success must be followed by a fresh timed run and all-profile QA/UI.'})
    plan['limits']['analysis_seconds'] = SECONDS
    for name in ('plan.json','completed.json','candidate-queue.json','all-source-analysis.json'):
        plan['inputs'][str(source/name)] = sha(source/name)
    write(directory/'plan.json',plan)
    print({'prepared':True,'neighborhoods':len(tasks),'fresh_analysis':False,
           'analysis_seconds':SECONDS,'generation_seconds':GENERATION_SECONDS},flush=True)


def validate(plan):
    limits = deepcopy(pipeline.LIMITS); limits['analysis_seconds'] = SECONDS
    if (plan['artifact_kind'] != VERSION or plan['limits'] != limits
            or plan['common_position_contract'] != common.VERSION
            or plan['generation_seconds'] != GENERATION_SECONDS or plan['generation_tokens'] != common.TOKENS
            or plan['fresh_analysis'] is not False or plan['runtime_reference_labels'] is not False):
        raise ValueError('Unknown frozen common-position configuration')
    hashed = cache(sha)
    for field in ('inputs','code_sha256','model_files'):
        if any(hashed(p) != h for p,h in plan[field].items()): raise ValueError('Frozen file changed')
    for d in plan['deployments'].values():
        for info in (d['server'],d['models']['baseline']):
            if hashed(info['path']) != info['sha256']: raise ValueError('Deployment changed')
    source = Path(plan['source_directory']); old = read_json(source/'plan.json')
    if plan['tasks'] != read_json(source/'candidate-queue.json'): raise ValueError('Neighborhood population changed')
    for key in ('membership_policy','deployments','budget','classifier','documents','selections',
                'expires_at','profile_extra_tokens','evaluation','ground_selection_contract'):
        if plan[key] != old[key]: raise ValueError('Source policy changed')
    return source


def propose(directory, plan, runner):
    proposals = []; outcomes = []; began = runner.clock()
    with pipeline.owned_server(plan['deployments']['profile'],'baseline',directory/'proposal-server'):
        for task in plan['tasks']:
            seed = task['proposal']; cid = seed['id']
            remaining = GENERATION_SECONDS-(runner.clock()-began)
            if remaining <= 3:
                outcomes.append({'seed_id':cid,'state':'unprocessed_generation_budget'}); continue
            try:
                req = common.invocation(seed)
                result = runner.call('common-position',req,maximum=min(plan['limits']['call_seconds'],remaining-3))
                proposal = common.bind(seed,result)
                state = 'proposed' if proposal is not None else 'model_deferred'
                if proposal is not None: proposals.append(proposal)
                write(directory/'common-proposals'/(cid+'.json'),
                      {'seed_id':cid,'state':state,'result':result,'proposal':proposal})
            except BudgetExhausted: raise
            except (ValueError,TypeError,KeyError,TimeoutError,RuntimeError) as exc:
                state = 'proposal_failed_'+type(exc).__name__
                write(directory/'common-proposals'/(cid+'.json'),{'seed_id':cid,'state':state})
            outcomes.append({'seed_id':cid,'state':state})
    queue = common.queue(proposals)
    write(directory/'proposal-outcomes.json',outcomes); write(directory/'common-queue.json',queue)
    return queue, outcomes


def complete(directory, plan, runner, queue, records):
    bundles = []; outcomes = []; reserved = 0; relations = pipeline.legacy.Relations(runner)
    for p in queue:
        if reserved+len(p['sources']) > plan['limits']['core_relations']:
            outcomes.append({'id':p['id'],'state':'unprocessed_core_capacity'}); continue
        if not runner.allocation.begin(p['id']):
            outcomes.append({'id':p['id'],'state':runner.allocation.refusal}); continue
        reserved += len(p['sources'])
        try:
            bundle,state = pipeline.complete_candidate(p,directory,plan,runner,relations,records)
            if bundle is not None: bundles.append(bundle)
        except BudgetExhausted: raise
        except (TimeoutError,ValueError,TypeError,KeyError,AttributeError,RuntimeError) as exc:
            state = 'candidate_failed_'+type(exc).__name__
            write(directory/'candidates'/p['id']/'failed.json',{'exception_type':type(exc).__name__})
        runner.allocation.finish(state); outcomes.append({'id':p['id'],'state':state})
        write(directory/'candidates'/p['id']/'outcome.json',outcomes[-1])
    bundle = pipeline.merge_bundles(bundles,plan); compiled = compile_inputs(bundle)
    write(directory/'bundle.json',bundle); write(directory/'compiled.json',compiled)
    write(directory/'all-source-analysis.json',list(records.values()))
    write(directory/'relation-call-map.json',relations.trace)
    return outcomes, reserved, compiled


def execute(directory):
    began = time.monotonic(); plan = read_json(directory/'plan.json'); live(plan['expires_at'])
    source = validate(plan)
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    budget = InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'])
    runner = pipeline.CompletionRunner(directory,plan,budget); runner.started = began
    write(directory/'started.json',{'plan_sha256':runner.plan_sha,'fresh_analysis':False,'budget_before':budget.summary()})
    try:
        records = {r['source_id']:r for r in read_json(source/'all-source-analysis.json')}
        queue, proposal_outcomes = propose(directory,plan,runner)
        outcomes,reserved,compiled = complete(directory,plan,runner,queue,records)
        report = {'artifact_kind':VERSION,'fresh_analysis':False,'elapsed_seconds':time.monotonic()-began,
            'proposal_outcomes':proposal_outcomes,'proposed_distinct_contracts':len(queue),
            'outcomes':outcomes,'attempts':runner.allocation.attempts,'completion_attempts':runner.allocation.completions,
            'reserved_core_relations':reserved,'screened_inputs':len(compiled['profiles']),
            'qualified_agents':0,'quality_gate_passed':False,'runtime_reference_labels':False,
            'bundle_sha256':sha(directory/'bundle.json'),'compiled_sha256':sha(directory/'compiled.json'),
            'budget_after':budget.summary()}
        write(directory/'completed.json',report)
        print({k:report[k] for k in ('fresh_analysis','elapsed_seconds','proposed_distinct_contracts',
                                    'screened_inputs','qualified_agents','outcomes')},flush=True)
    except BaseException as exc:
        write(directory/'failed.json',{'exception_type':type(exc).__name__,'elapsed_seconds':time.monotonic()-began,
                                      'quality_gate_passed':False,'budget_after':budget.summary()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command',required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--directory',type=Path,required=True)
    prep.add_argument('--source',type=Path,required=True)
    run = sub.add_parser('run'); run.add_argument('--directory',type=Path,required=True)
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.directory,args.source)
    else: execute(args.directory)
