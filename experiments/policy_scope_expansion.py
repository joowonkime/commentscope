"""Freeze the entire existing snapshot; compare only previously untested sources.

Actual previous96 and new903 comparisons remain separately receipted calls.
No independent G3/G4 claim, criterion change or post-success source selection.
Only executed nomination/provider dependencies are frozen, so independent
Factory/ownership implementation can proceed while this CPU census runs.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import os

from commentscope.factory import policy_stance_hypotheses as stance,policy_stance_union as union,fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources as registry
from commentscope.ingestion import load_snapshot
from commentscope.providers import evidence_nli,host_resources
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.completed_policy_stance import load as completed_stance
from experiments.compare_backend_discovery import check_quota,quota_watch,SCOPE
from experiments.corpus_resource_guard import host_observation
from experiments.framed_corpus_pipeline import experiment_lock

ROOT=Path('runs/compare-backend-20261023-v1')
OLD=ROOT/'M1-policy-stance-discovery-v1'
VERSION='full-snapshot-policy-census-20261023-v2'
BATCH_SIZE=301
BOUNDARIES=['src/commentscope/factory/policy_stance_hypotheses.py','src/commentscope/factory/policy_stance_union.py',
    'src/commentscope/factory/minimal_claims.py','src/commentscope/factory/position_frames.py',
    'src/commentscope/factory/nli_fact_records.py','src/commentscope/factory/fact_checks.py',
    'src/commentscope/factory/automatic_contract.py','src/commentscope/factory/claim_clusters.py',
    'src/commentscope/contracts/perspective_draft.py','src/commentscope/providers/local_nli.py',
    'src/commentscope/providers/evidence_nli.py','src/commentscope/providers/budget.py',
    'src/commentscope/providers/host_resources.py','src/commentscope/storage.py',
    'experiments/policy_scope_expansion.py','experiments/completed_policy_stance.py',
    'experiments/compare_backend_discovery.py','experiments/corpus_resource_guard.py',
    'experiments/framed_corpus_pipeline.py','runs/factory-r5-20261017-v1/account_quota_guard.py']


def prepare(directory):
    check_quota()
    if directory.exists() or not directory.resolve().is_relative_to(Path('runs').resolve()):raise ValueError('New private full-snapshot census required')
    previous=read_json(SCOPE);old_plan=read_json(OLD/'plan.json')
    snapshot=load_snapshot(Path(previous['snapshot'])).snapshot;fact_checks.live(snapshot.usage.expires_at)
    lookup=registry(snapshot,include_video_context=True);all_sources=[lookup[sid] for sid in sorted(lookup)]
    originals=[lookup[sid] for sid in old_plan['scope_ids']]
    old_record,old_request,old_response,proof=completed_stance(OLD,deployment=previous['deployment'],sources=originals)
    new_sources=[s for s in all_sources if s['id'] not in {s['id'] for s in originals}]
    if len(all_sources)!=999 or len(originals)!=96 or len(new_sources)!=903:raise ValueError('Exact full existing999/previous96/new903 scope required')
    source_batches=[new_sources[i:i+BATCH_SIZE] for i in range(0,len(new_sources),BATCH_SIZE)]
    requests=[stance.invocation(batch,old_record['topic'],old_record['alias']) for batch in source_batches]
    write(directory/'all-sources.json',all_sources);write(directory/'sources.json',new_sources)
    write(directory/'previous-record.json',old_record);write(directory/'previous-response-proof.json',proof)
    plan={'artifact_kind':VERSION,'phase':'pre-frozen-full-existing-snapshot-expansion',
        'at':datetime.now(timezone.utc).isoformat(),'snapshot':previous['snapshot'],'expires_at':snapshot.usage.expires_at,
        'scope_ids':[s['id'] for s in new_sources],'full_scope_ids':[s['id'] for s in all_sources],
        'previous_scope_ids':[s['id'] for s in originals],'source_scope_counts':{'full':999,'previous':96,'new':903},
        'reason':'The whole96 census and strict independent admission produced only1favorable/3unfavorable sources; no two valid Agents. Freeze all remaining same-snapshot originals instead of retuning or coercing held statements. Source syntax/ownership/fact issues remain separate required repairs.',
        'selection':'Every canonical original in the existing video, IDs fixed before this inference. No gold labels, winning-source selection or new snapshot.',
        'topic':old_record['topic'],'alias':old_record['alias'],'deployment':previous['deployment'],
        'classifier':previous['classifier'],'budget':previous['budget'],'limits':previous['limits'],
        'resource_policy':previous['resource_policy'],'timeout_seconds':previous['limits']['fact_batch_seconds'],
        'model_files':{p:h for p,h in previous['model_files'].items() if 'MoritzLaurer' in p},
        'sources_sha256':digest(new_sources),'source_batch_ids':[[s['id'] for s in batch] for batch in source_batches],
        'requests':requests,'request_sha256':[digest(request) for request in requests],
        'inputs':{str(p):sha(p) for p in [SCOPE,Path(previous['snapshot']),OLD/'plan.json',OLD/'completed.json',
            ROOT/'M1-policy-factory-v1-result.json',directory/'all-sources.json',directory/'sources.json',
            directory/'previous-record.json',directory/'previous-response-proof.json']},
        'code_sha256':{p:sha(p) for p in BOUNDARIES},
        'freeze_scope':'Executed nomination/provider/validation/resource dependencies only. Other unused Factory/ownership modules may change; pinned dependencies may not.',
        'expected_calls':{'new_Qwen':0,'new_embedding':0,'new_NLI_batches':3,'new_forward_pairs':1806,'old_forward_pairs_reused':192},
        'evaluation':'Nominees only; raw/own-policy/own-evidence/owner/fact gates still needed. Error/overflow stays held. No valid support/Agent approval from this census.',
        'decision':'If full census has sufficient nominees, use strict source admission and closed own-node evidence before counting3 per core. Otherwise record the actual limitation; do not change acceptance or invent support.',
        'independent_G3':False,'G4_complete':False,'quality_gate_passed':False}
    write(directory/'plan.json',plan)
    return {'prepared':True,'frozen_all_sources':999,'previous_sources_reused':96,'new_sources':903,'new_pairs':1806,'new_batches':3}


def run(directory):
    check_quota()
    with experiment_lock(directory),quota_watch():
        plan=read_json(directory/'plan.json');fact_checks.live(plan['expires_at'])
        for field in ['inputs','code_sha256','model_files']:
            for path,expected in plan[field].items():
                if sha(path)!=expected:raise ValueError('Frozen expansion input changed: '+path)
        if (directory/'started.json').exists():raise RuntimeError('Prior expansion attempt exists; reconcile, never retry implicitly')
        sources=read_json(directory/'sources.json');lookup={s['id']:s for s in sources}
        if digest(sources)!=plan['sources_sha256']:raise ValueError('Expansion inventory changed')
        batches=[[lookup[sid] for sid in ids] for ids in plan['source_batch_ids']]
        requests=[stance.invocation(batch,plan['topic'],plan['alias']) for batch in batches]
        if requests!=plan['requests'] or [digest(r) for r in requests]!=plan['request_sha256']:
            raise ValueError('Pre-frozen source partition/request changed')
        write(directory/'started.json',{'pid':os.getpid(),'plan_sha256':sha(directory/'plan.json')})
        budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'],limit_seconds=None)
        records=[];states=Counter()
        for number,(batch,request) in enumerate(zip(batches,requests,strict=True),1):
            check_quota();prefix=f'{number:04}-policy-value-census'
            write(directory/'calls'/(prefix+'.request.json'),{'request':request,'request_sha256':digest(request),
                'plan_sha256':sha(directory/'plan.json'),'timeout_seconds':plan['timeout_seconds']})
            with host_resources.watch(directory/'resources'/f'{number:04}',plan['resource_policy'],host_observation):
                response=budget.call(request,sha(directory/'plan.json'),timeout_seconds=plan['timeout_seconds'],provider=evidence_nli.generate)
                write(directory/'calls'/(prefix+'.result.json'),response);check_quota()
            record=stance.bind(batch,plan['topic'],plan['alias'],response);records.append(record)
            states.update(row['state'] for row in response['results'])
            write(directory/'artifacts'/f'part-{number:04}.json',record)
            write(directory/'part-completions'/f'{number:04}.json',{'request_sha256':digest(request),
                'record_sha256':sha(directory/'artifacts'/f'part-{number:04}.json'),
                'result_sha256':sha(directory/'calls'/(prefix+'.result.json'))})
            print({'completed_new_batch':number,'sources':len(batch),'pairs':len(response['results']),
                'states':dict(Counter(row['state'] for row in response['results']))},flush=True)
        combined=union.combine([read_json(directory/'previous-record.json'),*records],read_json(directory/'all-sources.json'))
        write(directory/'artifacts/combined-record.json',combined);candidates=union.candidates(combined)
        write(directory/'artifacts/candidates.json',candidates)
        report={'artifact_kind':VERSION,'new_source_scope':len(sources),'full_source_scope':len(combined['sources']),
            'new_comparisons':sum(len(r['response']['results']) for r in records),'old_comparisons_reused':192,
            'new_states':dict(states),'candidate_nominee_counts':{c['id']:len(c['nominees']) for c in candidates},
            'actual_valid_supports':0,'actual_agents':0,'new_Qwen_calls':0,'new_NLI_batches':len(records),
            'no_synthetic_joint_call':True,'independent_G3':False,'quality_gate_passed':False}
        write(directory/'report.json',report)
        write(directory/'completed.json',{'plan_sha256':sha(directory/'plan.json'),'report_sha256':sha(directory/'report.json'),
            'combined_record_sha256':sha(directory/'artifacts/combined-record.json'),
            'part_record_sha256':{f'{i:04}':sha(directory/'artifacts'/f'part-{i:04}.json') for i in range(1,len(records)+1)}})
        return report



if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run']);parser.add_argument('directory',type=Path)
    args=parser.parse_args();print(prepare(args.directory) if args.action=='prepare' else run(args.directory),flush=True)
