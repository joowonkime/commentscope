"""Matched full-GPU 8B deployment with a bounded optional reasoning phase.

Same frozen targets/full sources/reference100 and criteria. The local binary's
--help documents the reasoning controls. Private reasoning is never UI content.
"""
import argparse
from contextlib import closing, nullcontext
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from commentscope.agents.runtime import request
from commentscope.factory import scoped_discovery as core
from commentscope.factory import condition_guard
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments import fact_evidence_probe as base
from experiments.scoped_discovery_probe import code_hashes,validate
from experiments.audit_model_compare import owned_server


def prepare(directory,source,thinking,*,plumbing=False):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    original=read_json(source/'plan.json');ref=read_json(source/'references.json')
    if read_json(source/'reference-frozen.json')['sha256']!=sha(source/'references.json'):raise ValueError('Reference changed')
    plan=deepcopy(original)
    plan.update(artifact_kind='bounded-reasoning-membership-0.1',code_sha256=code_hashes(),
                inputs={str(source/name):sha(source/name) for name in ['plan.json','references.json','reference-frozen.json']})
    plan['runtime'].update(context=4096,gpu_layers='all',template_kwargs={'enable_thinking':thinking},
                           reasoning='on' if thinking else 'off',reasoning_budget=256 if thinking else 0,
                           max_tokens=512 if thinking else 180)
    plan['plumbing_only']=plumbing;plan['reference_source']=str(source)
    if plumbing:
        plan['rows']=[]
        cases=[('S1','If I received a guaranteed income, I would still work as a nurse.',
                'I would keep working if I received a guaranteed income.','supported'),
               ('S2','People claim guaranteed income stops everyone working. I disagree; I would still work.',
                'I think nobody would work if everyone received guaranteed income.','unsupported')]
        for rid,text,target,expected in cases:
            claim={'id':'C','text':target,'kind':'fact','scope':{'entity':'','time':'','conditions':''},'requires':[]}
            req=core.judge_request(text,claim)
            plan['rows'].append({'id':rid,'text':text,'claim':claim,'request':req,'expected':expected})
        plan['evaluation_ids']=['S1','S2']
    for row in plan['rows']:
        row['request']['max_tokens']=plan['runtime']['max_tokens'];row['request_sha256']=digest(row['request'])
    plan['budget']={'cycle_id':base.CYCLE,'timeout_seconds':90,'reasoning_tokens':256 if thinking else 0,'repairs':0,'retries':0}
    plan['deployment_scope']='Full GPU/context4096 operational deployment; compare reasoning on/off under matched resource settings, not historical CPU-offloaded speed.'
    write(directory/'plan.json',plan)
    print({'prepared':True,'rows':len(plan['rows']),'thinking':thinking,'plumbing_only':plumbing},flush=True)


