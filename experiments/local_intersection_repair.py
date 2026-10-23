"""Actual bounded local proposal pass over unresolved deictic neighborhoods."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import os
import time

from commentscope.factory import local_intersection_repair as repair,named_candidate_census as census,shared_claims
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers import context_capacity
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments.completed_model_responses import CompletedResponses,NLI
from experiments.compare_backend_discovery import check_quota,quota_watch
from experiments.compare_backend_admission import lifetimes
from experiments.fresh_grounded_pipeline import Runner
from experiments.sequential_corpus_pipeline import SequentialRunner
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.scoped_discovery_probe import code_hashes
from experiments.minimal_factory_pipeline import deployment_check

VERSION='actual-local-intersection-repair-20261023-v1'
ROOT=Path('runs/compare-backend-20261023-v1')
PREVIOUS=ROOT/'M1-source-closure-v7'
CENSUS=ROOT/'M1-common-census-v2'


def inputs(plan):
    done=read_json(CENSUS/'completed.json');record=read_json(CENSUS/'artifacts/record.json')
    if done['plan_sha256']!=sha(CENSUS/'plan.json') or done['output_sha256']!=sha(CENSUS/'artifacts/record.json'):
        raise ValueError('Terminal actual census required')
    cache=CompletedResponses(CENSUS,deployment=plan['deployment']);census.validate(record)
    for request,response in record['completed_batches']:
        if cache.get(request,provider=NLI)!=response:raise ValueError('Census differs from exact completed ledger response')
    candidates=census.candidates(record)
    return repair.neighborhoods(record['sources'],candidates),cache.proof


def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):raise ValueError('New private local repair run required')
    previous=read_json(PREVIOUS/'plan.json');deployment_check(previous['deployment'])
    plan={k:deepcopy(previous[k]) for k in ['snapshot','scope_ids','deployment','classifier','model_files','documents','selections','budget','limits','resource_policy']}
    plan.update(artifact_kind=VERSION,proposal_contract=shared_claims.COMMON,at=datetime.now(timezone.utc).isoformat(),
        bottleneck='Fixed shared proposals contain unresolved deictic quantities; classifier nominations do not bind the amount and cannot yield a coherent source-reviewed second Agent.',
        hypothesis='Automatic deictic detection plus>=3 completed nominations identifies local source neighborhoods. Re-propose from every unchanged nominated original without old candidate/verdict/review input; explicit amounts and conditions can yield a self-contained common intersection.',
        structural_reassessment='Generic valence and unchanged36-proposal censuses did not yield a second credible Agent. Change neighborhood grouping and resolve common-text references locally; do not repeat the global96 proposal pass or spend deep verification on already disproven groups.',
        metrics=['complete nominee source coverage','self-contained proposed cores with explicit necessary amount/condition','subsequent direct valid support and actual Agent count'],
        decision='Review every new proposal and its nominated originals. Freeze subsequent source comparison/closure only for genuinely stated full intersections. New nominations are not approval; never manually repair a generated pack.',
        expected_calls={'new_Qwen':'One per bounded automatic deictic neighborhood (currently1 group/5originals),1024output, exact capacity measurement, existing finite600s/retries0.','new_embedding':0,'new_NLI':0},
        quality_gate_passed=False,runtime_reference_labels=False,
        inputs={str(p):sha(p) for p in [PREVIOUS/'plan.json',Path(previous['snapshot']),CENSUS/'plan.json',CENSUS/'completed.json',CENSUS/'artifacts/record.json',ROOT/'acceptance-profile.json']})
    groups,proof=inputs(plan);plan['groups']=groups;plan['reuse_proof_sha256']=digest(proof)
    plan['logical_request_sha256']=[digest(repair.request(g)) for g in groups];plan['code_sha256']=code_hashes()
    write(directory/'plan.json',plan)
    return {'prepared':True,'automatic_groups':len(groups),'source_counts':[len(g['sources']) for g in groups],'new_model_calls':0}


def run(directory):
    check_quota()
    with experiment_lock(directory),quota_watch():
        plan=read_json(directory/'plan.json')
        if plan['artifact_kind']!=VERSION:raise ValueError('Local repair contract changed')
        for field in ['inputs','code_sha256','model_files']:
            for path,expected in plan[field].items():
                if sha(path)!=expected:raise ValueError('Frozen local repair input changed: '+path)
        deployment_check(plan['deployment']);groups,proof=inputs(plan)
        if groups!=plan['groups'] or digest(proof)!=plan['reuse_proof_sha256'] or [digest(repair.request(g)) for g in groups]!=plan['logical_request_sha256']:
            raise ValueError('Frozen source neighborhood changed')
        if (directory/'started.json').exists():raise RuntimeError('Existing attempt; reconcile, no implicit retry')
        budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
        write(directory/'started.json',{'pid':os.getpid(),'plan_sha256':sha(directory/'plan.json')});started=time.monotonic()
        records=[];holds=[];errors=[]
        try:
            with lifetimes(directory,plan,1) as models:
                sequential=SequentialRunner(Runner(directory,plan,budget),models,directory/'transitions/0001')
                runner=CheckpointRunner(sequential,plan['deployment']['runtime'])
                for group in groups:
                    check_quota();request=repair.request(group);key=digest(request)
                    if (directory/'stop-after-checkpoint').exists():raise RuntimeError('Graceful checkpoint stop requested')
                    capacity=models.invoke('llm',lambda:context_capacity.measure(request))
                    if capacity['request_sha256']!=key:raise ValueError('Measured request identity changed')
                    write(directory/'artifacts/capacity'/(key+'.json'),capacity)
                    if not capacity['fits']:
                        holds.append({'source_ids':group['source_ids'],'reason':'complete_group_context_capacity'});continue
                    result=runner.call('local-intersection-'+key[:24],request);check_quota()
                    if result.get('raw') is None and result.get('errors'):raise RuntimeError('Incomplete call requires reconciliation')
                    if (result.get('usage') or {}).get('prompt_tokens',0)>capacity['input_tokens']+capacity['safety_margin']:
                        raise ValueError('Actual request exceeded measured capacity')
                    try:bound=repair.bind(group,result)
                    except (ValueError,KeyError,TypeError) as exc:
                        errors.append({'request_sha256':key,'error':str(exc)});continue
                    records.append(bound);write(directory/'artifacts/proposals'/(key+'.json'),bound)
                output={'records':records,'candidates':shared_claims.candidates(records),'errors':errors,'holds':holds,
                    'actual_agents':0,'semantic_approval':False,'quality_gate_passed':False}
                write(directory/'artifacts/output.json',output)
            report={'artifact_kind':VERSION,'plan_sha256':sha(directory/'plan.json'),'output_sha256':sha(directory/'artifacts/output.json'),
                'completed_Qwen_calls':len(records),'candidates':len(output['candidates']),'errors':errors,'capacity_holds':holds,
                'elapsed_seconds':time.monotonic()-started,'actual_agents':0,'semantic_approval':False,'goal_complete':False}
            write(directory/'completed.json',report);return report
        except BaseException as exc:
            write(directory/'failed.json',{'exception':type(exc).__name__,'message':str(exc),'elapsed_seconds':time.monotonic()-started});raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run']);parser.add_argument('directory',type=Path)
    args=parser.parse_args();print(prepare(args.directory) if args.action=='prepare' else run(args.directory),flush=True)
