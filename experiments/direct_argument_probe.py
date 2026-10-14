"""Compare a new post-membership module over the whole frozen candidate queue.

Previously measured membership is reused unchanged, including negatives and
unassessed rows. Unknown candidates remain unknown. No old ground selection,
typing, audit, fact outcome or development label enters the new model calls.
"""
import argparse
from copy import deepcopy
from functools import cache
import os
from pathlib import Path
import time

from commentscope.factory import direct_arguments as direct
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.fact_checks import live
from commentscope.factory.scoped_discovery import verdict
from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.providers.budget import InferenceBudget,BudgetExhausted
from commentscope.storage import write_json_exclusive as write
from experiments import source_span_product_probe as previous
from experiments import direct_argument_completion as downstream
from experiments.scoped_discovery_probe import code_hashes

VERSION='cached-direct-argument-product-0.1'
SECONDS=1200
INFERENCE_SECONDS=600
FOLLOWUP_RESERVE_SECONDS=3000
pipeline=previous.pipeline


def population(source):
    old=read_json(source/'plan.json');report=read_json(source/'completed.json')
    if old['artifact_kind']!=previous.VERSION or report['artifact_kind']!=previous.VERSION:
        raise ValueError('Expected completed frozen span-selection comparison')
    for key in ('bundle','compiled'):
        if sha(source/(key+'.json'))!=report[key+'_sha256']:raise ValueError('Source output changed')
    queue=read_json(source/'selected-queue.json')
    if [p['id'] for p in queue]!=[o['id'] for o in report['outcomes']] or len(queue)!=report['distinct_exact_contracts']:
        raise ValueError('Complete candidate population required')
    trace={r['row_id']:r for r in read_json(source/'relation-call-map.json')}
    selections={}
    for p,o in zip(queue,report['outcomes'],strict=True):
        path=source/'candidates'/p['id']/'membership.json'
        if not path.exists():
            if not o['state'].startswith('unprocessed_'):raise ValueError('Missing measured membership')
            continue
        m=read_json(path);rows=pipeline.source_rows([p],old['membership_policy'])
        for row in rows:row['id']=p['id']+'-'+row['id']
        if m['proposals']!=[p] or m['rows']!=rows or set(m['actual'])!={r['id'] for r in rows}:
            raise ValueError('Source membership population changed')
        bound=pipeline.CoreAdmissionBound(rows)
        for row in rows:
            record=trace[row['id']];actual=m['actual'][row['id']]
            if record['request_sha256']!=digest(row['request']):raise ValueError('Source relation binding changed')
            if record['call_sequence'] is None:
                if actual!='unassessed' or bound.skip_proof(row) is None:raise ValueError('Invalid source upper bound')
            else:
                prefix=f"{record['call_sequence']:04}-"
                files=list((source/'calls').glob(prefix+'*.request.json'))
                if len(files)!=1:raise ValueError('Missing unique source response')
                req=read_json(files[0]);res=read_json(files[0].with_name(files[0].name.replace('.request.','.result.')))
                if req['plan_sha256']!=sha(source/'plan.json') or req['request']!=row['request'] or verdict(res)!=actual:
                    raise ValueError('Cached source response mismatch')
                bound.observe(row,actual)
        selections[p['id']]=m
    return old,queue,selections


def prepare(directory,source):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    old,queue,selections=population(source)
    previous.validate(old)
    plan=deepcopy(old)
    plan.update(artifact_kind=VERSION,source_directory=str(source),tasks=queue,cached_membership=selections,
                direct_argument_contract=direct.VERSION,direct_limits=direct.LIMITS,
                inference_seconds=INFERENCE_SECONDS,followup_reserve_seconds=FOLLOWUP_RESERVE_SECONDS,
                code_sha256=code_hashes(),fresh_analysis=False,runtime_reference_labels=False,
                comparison_scope='all_frozen_candidates_unchanged_membership_new_direct_grounds',
                review_protocol={'all_exposed_profiles':True,'manual_subset_or_repair':False,
                    'old_ground_type_or_fact_results_as_model_inputs':False,'independent_gold':False,
                    'acceptance':'At least two distinct faithful complete profiles, canonical support >=3; '
                        'all exposed profiles reviewed, no missing major fact, ownership or attitude distortion. '
                        'Fresh timing and QA/UI remain separate requirements.'})
    plan['limits']['analysis_seconds']=SECONDS
    paths=[source/n for n in ('plan.json','completed.json','selected-queue.json','relation-call-map.json',
                              'all-source-analysis.json','bundle.json','compiled.json')]
    paths+=list((source/'calls').glob('*.json'))+list((source/'candidates').glob('*/membership.json'))
    plan['inputs'].update({str(p):sha(p) for p in paths})
    write(directory/'plan.json',plan)
    print({'prepared':True,'population':len(queue),'measured_membership':len(selections),
           'minimum_support_candidates':sum(sum(v=='supported' for v in m['actual'].values())>=3 for m in selections.values()),
           'inference_seconds':INFERENCE_SECONDS,'followup_reserve_seconds':FOLLOWUP_RESERVE_SECONDS},flush=True)


