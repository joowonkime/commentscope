"""A frozen first tranche of common discovery across the existing full snapshot.

All source groups are frozen before inference. A tranche is feasibility evidence,
not whole-snapshot completion. No group is selected by reviews or successful IDs.
"""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import os,time
from commentscope.factory import lexical_source_groups as lexical,shared_claims
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources as registry
from commentscope.ingestion import load_snapshot
from commentscope.providers import context_capacity
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.checkpoint_calls import CheckpointRunner
from commentscope.storage import write_json_exclusive as write
from experiments.compare_backend_discovery import check_quota,quota_watch,SCOPE
from experiments.compare_backend_admission import lifetimes
from experiments.framed_corpus_pipeline import experiment_lock
from experiments.fresh_grounded_pipeline import Runner
from experiments.sequential_corpus_pipeline import SequentialRunner
from experiments.scoped_discovery_probe import code_hashes
from experiments.minimal_factory_pipeline import deployment_check
from experiments.completed_model_responses import CompletedResponses

VERSION='full-snapshot-common-discovery-20261023-v1'
ROOT=Path('runs/compare-backend-20261023-v1')
CENSUS=ROOT/'M1-policy-census-full-v1/plan.json'
PRIORS=[ROOT/'M1-discovery-v2',ROOT/'M1-local-intersection-repair-v1']

def originals(plan):
    snapshot=load_snapshot(Path(plan['snapshot'])).snapshot
    sources=registry(snapshot,include_video_context=True)
    return [sources[sid] for sid in plan['scope_ids']]

def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):
        raise ValueError('A new private discovery run is required')
    prior=read_json(SCOPE);deployment_check(prior['deployment'])
    plan={k:prior[k] for k in ('snapshot','deployment','budget','limits','resource_policy','model_files')}
    plan.update(artifact_kind=VERSION,at=datetime.now(timezone.utc).isoformat(),
        scope_ids=read_json(CENSUS)['full_scope_ids'],grouping_contract=lexical.VERSION,
        proposal_contract=shared_claims.COMMON,
        bottleneck='Free common discovery covered96 originals; only two valence hypotheses were compared across999. Local source interpretation changes yielded no second valid Agent.',
        hypothesis='Automatically ranked own-original lexical neighborhoods across999 expose shared self-contained positions outside the old96/two valence candidates. Existing COMMON prompt and downstream gates unchanged.',
        selection='All sources retained once in deterministic TF-IDF groups; seed rank is mean top2 cosine times min(1,distinct unigram/bigram features/24), using own text only and preserving quantities. First4 groups are a feasibility tranche; all remaining groups explicitly unassessed.',
        decision='Inspect all actual proposals and nominee originals. Only hypotheses with plausible >=3 fully valid own-source supports proceed to actual membership/arguments/facts/Agent compilation. No blind sweep of remaining groups, manual source repair or successful pack.',
        independent_G3=False,quality_gate_passed=False,new_embedding_calls=0,
        expected_calls={'proposal_before_capacity_split':4,'maximum_after_split':48,'max_output_tokens_each':1024},
        product_metric='Second genuinely different actual Agent/3 valid sources, then6actual answers andHTTP; proposal count alone is product improvement0.')
    groups=lexical.groups(originals(plan));plan['groups']=[[s['id'] for s in g] for g in groups]
    plan['selected_group_indices']=list(range(min(4,len(groups))))
    plan['unassessed_group_indices']=list(range(len(plan['selected_group_indices']),len(groups)))
    paths=[SCOPE,CENSUS,Path(prior['snapshot']),ROOT/'acceptance-profile.json',ROOT/'M1-source-closure-v11-result.json',ROOT/'M1-literal-source-structural-result.json']
    plan['inputs']={str(p):sha(p) for p in paths};plan['code_sha256']=code_hashes()
    caches=[CompletedResponses(p,deployment=plan['deployment']) for p in PRIORS]
    plan['prior_cache_proof_sha256']=[digest(c.proof) for c in caches]
    plan['logical_request_sha256']=[digest(shared_claims.request(groups[i],version=shared_claims.COMMON)) for i in plan['selected_group_indices']]
    write(directory/'plan.json',plan)
    return {'scope':len(plan['scope_ids']),'all_groups':len(groups),'selected_groups':plan['selected_group_indices'],'new_model_calls':0}

