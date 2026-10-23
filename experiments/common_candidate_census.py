"""Freeze completed common hypotheses, then compare automatic lexical nominees.

No new proposals/embeddings, no selected successful originals, no manual labels.
This phase measures candidate availability before costly source closure.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import os
import time

from commentscope.factory import named_candidate_census as census,shared_claims,fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources as registry
from commentscope.ingestion import load_snapshot
from commentscope.providers import evidence_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments.compare_backend_discovery import check_quota,quota_watch,SCOPE
from experiments.compare_backend_admission import lifetimes
from experiments.completed_shared_proposals import load as completed_proposals
from experiments.fresh_grounded_pipeline import Runner
from experiments.sequential_corpus_pipeline import SequentialRunner
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.scoped_discovery_probe import code_hashes
from experiments.minimal_factory_pipeline import deployment_check

VERSION='actual-common-candidate-census-20261023-v2'
ROOT=Path('runs/compare-backend-20261023-v1')
DISCOVERY=ROOT/'M1-discovery-v2'
PREVIOUS=ROOT/'M1-source-closure-v7'


def inputs(plan):
    snapshot=load_snapshot(Path(plan['snapshot'])).snapshot;fact_checks.live(snapshot.usage.expires_at)
    lookup=registry(snapshot,include_video_context=True)
    original96=[lookup[sid] for sid in read_json(SCOPE)['scope_ids']]
    records,proof=completed_proposals(DISCOVERY,deployment=plan['deployment'],originals=original96)
    sources=[lookup[sid] for sid in plan['scope_ids']]
    ranked=census.ranking(sources,shared_claims.candidates(records),plan['topic'],plan['alias'],limit=plan['retrieval_limit'],remaining_unnamed=True)
    return ranked,proof


def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):raise ValueError('New private census required')
    prior=read_json(PREVIOUS/'plan.json');deployment_check(prior['deployment'])
    plan={k:deepcopy(prior[k]) for k in ['snapshot','scope_ids','deployment','classifier','model_files','documents','selections','budget','limits','resource_policy']}
    plan.update(artifact_kind=VERSION,at=datetime.now(timezone.utc).isoformat(),topic='Universal Basic Income',alias='UBI',retrieval_limit=32,
        bottleneck='Named-policy census completed768pairs but no directly credible three-source alternative. It excluded12 substantive self-contained non-policy-name hypotheses such as personal work intentions solely for absent policy names.',
        hypothesis='Test all12 previously unassessed non-named hypotheses, unchanged. Own-original BM25 retrieval over all999, no new global generation or hand-selected source. Independent raw/evidence/reference/own-node gates must establish their exact self-contained scope; no missing policy referent is filled in.',
        eligibility='Only the12 hypotheses with no policy name enter this remaining path. Exact full originals, fixed source syntax and literal nodes<=600 remain necessary. Named-policy hypotheses are not re-compared; prior768 actual comparisons remain preserved.',
        metrics=['nominated original counts per common hypothesis','candidate count with>=3 actual full-original comparisons supported','unassessed pairs retained','no semantic/Agent approval from nominations'],
        decision='If a substantive alternative has>=3 nominations, freeze source closure over all such candidates. Otherwise change representation/retrieval before further Qwen calls; do not rewrite candidates or manufacture votes.',
        expected_calls={'Qwen':0,'embedding':0,'NLI':'One call for12x32=384 previously unassessed pairs, each original<=512 classifier tokens or held; finite existing timeout/retries0.'},
        quality_gate_passed=False,independent_G3=False,
        inputs={str(p):sha(p) for p in [SCOPE,Path(prior['snapshot']),PREVIOUS/'plan.json',PREVIOUS/'completed.json',DISCOVERY/'plan.json',DISCOVERY/'completed.json',DISCOVERY/'artifacts/output.json',ROOT/'M1-common-census-v1/completed.json',ROOT/'acceptance-profile.json']})
    ranked,proof=inputs(plan);request=census.invocation(ranked)
    plan['ranking_sha256']=digest(ranked);plan['proposal_reuse_proof_sha256']=digest(proof)
    plan['batches']=[{'system':request['system'],'schema':{},'max_tokens':1,'data':{'cases':request['data']['cases'][i:i+600]}}
        for i in range(0,len(request['data']['cases']),600)]
    plan['code_sha256']=code_hashes()
    write(directory/'plan.json',plan);write(directory/'ranking.json',ranked);write(directory/'proposal-reuse-proof.json',proof)
    return {'prepared':True,'all_sources':len(ranked['sources']),'completed_hypotheses':len(ranked['proposals']),
        'named_hypotheses':sum(r['named_policy'] for r in ranked['rows']),
        'retrieved_pairs':len(request['data']['cases']),'actual_NLI_batches':len(plan['batches']),'new_model_calls':0}


def run(directory):
    check_quota()
    with experiment_lock(directory),quota_watch():
        plan=read_json(directory/'plan.json')
        if plan['artifact_kind']!=VERSION:raise ValueError('Census contract changed')
        for field in ['inputs','code_sha256','model_files']:
            for path,expected in plan[field].items():
                if sha(path)!=expected:raise ValueError('Frozen census input changed: '+path)
        deployment_check(plan['deployment']);ranked,proof=inputs(plan)
        if digest(ranked)!=plan['ranking_sha256'] or digest(proof)!=plan['proposal_reuse_proof_sha256']:raise ValueError('Exact completed hypotheses changed')
        if (directory/'started.json').exists():raise RuntimeError('Existing attempt; reconcile, no implicit retry')
        budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
        write(directory/'started.json',{'pid':os.getpid(),'plan_sha256':sha(directory/'plan.json')});started=time.monotonic()
        completed=[]
        try:
            with lifetimes(directory,plan,1) as models:
                sequential=SequentialRunner(Runner(directory,plan,budget),models,directory/'transitions/0001')
                runner=CheckpointRunner(sequential,plan['deployment']['runtime'])
                for i,request in enumerate(plan['batches'],1):
                    check_quota()
                    if (directory/'stop-after-checkpoint').exists():raise RuntimeError('Graceful checkpoint stop requested')
                    response=runner.call('common-original-census-'+str(i),request,provider=evidence_nli.generate,maximum=plan['limits']['fact_batch_seconds'])
                    write(directory/'batch-completions'/f'{i:04}.json',{'request':request,'response':response})
                    check_quota();completed.append((request,response))
                record=census.bind(ranked,completed);candidates=census.candidates(record)
                write(directory/'artifacts/record.json',record)
                write(directory/'artifacts/candidates.json',candidates)
            report={'artifact_kind':VERSION,'plan_sha256':sha(directory/'plan.json'),
                'output_sha256':sha(directory/'artifacts/record.json'),'all_sources':len(ranked['sources']),
                'hypotheses':len(ranked['proposals']),'new_NLI_calls':len(completed),'new_Qwen_calls':0,'new_embedding_calls':0,
                'nominees':[{'candidate_id':c['id'],'text':c['text'],'count':len(c['nominees'])} for c in candidates],
                'at_least_three_nominees':sum(len(c['nominees'])>=3 for c in candidates),
                'elapsed_seconds':time.monotonic()-started,'semantic_approval':False,'goal_complete':False}
            write(directory/'completed.json',report);return report
        except BaseException as exc:
            write(directory/'failed.json',{'exception':type(exc).__name__,'message':str(exc),'elapsed_seconds':time.monotonic()-started});raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run']);parser.add_argument('directory',type=Path)
    args=parser.parse_args();print(prepare(args.directory) if args.action=='prepare' else run(args.directory),flush=True)
