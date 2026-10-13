"""Cached, all-candidate range-typing integration; never fresh or quality approval.

Reuses frozen target selection and core relations without reading review labels.
Only the typing quotation interface changes. Reasons, facts and compilation keep
their existing policies; a failed factual premise is never removed to get agents.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.factory import grounded_factory as factory, membership_policy
from commentscope.factory import span_typing, target_ranking, nli_fact_records as records
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.fact_checks import live
from commentscope.factory.scoped_discovery import verdict
from commentscope.providers import evidence_nli
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import command, file_hash, owned_server
from experiments.fresh_grounded_pipeline import Runner, classify
from experiments.scoped_discovery_probe import code_hashes
from experiments.target_ranking_probe import choose, VERSION as RANKING_VERSION

VERSION='cached-source-range-integration-0.1'


def frozen_typing(selection, policy):
    """Bind every selected candidate; no hand-picked subset or text repair."""
    proposals=selection['proposals'];rows=selection['rows'];actual=selection['actual']
    ids=[p['id'] for p in proposals]
    if len(set(ids))!=len(ids) or len({r['id'] for r in rows})!=len(rows):
        raise ValueError('Duplicate candidate or relation ID')
    if set(actual)!={r['id'] for r in rows} or any(r['candidate_id'] not in ids for r in rows):
        raise ValueError('Incomplete source inventory')
    if len({(r['candidate_id'],r['source_id']) for r in rows})!=len(rows):
        raise ValueError('Duplicate canonical source relation')
    requests=[];max_details=0
    for p in proposals:
        members={}
        for row in rows:
            if row['candidate_id']!=p['id']:continue
            req=membership_policy.invocation(policy,row['text'],p['claims']['C'])
            if (row['text']!=p['sources'][row['source_id']] or row['claim']!=p['claims']['C']
                    or req!=row['request'] or digest(req)!=row['request_sha256']):
                raise ValueError('Core source/target/request changed')
            if actual[row['id']]=='supported':members[row['source_id']]=row['text']
        if len(members)<3:raise ValueError('Selected candidate lacks three sources')
        req=span_typing.invocation(p['claims']['C'],members)
        requests.append({'candidate_id':p['id'],'request':req,'request_sha256':digest(req)})
        max_details+=2*len(members)
    if max_details>40:raise ValueError('Cached detail budget exceeded')
    return requests,max_details


def prepare(directory, source):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    ranked_plan=read_json(source/'plan.json');completed=read_json(source/'completed.json')
    if ranked_plan['artifact_kind']!=RANKING_VERSION:raise ValueError('Expected ranked source candidates')
    live(ranked_plan['expires_at'])
    # Historical code is not silently rerun under its old plan. Bind its inputs,
    # raw outputs and replayable selection while freezing this new code version.
    files={Path(p):h for p,h in ranked_plan['inputs'].items()}
    original=read_json(Path(ranked_plan['source'])/'plan.json')
    files.update({Path(p):h for p,h in original['inputs'].items()})
    if any(sha(p)!=h for p,h in files.items()):raise ValueError('Historical input changed')
    names=['plan.json','completed.json','ranking.json','selection.json',
           'alternative-requests.json','alternative-verdicts.json',
           'membership-server/runtime.json','membership-server/stopped.json']
    files.update({source/n:sha(source/n) for n in names})
    selected=read_json(source/'selection.json');ranked=read_json(source/'ranking.json')
    rows=read_json(source/'alternative-requests.json');actual=read_json(source/'alternative-verdicts.json')
    if completed['selection_sha256']!=sha(source/'selection.json'):
        raise ValueError('Selection output changed')
    rank_request=source/'calls/0001-target-ranking.request.json'
    rank_result=source/'calls/0001-target-ranking.result.json'
    rr=read_json(rank_request)
    if (rr['request']!=ranked_plan['ranking_request'] or rr['request_sha256']!=digest(rr['request'])
            or rr['plan_sha256']!=sha(source/'plan.json')):raise ValueError('Ranking request changed')
    if target_ranking.assemble(ranked_plan['proposals'],ranked_plan['units'],ranked_plan['scheduled'],read_json(rank_result))!=ranked:
        raise ValueError('Ranking replay changed')
    files.update({p:sha(p) for p in (rank_request,rank_result)})
    for row,path in zip(rows,sorted((source/'calls').glob('*-membership.request.json')),strict=True):
        rp=path.with_name(path.name.replace('.request.','.result.'));req=read_json(path);result=read_json(rp)
        if (req['request']!=row['request'] or req['request_sha256']!=digest(row['request'])
                or req['plan_sha256']!=sha(source/'plan.json') or verdict(result)!=actual[row['id']]
                or (not result['errors'] and json.loads(result['raw'])!=result['output'])):
            raise ValueError('Alternative raw membership binding changed')
        files.update({p:sha(p) for p in (path,rp)})
    replay=choose(ranked_plan['proposals'],ranked_plan['baseline_rows'],ranked_plan['baseline_actual'],ranked['alternatives'],rows,actual)
    if selected!=replay:raise ValueError('All-candidate selection replay changed')
    deployment=deepcopy(ranked_plan['deployment'])
    if (read_json(source/'membership-server/runtime.json')['command']!=command(deployment,'baseline')
            or read_json(source/'membership-server/stopped.json')['returncode']!=0):
        raise ValueError('Historical deployment mismatch')
    policy=ranked_plan['membership_policy']
    if original['membership_policy']!=policy:raise ValueError('Membership policy changed')
    typing_requests,max_details=frozen_typing(selected,policy)
    plan={'artifact_kind':VERSION,'expires_at':ranked_plan['expires_at'],'source':str(source),
          'inputs':{str(p):h for p,h in files.items()},'code_sha256':code_hashes(),
          'model_files':ranked_plan['model_files'],'deployment':deployment,'membership_policy':policy,
          'selection':selected,'typing_requests':typing_requests,'typing_version':span_typing.VERSION,
          'classifier':original['classifier'],'documents':original['documents'],'selections':original['selections'],
          'evaluation':original['evaluation'],'budget':ranked_plan['budget'],
          'limits':{'analysis_seconds':900,'call_seconds':90,'fact_seconds':240,'detail_relations':max_details},
          'fresh_analysis':False,'runtime_reference_labels':False,'quality_gate_passed':False}
    write(directory/'plan.json',plan)
    print({'prepared':True,'candidates':len(typing_requests),'max_detail_relations':max_details,
           'typing_request_bytes':[len(json.dumps(r['request']).encode()) for r in typing_requests]},flush=True)


def execute(directory):
    started=time.monotonic();plan=read_json(directory/'plan.json');live(plan['expires_at'])
    if plan['artifact_kind']!=VERSION or plan['typing_version']!=span_typing.VERSION:raise ValueError('Unknown trial')
    for key in ('inputs','code_sha256','model_files'):
        if any(sha(p)!=h for p,h in plan[key].items()):raise ValueError('Frozen input/code/model changed')
    for info in (plan['deployment']['server'],plan['deployment']['models']['baseline']):
        if file_hash(info['path'])!=info['sha256']:raise ValueError('Deployment changed')
    expected,maximum=frozen_typing(plan['selection'],plan['membership_policy'])
    if expected!=plan['typing_requests'] or maximum!=plan['limits']['detail_relations']:
        raise ValueError('Frozen typing inventory changed')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    budget=InferenceBudget(Path(plan['budget']['ledger']),plan['budget']['cycle_id'])
    runner=Runner(directory,plan,budget);runner.started=started
    write(directory/'started.json',{'plan_sha256':runner.plan_sha,'budget_before':budget.summary(),'fresh_analysis':False})
    try:
        selected=plan['selection'];detail_actual={}
        with owned_server(plan['deployment'],'baseline',directory/'membership-server'):
            typed,core_rows,deferred=classify(selected['proposals'],selected['rows'],selected['actual'],runner,typer=span_typing)
            details=membership_policy.bind_rows(plan['membership_policy'],factory.detail_requests(typed,core_rows,selected['actual']))
            if len(details)>maximum:raise ValueError('Detail relation budget exceeded')
            write(directory/'typed.json',{'proposals':typed,'core_rows':core_rows,'details':details,'deferred':deferred})
            for row in details:detail_actual[row['id']]=verdict(runner.call('detail',row['request']))
        write(directory/'detail-verdicts.json',detail_actual)
        bundle=factory.bundle(typed,core_rows,selected['actual'],details,detail_actual,
                expires_at=plan['expires_at'],model=plan['classifier'],documents=plan['documents'])
        packets=factory.fact_packets(bundle,plan['selections'])
        if packets:
            req=records.invocation(packets)
            judged=runner.call('facts',req,provider=evidence_nli.generate,maximum=plan['limits']['fact_seconds'])
            bound=records.records(packets,bundle['model'],judged,batch_request=req)
            bundle['checks']=[{'claim_id':p['claim']['id'],'selections':plan['selections'],'record':r} for p,r in zip(packets,bound,strict=True)]
        compiled=compile_inputs(bundle)
        write(directory/'bundle.json',bundle);write(directory/'compiled.json',compiled)
        report={'artifact_kind':VERSION,'elapsed_seconds':time.monotonic()-started,'fresh_analysis':False,
                'selected_candidates':len(selected['proposals']),'typed_candidates':len(typed),'typing_deferred':deferred,
                'detail_relations':len(details),'fact_claims':len(packets),'screened_inputs':len(compiled['profiles']),
                'qualified_agents':0,'quality_gate_passed':False,'runtime_reference_labels':False,
                'evaluation':plan['evaluation'],'budget_after':budget.summary(),
                'bundle_sha256':sha(directory/'bundle.json'),'compiled_sha256':sha(directory/'compiled.json'),
                'remaining_gates':['actual_core_and_reason_audit','actual_answers_and_abstention','actual_comparison_latency','fresh_analysis']}
        write(directory/'completed.json',report)
        print({k:v for k,v in report.items() if k not in ('budget_after','evaluation')},flush=True)
    except BaseException as exc:
        write(directory/'failed.json',{'exception_type':type(exc).__name__,'elapsed_seconds':time.monotonic()-started,
                                     'budget_after':budget.summary(),'quality_gate_passed':False})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path)
    p.add_argument('--source',type=Path);a=p.parse_args()
    if a.phase=='prepare' and a.source is None:p.error('prepare requires --source')
    if a.phase=='prepare':prepare(a.directory,a.source)
    else:execute(a.directory)