def validate(plan):
    limits=deepcopy(pipeline.LIMITS);limits['analysis_seconds']=SECONDS
    if (plan['artifact_kind']!=VERSION or plan['direct_argument_contract']!=direct.VERSION
            or plan['direct_limits']!=direct.LIMITS or plan['limits']!=limits
            or plan['inference_seconds']!=INFERENCE_SECONDS or plan['followup_reserve_seconds']!=FOLLOWUP_RESERVE_SECONDS
            or plan['fresh_analysis'] is not False or plan['runtime_reference_labels'] is not False):
        raise ValueError('Unknown direct argument comparison')
    hashed=cache(sha)
    for field in ('inputs','code_sha256','model_files'):
        if any(hashed(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen files changed')
    old,queue,selections=population(Path(plan['source_directory']))
    if queue!=plan['tasks'] or selections!=plan['cached_membership']:raise ValueError('Cached population changed')
    for key in ('membership_policy','deployments','budget','classifier','documents','selections','expires_at',
                'profile_extra_tokens','evaluation'):
        if plan[key]!=old[key]:raise ValueError('Unchanged policy required')
    for d in plan['deployments'].values():
        for info in (d['server'],d['models']['baseline']):
            if hashed(info['path'])!=info['sha256']:raise ValueError('Deployment changed')


class Runner(pipeline.CompletionRunner):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.initial_charge=self.budget.summary()['charged_seconds']

    def timeout(self,maximum):
        b=self.budget.summary()
        remaining=min(INFERENCE_SECONDS-(b['charged_seconds']-self.initial_charge),
                      b['remaining_seconds']-FOLLOWUP_RESERVE_SECONDS)-3
        if remaining<=0:raise TimeoutError('Direct comparison allowance exhausted; followup reserve retained')
        return min(super().timeout(maximum),remaining)


def run_tasks(directory,plan,runner):
    outcomes=[];bundles=[];relations=pipeline.legacy.Relations(runner)
    for p in plan['tasks']:
        cid=p['id'];m=plan['cached_membership'].get(cid)
        if m is None:state='upstream_membership_unprocessed'
        elif sum(v=='supported' for v in m['actual'].values())<3:state='cached_insufficient_core_support'
        elif not runner.allocation.begin(cid):state=runner.allocation.refusal
        else:
            runner.allocation.begin_completion()
            try:
                bundle,state=downstream.finish(p,m,directory,plan,runner,relations)
                if bundle is not None:bundles.append(bundle)
            except BudgetExhausted:raise
            except (ValueError,TypeError,KeyError,AttributeError,TimeoutError,RuntimeError) as exc:
                state='candidate_failed_'+type(exc).__name__
                write(directory/'candidates'/cid/'failed.json',{'exception_type':type(exc).__name__})
            runner.allocation.finish(state)
        outcomes.append({'id':cid,'state':state})
        write(directory/'candidates'/cid/'outcome.json',outcomes[-1])
    bundle=pipeline.merge_bundles(bundles,plan);compiled=compile_inputs(bundle)
    write(directory/'bundle.json',bundle);write(directory/'compiled.json',compiled)
    write(directory/'relation-call-map.json',relations.trace)
    return outcomes,compiled


def execute(directory):
    started=time.monotonic();plan=read_json(directory/'plan.json');live(plan['expires_at']);validate(plan)
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'])
    runner=Runner(directory,plan,budget);runner.started=started
    write(directory/'started.json',{'plan_sha256':runner.plan_sha,'budget_before':budget.summary()})
    try:
        outcomes,compiled=run_tasks(directory,plan,runner)
        report={'artifact_kind':VERSION,'fresh_analysis':False,'elapsed_seconds':time.monotonic()-started,
                'outcomes':outcomes,'attempts':runner.allocation.attempts,'completion_attempts':runner.allocation.completions,
                'screened_inputs':len(compiled['profiles']),'qualified_agents':0,'quality_gate_passed':False,
                'runtime_reference_labels':False,'bundle_sha256':sha(directory/'bundle.json'),
                'compiled_sha256':sha(directory/'compiled.json'),'budget_after':budget.summary()}
        write(directory/'completed.json',report)
        print({k:report[k] for k in ('elapsed_seconds','screened_inputs','qualified_agents','outcomes')},flush=True)
    except BaseException as exc:
        write(directory/'failed.json',{'exception_type':type(exc).__name__,'elapsed_seconds':time.monotonic()-started,
                                      'quality_gate_passed':False,'budget_after':budget.summary()})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--directory',type=Path,required=True);prep.add_argument('--source',type=Path,required=True)
    run=sub.add_parser('run');run.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.directory,args.source)
    else:execute(args.directory)
