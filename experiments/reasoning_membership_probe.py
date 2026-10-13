"""Matched full-GPU 8B deployment with a bounded optional reasoning phase.

Same frozen targets/full sources/reference100 and criteria. The local binary's
--help documents the reasoning controls. Private reasoning is never UI content.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from commentscope.agents.runtime import request
from commentscope.factory import scoped_discovery as core
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


def execute(directory):
    plan=read_json(directory/'plan.json');validate(plan)
    plan_sha=sha(directory/'plan.json');budget=InferenceBudget(base.DEFAULT_BUDGET,base.CYCLE)
    write(directory/'started.json',{'plan_sha256':plan_sha,'budget_before':budget.summary()})
    results={}
    with owned_server(plan,'baseline',directory/'server'):
        for row in plan['rows']:
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
            write(directory/(row['id']+'.json'),item);results[row['id']]=core.verdict(result)
            print({'completed':row['id'],'verdict':results[row['id']],
                   'reasoning':item['reasoning_nonempty'],'seconds':result['seconds']},flush=True)
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
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path)
    p.add_argument('--source',type=Path,default=Path('runs/atomic-membership-20261013'))
    p.add_argument('--thinking',action='store_true');p.add_argument('--plumbing',action='store_true')
    a=p.parse_args();prepare(a.directory,a.source,a.thinking,plumbing=a.plumbing) if a.phase=='prepare' else execute(a.directory)
