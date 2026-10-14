"""Cached original-span selection through the unchanged candidate completion path."""
import argparse
from copy import deepcopy
from functools import cache
import os
from pathlib import Path
import time

from commentscope.factory import source_span_selection as selection
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.fact_checks import live
from commentscope.providers.budget import InferenceBudget,BudgetExhausted
from commentscope.storage import write_json_exclusive as write
from experiments import common_position_probe as previous
from experiments.scoped_discovery_probe import code_hashes

VERSION='cached-source-span-product-0.1'
SECONDS=2400
SELECTION_SECONDS=600
pipeline=previous.pipeline


def prepare(directory,source):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    previous.prepare(directory/'configuration',source)
    plan=read_json(directory/'configuration/plan.json')
    plan.update(artifact_kind=VERSION,source_span_contract=selection.VERSION,
                span_limits=deepcopy(selection.LIMITS),selection_seconds=SELECTION_SECONDS,
                selection_tokens=selection.TOKENS,code_sha256=code_hashes(),
                comparison_scope='same_complete_cached_neighborhoods_original_spans_new_membership',
                review_protocol={**plan['review_protocol'],
                    'literal_copy_is_not_semantic_approval':True,
                    'scope_fields':'No generated scope assertions; immutable sentence and complete original context are judged.',
                    'nominations':'All alleged supporters can be nominated; none is an admission vote.'})
    for key in ('common_position_contract','generation_seconds','generation_tokens'):plan.pop(key)
    plan['inputs'][str(directory/'configuration/plan.json')]=sha(directory/'configuration/plan.json')
    plan['limits']['analysis_seconds']=SECONDS
    write(directory/'plan.json',plan)
    print({'prepared':True,'neighborhoods':len(plan['tasks']),'fresh_analysis':False,
           'selection_seconds':SELECTION_SECONDS,'analysis_seconds':SECONDS},flush=True)


def validate(plan):
    limits=deepcopy(pipeline.LIMITS);limits['analysis_seconds']=SECONDS
    if (plan['artifact_kind']!=VERSION or plan['source_span_contract']!=selection.VERSION
            or plan['span_limits']!=selection.LIMITS or plan['selection_seconds']!=SELECTION_SECONDS
            or plan['selection_tokens']!=selection.TOKENS or plan['limits']!=limits
            or plan['fresh_analysis'] is not False or plan['runtime_reference_labels'] is not False):
        raise ValueError('Unknown frozen span-selection configuration')
    hashed=cache(sha)
    for field in ('inputs','code_sha256','model_files'):
        if any(hashed(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen file changed')
    for d in plan['deployments'].values():
        for info in (d['server'],d['models']['baseline']):
            if hashed(info['path'])!=info['sha256']:raise ValueError('Deployment changed')
    source=Path(plan['source_directory']);old=read_json(source/'plan.json')
    if plan['tasks']!=read_json(source/'candidate-queue.json'):raise ValueError('Neighborhood population changed')
    for key in ('membership_policy','deployments','budget','classifier','documents','selections',
                'expires_at','profile_extra_tokens','evaluation','ground_selection_contract'):
        if plan[key]!=old[key]:raise ValueError('Source policy changed')
    return source


def select(directory,plan,runner):
    proposals=[];outcomes=[];began=runner.clock()
    with pipeline.owned_server(plan['deployments']['profile'],'baseline',directory/'selection-server'):
        for task in plan['tasks']:
            seed=task['proposal'];cid=seed['id'];remaining=SELECTION_SECONDS-(runner.clock()-began)
            if remaining<=3:
                outcomes.append({'seed_id':cid,'state':'unprocessed_selection_budget'});continue
            try:
                rows=selection.inventory(seed);write(directory/'span-inventory'/(cid+'.json'),rows)
                req=selection.invocation(seed)
                result=runner.call('source-span-selection',req,maximum=min(plan['limits']['call_seconds'],remaining-3))
                p=selection.bind(seed,result);state='selected' if p is not None else 'model_deferred'
                if p is not None:proposals.append(p)
                write(directory/'span-selections'/(cid+'.json'),{'seed_id':cid,'state':state,'result':result,'proposal':p})
            except BudgetExhausted:raise
            except (ValueError,TypeError,KeyError,TimeoutError,RuntimeError) as exc:
                state='selection_failed_'+type(exc).__name__
                write(directory/'span-selections'/(cid+'.json'),{'seed_id':cid,'state':state})
            outcomes.append({'seed_id':cid,'state':state})
    queue=selection.queue(proposals)
    write(directory/'selection-outcomes.json',outcomes);write(directory/'selected-queue.json',queue)
    return queue,outcomes


def execute(directory):
    began=time.monotonic();plan=read_json(directory/'plan.json');live(plan['expires_at']);source=validate(plan)
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'])
    runner=pipeline.CompletionRunner(directory,plan,budget);runner.started=began
    write(directory/'started.json',{'plan_sha256':runner.plan_sha,'fresh_analysis':False,'budget_before':budget.summary()})
    try:
        records={r['source_id']:r for r in read_json(source/'all-source-analysis.json')}
        queue,selected=select(directory,plan,runner)
        outcomes,reserved,compiled=previous.complete(directory,plan,runner,queue,records)
        report={'artifact_kind':VERSION,'fresh_analysis':False,'elapsed_seconds':time.monotonic()-began,
                'selection_outcomes':selected,'distinct_exact_contracts':len(queue),'outcomes':outcomes,
                'attempts':runner.allocation.attempts,'completion_attempts':runner.allocation.completions,
                'reserved_core_relations':reserved,'screened_inputs':len(compiled['profiles']),
                'qualified_agents':0,'quality_gate_passed':False,'runtime_reference_labels':False,
                'bundle_sha256':sha(directory/'bundle.json'),'compiled_sha256':sha(directory/'compiled.json'),
                'budget_after':budget.summary()}
        write(directory/'completed.json',report)
        print({k:report[k] for k in ('fresh_analysis','elapsed_seconds','distinct_exact_contracts',
                                    'screened_inputs','qualified_agents','outcomes')},flush=True)
    except BaseException as exc:
        write(directory/'failed.json',{'exception_type':type(exc).__name__,'elapsed_seconds':time.monotonic()-began,
                                      'quality_gate_passed':False,'budget_after':budget.summary()})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--directory',type=Path,required=True);prep.add_argument('--source',type=Path,required=True)
    run=sub.add_parser('run');run.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.directory,args.source)
    else:execute(args.directory)
