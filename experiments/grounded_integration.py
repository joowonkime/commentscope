"""Staged automatic typing -> detail membership -> evidence -> bundle assembly.

Offline source-reference labels are not loaded. Frozen requests and raw failures
survive each stage. The input source membership quality report is a development
qualification, not a per-comment human approval or a runtime repair file.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from commentscope.agents.runtime import request
from commentscope.factory import grounded_factory as factory, perspective_typing as typing
from commentscope.factory import scoped_discovery as discovery,nli_fact_records as nli_records
from commentscope.factory import membership_policy
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers.budget import InferenceBudget
from commentscope.providers import evidence_nli
from commentscope.storage import write_json_exclusive as write
from experiments import fact_evidence_probe as base
from experiments.scoped_discovery_probe import code_hashes,run_calls
from experiments.membership_checkpoint import checkpoint


def prepare(source,directory):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    gate=checkpoint(source)
    if not gate['development_gate_passed'] or not gate['all_relations_complete']:
        raise ValueError('Complete source fidelity gate required; no downstream promotion')
    previous=read_json(source/'plan.json');report=read_json(source/'report.json')
    if previous.get('membership_guard') is not None:
        raise ValueError('Experimental guarded policy is not bound to the staged runtime')
    if (not report['development_gate_passed'] or report['precision']<.95 or report['positive_retention']<.8
            or len(previous['evaluation_ids'])!=100 or len(set(previous['evaluation_ids']))!=100):
        raise ValueError('Source fidelity gate failed; no downstream promotion')
    policy=membership_policy.from_rows(previous['rows'])
    actual={}
    records={}
    for row in previous['rows']:
        stored=read_json(source/(row['id']+'.json'))
        if stored['request_sha256']!=digest(row['request']):raise ValueError('Source request changed')
        result=stored['result']
        if result['raw'] is not None and json.loads(result['raw'])!=result['output']:raise ValueError('Parsed source decision changed')
        actual[row['id']]=discovery.verdict(result);records[str(source/(row['id']+'.json'))]=sha(source/(row['id']+'.json'))
    if actual!=report['actual']:raise ValueError('Membership report does not replay')
    rows=[]
    for p in previous['proposals']:
        members={r['source_id']:r['text'] for r in previous['rows'] if r['candidate_id']==p['id'] and actual[r['id']]=='supported'}
        if len(members)<3:continue
        req=typing.invocation(p['claims']['C'],members)
        rows.append({'id':p['id'],'proposal':p,'members':members,'request':req,'request_sha256':digest(req)})
    plan={**deepcopy(previous),'artifact_kind':'grounded-integration-0.2','rows':rows,
          'membership_policy':policy,
          'core_rows':previous['rows'],'core_verdicts':actual,'code_sha256':code_hashes(),
          'inputs':{str(source/'plan.json'):sha(source/'plan.json'),str(source/'report.json'):sha(source/'report.json'),**records},
          'quality_gate_passed':False}
    write(directory/'plan.json',plan)
    print({'prepared_typing':len(rows),'source_precision':report['precision'],'source_retention':report['positive_retention']},flush=True)


def type_claims(directory):
    plan=read_json(directory/'plan.json')
    if plan.get('artifact_kind')!='grounded-integration-0.2':
        raise ValueError('Prepare a new plan with an explicit membership policy')
    policy=membership_policy.from_rows(plan['core_rows'])
    if policy!=plan['membership_policy']:raise ValueError('Membership policy changed')
    records=run_calls(directory,plan,plan['rows'],'typing')
    typed=[];deferred=[]
    for row in plan['rows']:
        result=records[row['id']]['result']
        try:
            if result['errors']:raise ValueError('Typing inference failed')
            value=typing.apply(row['proposal'],result['output'],row['members'])
            if value is None:deferred.append({'id':row['id'],'reason':result['output']['reason']})
            else:typed.append(value)
        except (ValueError,KeyError,TypeError) as exc:deferred.append({'id':row['id'],'reason':str(exc)})
    # Type/premise metadata changes, but the independently judged core text and
    # scope must stay identical. These are derived rows, not rewritten raw logs.
    byid={p['id']:p for p in typed};core_rows=[]
    for row in plan['core_rows']:
        if row['candidate_id'] not in byid:continue
        claim=byid[row['candidate_id']]['claims']['C']
        if membership_policy.invocation(policy,row['text'],claim)!=row['request']:raise ValueError('Typing changed the membership target')
        core_rows.append({**deepcopy(row),'claim':deepcopy(claim),'pretyping_claim_sha256':digest(row['claim'])})
    details=membership_policy.bind_rows(policy,factory.detail_requests(typed,core_rows,plan['core_verdicts']))
    write(directory/'typed.json',{'proposals':typed,'deferred':deferred,'core_rows':core_rows,'detail_rows':details})
    write(directory/'typed-frozen.json',{'sha256':sha(directory/'typed.json')})
    print({'typed_candidates':len(typed),'deferred':deferred,'detail_requests':len(details)},flush=True)


def details(directory):
    plan=read_json(directory/'plan.json');typed=read_json(directory/'typed.json')
    if read_json(directory/'typed-frozen.json')['sha256']!=sha(directory/'typed.json'):raise ValueError('Typed requests changed')
    rows=typed['detail_rows'];records=run_calls(directory,plan,rows,'details')
    actual={r['id']:discovery.verdict(records[r['id']]['result']) for r in rows}
    evidence=read_json('runs/fact-evidence-development-20261013/plan.json')
    model=read_json('runs/mvp-agreed-20261013/nli-bound-records.json')['model']
    model['runtime_sha256']=digest({p:sha(p) for p in ['src/commentscope/providers/evidence_nli.py','src/commentscope/providers/local_nli.py']})
    from commentscope.providers.local_nli import REVISION
    model_root=Path('/home/taeng/.cache/huggingface/hub/models--MoritzLaurer--DeBERTa-v3-base-mnli-fever-anli/snapshots')/REVISION
    model_files={str(p):sha(p) for p in model_root.iterdir() if p.is_file()}
    if model_files[str(model_root/'model.safetensors')]!=model['weights_sha256']:raise ValueError('Classifier weights changed')
    bundle=factory.bundle(typed['proposals'],typed['core_rows'],plan['core_verdicts'],rows,actual,
                          expires_at=plan['expires_at'],model=model,documents=[evidence['document']])
    packets=factory.fact_packets(bundle,evidence['selections'])
    req=nli_records.invocation(packets)
    write(directory/'fact-plan.json',{'bundle':bundle,'packets':packets,'selections':evidence['selections'],
          'request':req,'request_sha256':digest(req),'code_sha256':code_hashes(),'model_files':model_files,
          'inputs':{str(directory/'plan.json'):sha(directory/'plan.json'),str(directory/'typed.json'):sha(directory/'typed.json'),
                    'runs/fact-evidence-development-20261013/plan.json':sha('runs/fact-evidence-development-20261013/plan.json')},
          'retrieval_scope':'Configured frozen Kela evidence library only; no open-web retrieval',
          'quality_gate_passed':False})
    print({'prepared_fact_claims':len(packets),'detail_supports':sum(v=='supported' for v in actual.values())},flush=True)


def facts(directory):
    plan=read_json(directory/'fact-plan.json')
    for field in ['inputs','code_sha256','model_files']:
        if any(sha(p)!=h for p,h in plan[field].items()):raise ValueError('Fact stage changed')
    if digest(plan['request'])!=plan['request_sha256']:raise ValueError('Fact request changed')
    write(directory/'facts-started.json',{'plan_sha256':sha(directory/'fact-plan.json')})
    bundle=plan['bundle']
    if plan['packets']:
        result=InferenceBudget(base.DEFAULT_BUDGET,base.CYCLE).call(plan['request'],sha(directory/'fact-plan.json'),timeout_seconds=240,provider=evidence_nli.generate)
        write(directory/'fact-result.json',result)
        records=nli_records.records(plan['packets'],bundle['model'],result,batch_request=plan['request'])
        bundle['checks']=[{'claim_id':packet['claim']['id'],'selections':plan['selections'],'record':record}
                          for packet,record in zip(plan['packets'],records,strict=True)]
    write(directory/'bundle.json',bundle)
    from commentscope.agents.grounded_inputs import compile_inputs
    compiled=compile_inputs(bundle);write(directory/'compiled.json',compiled)
    write(directory/'completed.json',{name+'_sha256':sha(directory/(name+'.json')) for name in ['plan','typed','fact-plan','bundle','compiled']})
    print({'screened_inputs':len(compiled['profiles']),'deferred':compiled['deferred'],'quality_gate_passed':False},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','typing','details','facts']);p.add_argument('directory',type=Path);p.add_argument('--source',type=Path)
    a=p.parse_args()
    if a.phase=='prepare':prepare(a.source,a.directory)
    elif a.phase=='typing':type_claims(a.directory)
    elif a.phase=='details':details(a.directory)
    else:facts(a.directory)