def run(directory):
    check_quota()
    with experiment_lock(directory),quota_watch():
        plan=read_json(directory/'plan.json')
        if plan['artifact_kind']!=VERSION or plan['grouping_contract']!=lexical.VERSION:
            raise ValueError('Discovery contracts changed')
        for path,expected in {**plan['inputs'],**plan['code_sha256'],**plan['model_files']}.items():
            if sha(path)!=expected:raise ValueError('Frozen discovery input changed: '+path)
        deployment_check(plan['deployment']);groups=lexical.groups(originals(plan))
        if [[s['id'] for s in g] for g in groups]!=plan['groups']:raise ValueError('Frozen groups changed')
        if [digest(shared_claims.request(groups[i],version=shared_claims.COMMON)) for i in plan['selected_group_indices']]!=plan['logical_request_sha256']:
            raise ValueError('Frozen requests changed')
        caches=[CompletedResponses(p,deployment=plan['deployment']) for p in PRIORS]
        if [digest(c.proof) for c in caches]!=plan['prior_cache_proof_sha256']:raise ValueError('Completed response cache changed')
        if (directory/'started.json').exists():raise RuntimeError('Attempt exists; reconcile, no implicit retry')
        budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
        write(directory/'started.json',{'pid':os.getpid(),'plan_sha256':sha(directory/'plan.json')});started=time.monotonic()
        def boundary():
            check_quota()
            if (directory/'stop-after-checkpoint').exists():raise RuntimeError('Graceful checkpoint stop requested; no new call')
        def save(name,value):write(directory/'artifacts'/(name+'.json'),value)
        records=[];holds=[];errors=[];reused=0
        try:
            with lifetimes(directory,plan,1) as models:
                sequential=SequentialRunner(Runner(directory,plan,budget),models,directory/'transitions/0001')
                checkpoint=CheckpointRunner(sequential,plan['deployment']['runtime'])
                for i in plan['selected_group_indices']:
                    boundary();group=groups[i]
                    fitted,deferred=context_capacity.partition(group,
                        lambda rows:shared_claims.request(rows,version=shared_claims.COMMON),
                        lambda req:models.invoke('llm',lambda:context_capacity.measure(req)),minimum=2)
                    holds.extend(deferred)
                    for task in fitted:
                        boundary();req=task['request'];key=digest(req)
                        save('capacity/'+key,task['capacity'])
                        result=next((r for c in caches if (r:=c.get(req)) is not None),None)
                        if result is None:result=checkpoint.call('common-'+key[:24],req)
                        else:reused+=1
                        boundary()
                        try:record=shared_claims.bind(task['items'],result,version=shared_claims.COMMON)
                        except (ValueError,KeyError,TypeError) as exc:
                            errors.append({'request_sha256':key,'error':str(exc)})
                            save('errors/'+key,{'result':result,'error':errors[-1]})
                            if result.get('raw') is None and result.get('errors'):raise RuntimeError('Incomplete request requires reconciliation')
                            continue
                        records.append(record);save('proposals/'+key,record)
                        save('progress/'+key,{'group_index':i,'records':len(records),'candidates':len(shared_claims.candidates(records)),'semantic_approval':False})
                output={'records':records,'candidates':shared_claims.candidates(records),'holds':holds,'errors':errors,
                    'unassessed_group_indices':plan['unassessed_group_indices'],'actual_agents':0,'quality_gate_passed':False}
                save('output',output)
            report={'artifact_kind':VERSION,'plan_sha256':sha(directory/'plan.json'),'output_sha256':sha(directory/'artifacts/output.json'),
                'records':len(records),'candidates':len(output['candidates']),'reused':reused,'elapsed_seconds':time.monotonic()-started,
                'unassessed_groups':len(plan['unassessed_group_indices']),'actual_agents':0,'quality_gate_passed':False}
            write(directory/'completed.json',report);return report
        except BaseException as exc:
            write(directory/'failed.json',{'exception':type(exc).__name__,'message':str(exc),'elapsed_seconds':time.monotonic()-started});raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','run']);p.add_argument('directory',type=Path)
    a=p.parse_args();print(prepare(a.directory) if a.action=='prepare' else run(a.directory),flush=True)
