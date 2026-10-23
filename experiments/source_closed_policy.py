"""Actual full-snapshot source closure using exact completed response caches."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import os
import sqlite3
from contextlib import closing
import time
from commentscope.factory import source_closed_policy as closed,shared_claims,candidate_consolidation as cc
from commentscope.factory import fact_checks,explicit_discourse as ed,reviewed_source_admission as source_review
from experiments.source_review_queue import SourceReviewQueue,VERSION as REVIEW_QUEUE_VERSION
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources as registry
from commentscope.ingestion import load_snapshot
from commentscope.providers import context_capacity,evidence_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments.compare_backend_discovery import check_quota,quota_watch,SCOPE
from experiments.compare_backend_admission import lifetimes
from experiments.completed_policy_union import load as completed_union
from experiments.completed_model_responses import CompletedResponses,NLI
from experiments.fresh_grounded_pipeline import Runner
from experiments.sequential_corpus_pipeline import SequentialRunner,runtime_check
from experiments.framed_agent_probe import runtime_probe
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.scoped_discovery_probe import code_hashes
from experiments.minimal_factory_pipeline import deployment_check

VERSION='actual-source-closed-policy-factory-20261023-v13'
ROOT=Path('runs/compare-backend-20261023-v1')
CENSUS=ROOT/'M1-policy-census-full-v1'
PRIORS=[ROOT/'M1-source-closure-v12',ROOT/'M1-source-closure-v11',ROOT/'M1-source-closure-v10',ROOT/'M1-source-closure-v9',ROOT/'M1-source-closure-v8',ROOT/'M1-source-closure-v7',ROOT/'M1-source-closure-v6',ROOT/'M1-source-closure-v5',ROOT/'M1-source-closure-v4',ROOT/'M1-source-closure-v3',ROOT/'M1-source-closure-v2',ROOT/'M1-source-closure-v1',ROOT/'M1-policy-factory-v1',ROOT/'M1-admission-breadth-v3',ROOT/'M1-admission-v1']


def inputs(plan):
    snapshot=load_snapshot(Path(plan['snapshot'])).snapshot;fact_checks.live(snapshot.usage.expires_at)
    lookup=registry(snapshot,include_video_context=True);originals=[lookup[sid] for sid in plan['scope_ids']]
    record,batches,proof=completed_union(CENSUS,deployment=plan['deployment'],sources=originals)
    return snapshot,record,batches,proof


def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):raise ValueError('New private source-closure run required')
    previous=read_json(SCOPE);census=read_json(CENSUS/'plan.json');deployment_check(previous['deployment'])
    plan={'artifact_kind':VERSION,'at':datetime.now(timezone.utc).isoformat(),
        'bottleneck':'Controller stopped after3model-closed unreviewed sources. A later direct rejection invalidated the pack without allowing ordered admission to continue to a third actually valid source. New sentence interpretation also yielded no new valid support. Product remains1Agent/3valid supports.',
        'hypothesis':'Move existing exact complete-source direct review before counted admission. Generation remains untrusted: reuse original whole-source argument extraction and exact completed responses, do not rewrite/repair content or tune another typing prompt. Only pass reviews fill3slots, failures/uncertainty remain explicit and processing continues in frozen order. Review labels never enter model inputs.',
        'snapshot':previous['snapshot'],'scope_ids':census['full_scope_ids'],'deployment':previous['deployment'],
        'classifier':previous['classifier'],'model_files':previous['model_files'],'documents':previous['documents'],
        'selections':previous['selections'],'budget':previous['budget'],'limits':previous['limits'],
        'resource_policy':previous['resource_policy'],
        'selection':'All999 originals/all224 nominations retained. Candidates by ID; fixed-syntax path first, then unsupported sources, each ordered by literal node count/original length/ID. Stop each at3 model-closed sources; rest explicitly unprocessed. No successful-source/review-label selection.',
        'ownership':'Fixed syntax keeps unchanged literal node/parent proofs. Unsupported syntax requires independently approved complete original membership and literal evidence for every semantic unit, plus full original coverage/role/condition audit. Parent/video never enter argument comparator premises. Uncertain/partial declarations, failed entailment/audit/facts never count.',
        'interpret_unparsed':True,'atomic_arguments':False,'literal_arguments':False,'sentence_arguments':False,'require_direct_review':True,'runtime_after_direct_review':True,
        'source_review_contract':source_review.VERSION,'review_queue_contract':REVIEW_QUEUE_VERSION,'source_review_wait_seconds':600,
        'strategy_checkpoint':'This tests admission validation, not another extraction prompt. Every model-closed source waits for exact full-original/core/draft/artifact review before counting. No hand-edited successful pack or predefined winning IDs; failed whole sources remain explicit, no dropped major argument within a counted author. Only2reviewed Agents/6answers/HTTP complete the Goal.',
        'facts':'Private one-source draft exposes every selected factual claim for exact supplied-document NLI. All draft claims must be eligible; failed facts cannot be silently omitted for a vote. Public compile still>=3.',
        'audits':'One actual complete own-source audit with all source tasks; independent scoped receipts compose unchanged. Final semantic review remains mandatory.',
        'embeddings':'None: full fixed NLI census provides nominations. No fake vectors or new embedding generation.',
        'expected_calls':{'new_proposal':0,'new_embedding':0,'new_whole_original_comparisons':0,
            'new_source_Qwen':'Only genuinely unassessed original extraction/audit/dependency/raw support calls; unchanged original requests reused. Exact source review itself calls no extra model API. Until3 closed per core; all unchanged actual completed responses, including v8, reused.',
            'new_NLI':'Only semantic argument fidelity, unchanged own-node cache misses and every actual selected fact.',
            'runtime':'No runtime in this cycle. Directly review actual complete Agent contents/all counted sources before freezing6actual responses andHTTP.'},
        'decision':'If fewer than2 compile, inspect exact per-source first failing gate; do not relabel facts, weaken conditions or retry unavailable calls.',
        'prior_caches':[str(p) for p in PRIORS],'quality_gate_passed':False,'runtime_reference_labels':False,
        'independent_G3':False,
        'inputs':{str(p):sha(p) for p in [SCOPE,Path(previous['snapshot']),CENSUS/'plan.json',CENSUS/'completed.json',
            CENSUS/'artifacts/combined-record.json',ROOT/'acceptance-profile.json',ROOT/'M1-end-to-end-direction-20261023.json',ROOT/'M1-source-closure-v12-result.json',ROOT/'M1-review-before-count-real-replay.json',ROOT/'M1-full-common-v2-direct-review.json']}}
    _,record,batches,proof=inputs(plan)
    caches=[CompletedResponses(p,deployment=plan['deployment']) for p in PRIORS]
    plan['nomination_proof_sha256']=digest(proof);plan['prior_cache_proof_sha256']=[digest(c.proof) for c in caches]
    plan['candidate_sha256']=digest(shared_claims.candidates([record]))
    with closing(sqlite3.connect(Path(plan['budget']['ledger']).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        blocked=db.execute('SELECT id,request_sha,state FROM calls WHERE id IN (6974,7119)').fetchall()
    if len(blocked)!=2 or any(r[2]!='interrupted' for r in blocked):raise ValueError('Prior interrupted requests must stay explicit')
    plan['unavailable_requests']={r[1]:r[0] for r in blocked}
    # Freeze pre-existing source reviews as validation evidence only. Newly
    # produced judgments are append-only outputs bound to each queued packet.
    for prior in PRIORS:
        for path in sorted((prior/'semantic-review').glob('*/*.json')):
            review=read_json(path);plan['inputs'][str(path)]=sha(path)
            if not source_review.complete_review(review):
                plan.setdefault('incomplete_prior_review_files_not_reusable',[]).append(str(path))
                continue
            for evidence,expected in review['files_sha256'].items():
                if sha(evidence)!=expected:raise ValueError('Prior direct review evidence changed')
                plan['inputs'][evidence]=expected
    plan['code_sha256']=code_hashes()
    write(directory/'plan.json',plan)
    return {'prepared':True,'all_sources':len(record['sources']),'actual_census_batches_reused':len(batches),
        'prior_completed_responses':[len(c.results) for c in caches],'new_model_calls':0}


def run(directory):
    check_quota()
    with experiment_lock(directory),quota_watch():
        plan=read_json(directory/'plan.json')
        if plan['artifact_kind']!=VERSION:raise ValueError('Source-closure contract changed')
        if plan['source_review_contract']!=source_review.VERSION or plan['review_queue_contract']!=REVIEW_QUEUE_VERSION:raise ValueError('Source admission review contract changed')
        for field in ['inputs','code_sha256','model_files']:
            for path,expected in plan[field].items():
                if sha(path)!=expected:raise ValueError('Frozen source-closure input changed: '+path)
        deployment_check(plan['deployment']);snapshot,record,batches,proof=inputs(plan)
        caches=[CompletedResponses(Path(p),deployment=plan['deployment']) for p in plan['prior_caches']]
        if digest(proof)!=plan['nomination_proof_sha256'] or [digest(c.proof) for c in caches]!=plan['prior_cache_proof_sha256']:
            raise ValueError('Actual completed reuse changed')
        if (directory/'started.json').exists():raise RuntimeError('Attempt already exists; reconcile, no implicit retry')
        budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
        write(directory/'started.json',{'pid':os.getpid(),'plan_sha256':sha(directory/'plan.json')});started=time.monotonic()
        def boundary():
            check_quota()
            if (directory/'stop-after-checkpoint').exists():raise RuntimeError('Graceful checkpoint stop requested; no new call')
        def save(name,value):
            path=directory/'artifacts'/(name+'.json')
            if path.exists():
                if read_json(path)!=value:raise ValueError('Same-plan artifact changed: '+name)
            else:write(path,value)
        save('nomination-reuse-proof',proof)
        for i,cache in enumerate(caches):save('prior-response-cache/'+str(i),cache.proof)
        try:
            with lifetimes(directory,plan,1) as models:
                sequential=SequentialRunner(Runner(directory,plan,budget),models,directory/'transitions/0001')
                checkpoint=CheckpointRunner(sequential,plan['deployment']['runtime']);capacities={}
                def inspect(req):
                    boundary();key=digest(req)
                    if key not in capacities:
                        value=next((value for c in caches if (value:=c.capacity(req)) is not None),None)
                        capacities[key]=value if value is not None else models.invoke('llm',lambda:context_capacity.measure(req))
                    return deepcopy(capacities[key])
                class Logical:
                    def call(self,stage,req):
                        from commentscope.factory.shared_admission import PriorRequestUnavailable
                        boundary();key=digest(req)
                        if key in plan['unavailable_requests']:raise PriorRequestUnavailable('Prior interrupted request: '+str(plan['unavailable_requests'][key]))
                        for cache in caches:
                            cached=cache.get(req)
                            if cached is not None:
                                save('prior-response-roles/'+digest([stage,req]),{'role':stage,'request_sha256':key});return cached
                        measured=inspect(req)
                        if not measured['fits']:raise ValueError('Complete request exceeds capacity')
                        save('logical-roles/'+digest([stage,req]),{'role':stage,'request_sha256':key})
                        result=checkpoint.call('logical-'+key[:32],req);boundary()
                        if (result.get('usage') or {}).get('prompt_tokens',0)>measured['input_tokens']+measured['safety_margin']:
                            raise ValueError('Actual request exceeded capacity allocation')
                        return result
                def classify(req):
                    boundary()
                    for cache in caches:
                        cached=cache.get(req,provider=NLI)
                        if cached is not None:return cached
                    result=checkpoint.call('classifier-'+digest(req)[:24],req,provider=evidence_nli.generate,
                        maximum=plan['limits']['fact_batch_seconds']);boundary();return result
                runner=Logical()
                factory=closed.process(snapshot,record,batches,runner,inspect,classify,model=plan['classifier'],
                    documents=plan['documents'],selections=plan['selections'],save=save,
                    interpret_unparsed=plan['interpret_unparsed'],atomic_arguments=plan['atomic_arguments'],literal_arguments=plan['literal_arguments'],sentence_arguments=plan['sentence_arguments'],require_direct_review=plan['require_direct_review'],
                    review_source=SourceReviewQueue(directory,[Path(p) for p in plan['prior_caches']],boundary,wait_seconds=plan['source_review_wait_seconds']))
                profiles=factory['agent_inputs']['compiled']['profiles'];distinct=[];runtime=None
                if len(profiles)>=2 and not plan['runtime_after_direct_review']:
                    pairs=[{'a':profiles[0]['candidate_id'],'b':profiles[1]['candidate_id']}]
                    memberships=[a['membership'] for a in factory['accepted']]
                    req=cc.equivalence_request(record['sources'],factory['candidates'],memberships,pairs)
                    bound=cc.bind(record['sources'],factory['candidates'],memberships,pairs,runner.call('distinct-compiled-policies',req))
                    distinct.append(bound);save('distinct',bound)
                    runtime=runtime_probe(factory['agent_inputs']['bundle'],runner)
                    runtime_check(runtime,factory['agent_inputs']['compiled']);save('runtime',runtime)
                save('output',{'admission':factory,'last_factory':factory,'distinct_checks':distinct,
                    'runtime':runtime,'quality_gate_passed':False})
            report={'artifact_kind':VERSION,'plan_sha256':sha(directory/'plan.json'),'output_sha256':sha(directory/'artifacts/output.json'),
                'all_sources':len(record['sources']),'closed_source_counts':{o['candidate_id']:len(o['closed_source_ids']) for o in factory['outcomes']},
                'compiled_agents':len(profiles),'runtime_turns':len(runtime['turns']) if runtime else 0,
                'errors':len(factory['errors']),'prior_responses_reused':sum(len(c.used) for c in caches),
                'elapsed_seconds':time.monotonic()-started,'semantic_review_required':True,'quality_gate_passed':False}
            write(directory/'completed.json',report);return report
        except BaseException as exc:
            write(directory/'failed.json',{'exception':type(exc).__name__,'message':str(exc),'elapsed_seconds':time.monotonic()-started})
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run']);parser.add_argument('directory',type=Path)
    args=parser.parse_args();print(prepare(args.directory) if args.action=='prepare' else run(args.directory),flush=True)