def prepare_resume(directory,source,*,budget_path=base.DEFAULT_BUDGET):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    try:
        with socket.create_connection(('127.0.0.1',8091),timeout=.5):
            raise ValueError('Inference endpoint live; cannot prepare interruption recovery')
    except ConnectionRefusedError:pass
    original=read_json(source/'plan.json');old_sha=sha(source/'plan.json')
    if (original.get('artifact_kind')!='bounded-reasoning-membership-0.1'
            or read_json(source/'started.json')['plan_sha256']!=old_sha):
        raise ValueError('Invalid interrupted run')
    if any(sha(p)!=h for p,h in original['inputs'].items()):raise ValueError('Original inputs changed')
    if (source/'completed.json').exists():raise ValueError('Completed run does not need recovery')
    plan=deepcopy(original);reused={}
    with closing(sqlite3.connect(Path(budget_path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        for row in plan['rows']:
            if digest(row['request'])!=row['request_sha256']:raise ValueError('Request changed')
            path=source/(row['id']+'.json')
            if path.exists():
                item=read_json(path)
                if item['request_sha256']!=row['request_sha256']:raise ValueError('Record changed')
                result=item['result']
                if result['raw'] is not None and not result['errors'] and json.loads(result['raw'])!=result['output']:
                    raise ValueError('Parsed record changed')
                reused[row['id']]={'path':str(path),'sha256':sha(path)}
            elif db.execute('SELECT 1 FROM calls WHERE plan_sha=? AND request_sha=?',(old_sha,row['request_sha256'])).fetchone():
                raise ValueError('Recover interrupted ledger records before preparing continuation; never retry')
    if not reused:raise ValueError('No completed/recovered records to continue from')
    plan['reused_records']=reused
    plan['continuation_of']={'directory':str(source),'plan_sha256':old_sha,
                             'semantic_requests_changed':False,'retry_interrupted_calls':False}
    plan['inputs']={**original['inputs'],str(source/'plan.json'):old_sha,
                    str(source/'started.json'):sha(source/'started.json'),
                    **{v['path']:v['sha256'] for v in reused.values()}}
    plan['code_sha256']=code_hashes()
    validate(plan)
    write(directory/'plan.json',plan)
    print({'prepared_continuation':True,'reused':len(reused),'new_calls':len(plan['rows'])-len(reused)},flush=True)


def execute(directory):
    plan=read_json(directory/'plan.json');validate(plan)
    plan_sha=sha(directory/'plan.json');budget=InferenceBudget(base.DEFAULT_BUDGET,base.CYCLE)
    write(directory/'started.json',{'plan_sha256':plan_sha,'budget_before':budget.summary()})
    results={}
    for rid,record in plan.get('reused_records',{}).items():
        if sha(record['path'])!=record['sha256']:raise ValueError('Reused record changed')
        item=read_json(record['path']);item['reused_from']=record
        row=next(r for r in plan['rows'] if r['id']==rid)
        write(directory/(rid+'.json'),item)
        results[rid]=condition_guard.from_row(item['result'],row,plan.get('membership_guard'))
    server=owned_server(plan,'baseline',directory/'server') if len(results)<len(plan['rows']) else nullcontext()
    with server:
        for row in plan['rows']:
            if row['id'] in results:continue
            req=row['request'];raw_response=[]
            def call(s,d,c):
                response=budget.call(req,plan_sha,timeout_seconds=90)
                raw_response.append(response)
                return response
            try:
                result=request(req['system'],req['data'],req['schema'],call)
            except RuntimeError as exc:
                result={'raw':None,'output':None,'errors':['bounded_call_failed'],'seconds':None,'usage':None}
            item={'request_sha256':digest(req),'result':result,
                  'reasoning_nonempty':bool(raw_response and raw_response[0]['choices'][0]['message'].get('reasoning_content'))}
            write(directory/(row['id']+'.json'),item)
            results[row['id']]=condition_guard.from_row(result,row,plan.get('membership_guard'))
            print({'completed':row['id'],'verdict':results[row['id']],
                   'reasoning':item['reasoning_nonempty'],'seconds':result['seconds']},flush=True)
            if plan.get('stop_on_impossible') and not plan['plumbing_only']:
                from experiments.membership_checkpoint import checkpoint
                status=checkpoint(directory)
                if status['cannot_pass']:
                    status['stop_reason']='Fixed-denominator best-case bound cannot reach the preregistered gate.'
                    status['budget_after']=budget.summary()
                    write(directory/'early-stopped.json',status)
                    print({k:v for k,v in status.items() if k not in {'unexecuted_evaluation','budget_after'}},flush=True)
                    return
    ids=plan['evaluation_ids']
    refs=({r['id']:r['expected'] for r in plan['rows']} if plan['plumbing_only'] else
          read_json(Path(plan['reference_source'])/'references.json')['labels'])
    accepted=[i for i in ids if results[i]=='supported'];positive=[i for i in ids if refs[i]=='supported']
    true=sum(refs[i]=='supported' for i in accepted)
    precision=true/len(accepted) if accepted else 0;retention=true/len(positive) if positive else 0
    report={'actual':results,'accepted':len(accepted),'true_accepted':true,'positive_reference':len(positive),
            'precision':precision,'positive_retention':retention,
            'false_accepted':[i for i in accepted if refs[i]!='supported'],
            'missed_positive':[i for i in positive if results[i]!='supported'],
            'errors':[i for i in ids if results[i]=='error'],
            'development_gate_passed':not plan['plumbing_only'] and precision>=.95 and retention>=.8,
            'plumbing_only':plan['plumbing_only'],'quality_gate_passed':False,'independent_gold':False,
            'budget_after':budget.summary()}
    write(directory/'report.json',report)
    write(directory/'completed.json',{'plan_sha256':plan_sha,'report_sha256':sha(directory/'report.json'),
                                      'records':{r['id']:sha(directory/(r['id']+'.json')) for r in plan['rows']}})
    print({k:v for k,v in report.items() if k not in ['actual','budget_after']},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','prepare-resume','run']);p.add_argument('directory',type=Path)
    p.add_argument('--source',type=Path,default=Path('runs/atomic-membership-20261013'))
    p.add_argument('--thinking',action='store_true');p.add_argument('--plumbing',action='store_true')
    a=p.parse_args()
    if a.phase=='prepare':prepare(a.directory,a.source,a.thinking,plumbing=a.plumbing)
    elif a.phase=='prepare-resume':prepare_resume(a.directory,a.source)
    else:execute(a.directory)
