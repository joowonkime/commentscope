"""Fresh snapshot to source-bound agents through the direct-ground completion path.

This is a product diagnostic, not adoption of a quality-approved configuration.
Every embedding, extraction, selection and source judgment is newly executed.
Historical files supply configuration and failed diagnostic measurements only.
"""
import argparse
from copy import deepcopy
from functools import cache
import os
from pathlib import Path
import time

from commentscope.factory import source_span_selection as spans,direct_arguments as direct
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.automatic_contract import digest
from commentscope.factory.fact_checks import live
from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.providers.budget import InferenceBudget,BudgetExhausted
from commentscope.storage import write_json_exclusive as write
from experiments import candidate_completion_pipeline as base
from experiments import direct_argument_completion as downstream
from experiments.scoped_discovery_probe import code_hashes

VERSION='fresh-direct-ground-product-0.1'
SELECTION_SECONDS=900
QA_RESERVE_SECONDS=360
CONFIG_FIELDS=('membership_policy','budget','classifier','documents','selections','model_files','evaluation',
               'deployments','profile_extra_tokens','argument_control_measurement')


def prepare(directory,snapshot,configuration):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    old=read_json(configuration)
    if old['artifact_kind']!=base.VERSION:raise ValueError('Explicit current candidate configuration required')
    loaded=base.load_snapshot(snapshot)
    if len(loaded.snapshot.comments)>1000:raise ValueError('MVP comment cap exceeded')
    plan={k:deepcopy(old[k]) for k in CONFIG_FIELDS}
    plan.update(artifact_kind=VERSION,snapshot=str(snapshot),expires_at=loaded.snapshot.usage.expires_at,
                inputs={**old['inputs'],str(configuration):sha(configuration),str(snapshot):sha(snapshot)},
                configuration_source=str(configuration),code_sha256=code_hashes(),limits=deepcopy(base.LIMITS),
                retrieval_limits=deepcopy(base.support_retrieval.LIMITS),source_span_contract=spans.VERSION,
                direct_argument_contract=direct.VERSION,span_limits=deepcopy(spans.LIMITS),direct_limits=deepcopy(direct.LIMITS),
                selection_seconds=SELECTION_SECONDS,selection_tokens=spans.TOKENS,qa_reserve_seconds=QA_RESERVE_SECONDS,
                fresh_analysis=True,cross_run_response_reuse=False,runtime_reference_labels=False,quality_gate_passed=False,
                purpose='product_diagnostic_not_default_adoption',
                review_protocol={'all_exposed_profiles':True,'all_positive_originals':True,'independent_gold':False,
                    'manual_subset_or_repair':False,'prior_type_and_membership_failures_retained':True,
                    'acceptance':'At least two distinct complete faithful profiles, canonical support >=3; '
                        'major facts verified, no ownership/polarity/condition distortion or fabricated citation. '
                        'All-profile QA/UI and fixed benchmarks remain separate requirements.'})
    validate(plan)
    write(directory/'plan.json',plan)
    print({'prepared':True,'fresh_analysis':True,'analysis_seconds':3600,
           'selection_seconds':SELECTION_SECONDS,'qa_reserve_seconds':QA_RESERVE_SECONDS},flush=True)


