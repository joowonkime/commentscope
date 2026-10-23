"""Qualified conditional policy-value admission through the actual Factory."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import os
import time
import sqlite3
from contextlib import closing

from commentscope.factory import policy_admission,shared_claims,minimal_pipeline,candidate_consolidation as cc
from commentscope.factory import fact_checks,raw_membership_verification as verification
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources as registry
from commentscope.ingestion import load_snapshot
from commentscope.providers import context_capacity,evidence_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments.compare_backend_discovery import check_quota,quota_watch,SCOPE,EMBEDDINGS
from experiments.compare_backend_admission import lifetimes
from experiments.completed_policy_stance import load as completed_stance
from experiments.completed_model_responses import CompletedResponses,NLI
from experiments.fresh_grounded_pipeline import Runner
from experiments.sequential_corpus_pipeline import SequentialRunner,runtime_check
from experiments.framed_agent_probe import runtime_probe
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.scoped_discovery_probe import code_hashes
from experiments.minimal_factory_pipeline import deployment_check

VERSION='qualified-policy-factory-20261023-v1'
ROOT=Path('runs/compare-backend-20261023-v1')
CENSUS=ROOT/'M1-policy-stance-discovery-v1'
PRIOR=ROOT/'M1-admission-breadth-v3'


def inputs(plan):
    snapshot=load_snapshot(Path(plan['snapshot'])).snapshot;fact_checks.live(snapshot.usage.expires_at)
    sources=registry(snapshot,include_video_context=True);originals=[sources[sid] for sid in plan['scope_ids']]
    record,request,response,proof=completed_stance(CENSUS,deployment=plan['deployment'],sources=originals)
    vectors=read_json(EMBEDDINGS)
    if vectors['texts_sha256']!=digest({s['id']:s['text'] for s in originals}):raise ValueError('Exact cached source vectors required')
    return snapshot,originals,record,request,response,proof,vectors['vectors']


def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):raise ValueError('New private Factory run required')
    previous=read_json(SCOPE);deployment_check(previous['deployment'])
    plan={'artifact_kind':VERSION,'at':datetime.now(timezone.utc).isoformat(),
        'bottleneck':'Need source-derived conditional evaluative common cores and qualified source counts, without borrowing another voice or invented shared rationale.',
        'hypothesis':'A source-only own-policy evaluation, before a requested polarity is shown, filters classifier nomination errors. Raw/own-evidence plus exact completed whole-source NLI then yield actual shared value cores.',
        'snapshot':previous['snapshot'],'scope_ids':previous['scope_ids'],'deployment':previous['deployment'],
        'classifier':previous['classifier'],'model_files':previous['model_files'],
        'documents':previous['documents'],'selections':previous['selections'],'budget':previous['budget'],
        'limits':previous['limits'],'resource_policy':previous['resource_policy'],
        'admission_policy':'Every nominated author gets one source-only evaluation; then all matching source/polarity pairs get raw and positive-only own-evidence checks. NLI case reused with full original batch hash. Only qualified>=3 triggers existing argument/fact/Agent compilation.',
        'source_order':'Source-only evaluation and membership by shortest exact original then source ID; all nominated pairs included, no successful-source selection.',
        'condition_policy':'Existing ownership/essential-condition/fact rules unchanged. Conditional template never itself authorizes deleting any condition or publishing a universal stance.',
        'expected_calls':{'new_global_proposal_calls':0,'new_embedding_calls':0,'new_nomination_NLI_calls':0,
            'source_only_evaluations_max':9,'candidate_route_and_core_max':4,'raw_pairs_max':13,
            'own_evidence_max':13,'argument_fact_calls':'only qualified>=3; actual immutable source nodes',
            'runtime':'three actual questions per compiled profile; no all-abstain acceptance'},
        'prior_cache':str(PRIOR),'quality_gate_passed':False,'runtime_reference_labels':False,
        'inputs':{str(p):sha(p) for p in [SCOPE,EMBEDDINGS,Path(previous['snapshot']),CENSUS/'plan.json',
            CENSUS/'completed.json',CENSUS/'artifacts/record.json',ROOT/'acceptance-profile.json']},
        'code_sha256':code_hashes()}
    _,originals,record,request,response,proof,_=inputs(plan)
    prior=CompletedResponses(PRIOR,deployment=plan['deployment'])
    plan['nomination_proof_sha256']=digest(proof);plan['prior_cache_proof_sha256']=digest(prior.proof)
    plan['candidate_sha256']=digest(shared_claims.candidates([record]))
    ledger=Path(plan['budget']['ledger']).resolve()
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True)) as db:
        blocked=db.execute('SELECT id,request_sha,state FROM calls WHERE id IN (6974,7119)').fetchall()
    if len(blocked)!=2 or any(r[2]!='interrupted' for r in blocked):raise ValueError('Prior interrupted requests must stay explicit')
    plan['unavailable_requests']={r[1]:r[0] for r in blocked}
    write(directory/'plan.json',plan)
    return {'prepared':True,'sources':len(originals),'hypotheses':len(shared_claims.candidates([record])),
        'prior_completed_responses':len(prior.results),'new_model_calls':0}


def run(directory):
    check_quota()
    with experiment_lock(directory),quota_watch():
        plan=read_json(directory/'plan.json')
        if plan['artifact_kind']!=VERSION:raise ValueError('Factory contract changed')
        for field in ['inputs','code_sha256','model_files']:
            for path,expected in plan[field].items():
                if sha(path)!=expected:raise ValueError('Frozen Factory input changed: '+path)
        deployment_check(plan['deployment'])
        snapshot,originals,record,completed_request,response,proof,vectors=inputs(plan)
        prior=CompletedResponses(Path(plan['prior_cache']),deployment=plan['deployment'])
        if digest(proof)!=plan['nomination_proof_sha256'] or digest(prior.proof)!=plan['prior_cache_proof_sha256']:
            raise ValueError('Completed response reuse changed')
        if (directory/'started.json').exists():raise RuntimeError('Attempt already exists; reconcile, no implicit retry')
        budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
        write(directory/'started.json',{'pid':os.getpid(),'plan_sha256':sha(directory/'plan.json')})
        started=time.monotonic()
        def save(name,value):
            path=directory/'artifacts'/(name+'.json')
            if path.exists():
                if read_json(path)!=value:raise ValueError('Same-plan artifact changed: '+name)
            else:write(path,value)
        save('nomination-reuse-proof',proof);save('prior-response-cache',prior.proof)
        try:
            with lifetimes(directory,plan,1) as models:
                sequential=SequentialRunner(Runner(directory,plan,budget),models,directory/'transitions/0001')
                checkpoint=CheckpointRunner(sequential,plan['deployment']['runtime']);capacities={}
                def inspect(req):
                    key=digest(req)
                    if key not in capacities:
                        value=prior.capacity(req)
                        capacities[key]=value if value is not None else models.invoke('llm',lambda:context_capacity.measure(req))
                    return deepcopy(capacities[key])
                class Logical:
                    def call(self,stage,req):
                        from commentscope.factory.shared_admission import PriorRequestUnavailable
                        check_quota();key=digest(req)
                        if key in plan['unavailable_requests']:raise PriorRequestUnavailable('Prior interrupted request: '+str(plan['unavailable_requests'][key]))
                        cached=prior.get(req)
                        if cached is not None:
                            save('prior-response-roles/'+digest([stage,req]),{'role':stage,'request_sha256':key});return cached
                        measured=inspect(req)
                        if not measured['fits']:raise ValueError('Unsplit complete request exceeds capacity')
                        save('logical-roles/'+digest([stage,req]),{'role':stage,'request_sha256':key})
                        result=checkpoint.call('logical-'+key[:32],req);check_quota()
                        usage=result.get('usage') or {}
                        if usage.get('prompt_tokens',0)>measured['input_tokens']+measured['safety_margin']:
                            raise ValueError('Actual request exceeded frozen capacity allocation')
                        return result
                runner=Logical()
                admission=policy_admission.process(originals,record,completed_request,response,runner,inspect,save=save)
                save('admission',admission);factory=None;runtime=None;distinct=[]
                if admission['ready_candidate_ids']:
                    def embed(stage,texts):
                        if stage!='sources' or digest(texts)!=digest({s['id']:s['text'] for s in originals}):raise ValueError('No new embedding generation allowed')
                        return deepcopy(vectors)
                    def facts(req):
                        check_quota();cached=prior.get(req,provider=NLI)
                        if cached is not None:return cached
                        result=checkpoint.call('facts-'+digest(req)[:24],req,provider=evidence_nli.generate,maximum=plan['limits']['fact_batch_seconds'])
                        check_quota();return result
                    factory=minimal_pipeline.process(snapshot,runner,embed,inspect,facts,model=plan['classifier'],
                        documents=plan['documents'],selections=plan['selections'],scope_ids=plan['scope_ids'],
                        discovery_mode='shared',membership_mode='raw',verification_contract=verification.ALIGNED,
                        shared_records=[record],shared_memberships=admission['qualified_memberships'],source_entailment_required=True,
                        save=lambda name,value:save('factory/'+name,value))
                    save('factory/output',factory)
                    profiles=factory['agent_inputs']['compiled']['profiles'];candidates=admission['candidates']
                    for i,left in enumerate(profiles):
                        for right in profiles[i+1:]:
                            pairs=[{'a':left['candidate_id'],'b':right['candidate_id']}]
                            req=cc.equivalence_request(originals,candidates,admission['qualified_memberships'],pairs)
                            if inspect(req)['fits']:
                                bound=cc.bind(originals,candidates,admission['qualified_memberships'],pairs,runner.call('distinct-compiled-policies',req))
                                distinct.append(bound);save('distinct/'+digest(pairs),bound)
                    if profiles:
                        runtime=runtime_probe(factory['agent_inputs']['bundle'],runner)
                        runtime_check(runtime,factory['agent_inputs']['compiled']);save('runtime',runtime)
                output={'admission':admission,'last_factory':factory,'distinct_checks':distinct,'runtime':runtime,'quality_gate_passed':False}
                save('output',output)
            report={'artifact_kind':VERSION,'plan_sha256':sha(directory/'plan.json'),
                'output_sha256':sha(directory/'artifacts/output.json'),
                'qualified_source_counts':{o['candidate_id']:len(o['qualified_sources']) for o in admission['outcomes']},
                'compiled_agents':len(factory['agent_inputs']['compiled']['profiles']) if factory else 0,
                'runtime_turns':len(runtime['turns']) if runtime else 0,'elapsed_seconds':time.monotonic()-started,
                'prior_response_hits':prior.hits,'prior_responses_reused':len(prior.used),
                'semantic_review_required':True,'quality_gate_passed':False}
            write(directory/'completed.json',report);return report
        except BaseException as exc:
            write(directory/'failed.json',{'exception':type(exc).__name__,'message':str(exc),'elapsed_seconds':time.monotonic()-started})
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run']);parser.add_argument('directory',type=Path)
    args=parser.parse_args();result=prepare(args.directory) if args.action=='prepare' else run(args.directory)
    print({k:v for k,v in result.items() if k not in ['qualified_source_counts']},flush=True)