def validate(plan):
    if (plan['artifact_kind']!=VERSION or plan['limits']!=base.LIMITS
            or plan['retrieval_limits']!=base.support_retrieval.LIMITS or plan['source_span_contract']!=spans.VERSION
            or plan['direct_argument_contract']!=direct.VERSION or plan['span_limits']!=spans.LIMITS
            or plan['direct_limits']!=direct.LIMITS or plan['selection_seconds']!=SELECTION_SECONDS
            or plan['selection_tokens']!=spans.TOKENS or plan['qa_reserve_seconds']!=QA_RESERVE_SECONDS
            or plan['fresh_analysis'] is not True or plan['cross_run_response_reuse'] is not False
            or plan['runtime_reference_labels'] is not False or plan['purpose']!='product_diagnostic_not_default_adoption'):
        raise ValueError('Unknown fresh diagnostic contract')
    old=read_json(plan['configuration_source'])
    if any(plan[k]!=old[k] for k in CONFIG_FIELDS):raise ValueError('Source configuration changed')
    if base.product_evaluation.execution_state(plan['evaluation']['source_measurement'],'product_diagnostic')!=plan['evaluation']:
        raise ValueError('Failed relation diagnostic must remain visible')
    hashed=cache(sha)
    for field in ('inputs','code_sha256','model_files'):
        if any(hashed(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen files changed')
    for d in plan['deployments'].values():
        for info in (d['server'],d['models']['baseline']):
            if hashed(info['path'])!=info['sha256']:raise ValueError('Pinned deployment changed')
    loaded=base.load_snapshot(plan['snapshot'])
    if len(loaded.snapshot.comments)>1000 or loaded.snapshot.usage.expires_at!=plan['expires_at']:
        raise ValueError('Snapshot population/expiry changed')
    live(plan['expires_at'])


class Runner(base.CompletionRunner):
    def timeout(self,maximum):
        remaining=self.budget.summary()['remaining_seconds']-QA_RESERVE_SECONDS-3
        if remaining<=0:raise TimeoutError('Preparation allowance exhausted; QA reserve retained')
        return min(super().timeout(maximum),remaining)


def discover(directory,plan,runner):
    path=directory/'fresh-groups.json'
    req={'system':base.fresh_embedding.VERSION,'data':{'snapshot':plan['snapshot'],
         'snapshot_sha256':sha(plan['snapshot']),'output':str(path)},'schema':{},'max_tokens':1}
    embedded=runner.call('embedding',req,provider=base.fresh_embedding.generate,maximum=plan['limits']['embedding_seconds'])
    if embedded['sha256']!=sha(path):raise ValueError('Embedding artifact changed')
    raw=read_json(path);loaded=base.load_snapshot(plan['snapshot'])
    canonical=sorted((c for c in base.normalize_snapshot(loaded.snapshot) if c.duplicate_of is None and c.text_analysis),key=lambda c:c.comment_id)
    sources={sid:r['text'] for sid,r in raw['sources'].items()}
    base.source_index.validate(raw['source_index'],canonical,loaded.sha256,base.MODEL,base.REVISION,sources=sources)
    with base.owned_server(plan['deployments']['extraction'],'baseline',directory/'discovery-server'):
        units,discovered,coverage=base.proposals_from_sources(raw,runner)
    records=read_json(directory/'source-analysis.json')['records']
    req={'system':base.completion_candidates.VERSION,'data':{'units':units,'sources':discovered,
         'threshold':plan['limits']['candidate_threshold']},'schema':{},'max_tokens':1}
    cache_result=runner.call('discovery-candidates',req,provider=base.completion_candidates.generate,maximum=plan['limits']['embedding_seconds'])
    write(directory/'unit-candidates.json',cache_result)
    proposals=cache_result['proposals'][:plan['limits']['discovery_targets']]
    write(directory/'discovery-deferred.json',[{'id':p['id'],'reason':'discovery_target_budget'} for p in cache_result['proposals'][len(proposals):]])
    scheduled=base.support_retrieval.schedule(proposals,units,cache_result,raw['source_index'],sources)
    write(directory/'retrieval-schedule.json',scheduled)
    req={'system':base.target_ranking_nli.VERSION,'data':{'pairs':scheduled['pairs']},'schema':{},'max_tokens':1}
    ranked=runner.call('support-ranking',req,provider=base.target_ranking_nli.generate,maximum=plan['limits']['ranking_seconds'])
    broad=base.support_retrieval.assemble(proposals,units,cache_result,raw['source_index'],sources,scheduled,ranked)
    union=base.support_retrieval.union_nominations(proposals,broad)
    write(directory/'retrieval.json',broad);write(directory/'nominations.json',union)
    queue=base.completion.queue(proposals,broad,union);write(directory/'candidate-queue.json',queue)
    write(directory/'all-source-analysis.json',records)
    return queue,coverage,records


def select(directory,plan,runner,tasks):
    proposals=[];outcomes=[];started=runner.clock()
    with base.owned_server(plan['deployments']['profile'],'baseline',directory/'selection-server'):
        for task in tasks:
            seed=task['proposal'];cid=seed['id'];remaining=SELECTION_SECONDS-(runner.clock()-started)
            if remaining<=3:
                outcomes.append({'seed_id':cid,'state':'unprocessed_selection_budget'});continue
            try:
                write(directory/'span-inventory'/(cid+'.json'),spans.inventory(seed))
                req=spans.invocation(seed)
                result=runner.call('source-span-selection',req,maximum=min(plan['limits']['call_seconds'],remaining-3))
                p=spans.bind(seed,result);state='selected' if p is not None else 'model_deferred'
                if p is not None:proposals.append(p)
                write(directory/'span-selections'/(cid+'.json'),{'seed_id':cid,'state':state,'result':result,'proposal':p})
            except BudgetExhausted:raise
            except (ValueError,TypeError,KeyError,TimeoutError,RuntimeError) as exc:
                state='selection_failed_'+type(exc).__name__
                write(directory/'span-selections'/(cid+'.json'),{'seed_id':cid,'state':state})
            outcomes.append({'seed_id':cid,'state':state})
    queue=spans.queue(proposals);write(directory/'selected-queue.json',queue);write(directory/'selection-outcomes.json',outcomes)
    return queue,outcomes


def complete(directory,plan,runner,queue):
    bundles=[];outcomes=[];reserved=0;relations=base.legacy.Relations(runner)
    for p in queue:
        cid=p['id'];cd=directory/'candidates'/cid
        if reserved+len(p['sources'])>plan['limits']['core_relations']:state='unprocessed_core_capacity'
        elif runner.budget.summary()['remaining_seconds']<QA_RESERVE_SECONDS+base.completion.SLOT_SECONDS:
            state='unprocessed_preparation_budget'
        elif not runner.allocation.begin(cid):state=runner.allocation.refusal
        else:
            reserved+=len(p['sources']);write(cd/'proposal.json',p)
            try:
                rows=base.source_rows([p],plan['membership_policy'])
                for row in rows:row['id']=cid+'-'+row['id']
                bound=base.CoreAdmissionBound(rows)
                with base.owned_server(plan['deployments']['membership'],'baseline',cd/'core-server'):
                    actual=relations.judge(rows,'core-'+cid,admission_bound=bound)
                selection={'proposals':[p],'rows':rows,'actual':actual}
                write(cd/'membership.json',{**selection,'admission_bound':bound.report()})
                if sum(v=='supported' for v in actual.values())<3:state='insufficient_core_support'
                else:
                    runner.allocation.begin_completion()
                    bundle,state=downstream.finish(p,selection,directory,plan,runner,relations)
                    if bundle is not None:bundles.append(bundle)
            except BudgetExhausted:raise
            except (ValueError,TypeError,KeyError,AttributeError,TimeoutError,RuntimeError) as exc:
                state='candidate_failed_'+type(exc).__name__
                write(cd/'failed.json',{'exception_type':type(exc).__name__})
            runner.allocation.finish(state)
        outcomes.append({'id':cid,'state':state});write(cd/'outcome.json',outcomes[-1])
    bundle=base.merge_bundles(bundles,plan);compiled=compile_inputs(bundle)
    write(directory/'bundle.json',bundle);write(directory/'compiled.json',compiled)
    write(directory/'relation-call-map.json',relations.trace)
    return outcomes,reserved,compiled


def execute(directory):
    started=time.monotonic();plan=read_json(directory/'plan.json');validate(plan)
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'])
    runner=Runner(directory,plan,budget);runner.started=started
    write(directory/'started.json',{'plan_sha256':runner.plan_sha,'fresh_analysis':True,'budget_before':budget.summary()})
    try:
        tasks,coverage,records=discover(directory,plan,runner)
        queue,selection_outcomes=select(directory,plan,runner,tasks)
        outcomes,reserved,compiled=complete(directory,plan,runner,queue)
        elapsed=time.monotonic()-started
        report={'artifact_kind':VERSION,'fresh_analysis':True,'fresh_analysis_seconds':elapsed,'within_one_hour':elapsed<=3600,
                'coverage':coverage,'analyzed_unique_sources':len(records),'retrieval_neighborhoods':len(tasks),
                'selection_outcomes':selection_outcomes,'queue_candidates':len(queue),'outcomes':outcomes,
                'attempts':runner.allocation.attempts,'completion_attempts':runner.allocation.completions,
                'reserved_core_relations':reserved,'screened_inputs':len(compiled['profiles']),'qualified_agents':0,
                'quality_gate_passed':False,'runtime_reference_labels':False,
                'bundle_sha256':sha(directory/'bundle.json'),'compiled_sha256':sha(directory/'compiled.json'),
                'budget_after':budget.summary()}
        write(directory/'completed.json',report)
        print({k:report[k] for k in ('fresh_analysis_seconds','within_one_hour','retrieval_neighborhoods','queue_candidates',
                                    'screened_inputs','qualified_agents','outcomes')},flush=True)
    except BaseException as exc:
        write(directory/'failed.json',{'exception_type':type(exc).__name__,'elapsed_seconds':time.monotonic()-started,
                                      'quality_gate_passed':False,'budget_after':budget.summary()})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--directory',type=Path,required=True)
    prep.add_argument('--snapshot',type=Path,required=True);prep.add_argument('--configuration',type=Path,required=True)
    run=sub.add_parser('run');run.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.directory,args.snapshot,args.configuration)
    else:execute(args.directory)
