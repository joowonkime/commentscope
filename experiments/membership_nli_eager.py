"""Freeze/run the predeclared NLI variant without waiting for the LLM batch.

Every source pair is fixed first. References are hash-bound for evaluation only;
neither labels nor LLM verdicts enter the classifier request.
"""
import argparse
from pathlib import Path
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.fact_checks import live
from commentscope.factory.nli_fact_records import validate_result
from commentscope.providers import evidence_nli as nli
from commentscope.providers.local_nli import REVISION,THRESHOLD
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments import fact_evidence_probe as base
from experiments.scoped_discovery_probe import code_hashes
from experiments.scoped_membership_nli import summarize


def prepare(directory,source):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    old=read_json(source/'plan.json')
    req={'system':nli.VERSION,'schema':{},'max_tokens':1,'data':{'cases':[
        {'id':r['id'],'text':r['claim']['text'],'evidence':[{'id':r['source_id'],'text':r['text']}]} for r in old['rows']]}}
    root=Path('/home/taeng/.cache/huggingface/hub/models--MoritzLaurer--DeBERTa-v3-base-mnli-fever-anli/snapshots')/REVISION
    write(directory/'plan.json',{'source':str(source),'request':req,'request_sha256':digest(req),
          'inputs':{str(source/name):sha(source/name) for name in ['plan.json','references.json','reference-frozen.json']},
          'code_sha256':code_hashes(),'model_files':{str(p):sha(p) for p in root.iterdir() if p.is_file()},
          'threshold':THRESHOLD,'expires_at':old['expires_at'],'criteria':old['criteria'],
          'timeout_seconds':240,'reference_input_to_model':False,'scope':'Predeclared same-set NLI diagnostic and intersection.'})
    print({'prepared':True,'pairs':len(old['rows'])},flush=True)


def run(directory):
    plan=read_json(directory/'plan.json');live(plan['expires_at'])
    for field in ['inputs','code_sha256','model_files']:
        if any(sha(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen identity changed')
    if digest(plan['request'])!=plan['request_sha256']:raise ValueError('Request changed')
    write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
    result=InferenceBudget(base.DEFAULT_BUDGET,base.CYCLE).call(plan['request'],sha(directory/'plan.json'),timeout_seconds=240,provider=nli.generate)
    write(directory/'result.json',result)
    for case,row in zip(plan['request']['data']['cases'],result['results'],strict=True):validate_result(row,case,result['metadata'])
    write(directory/'batch-completed.json',{name+'_sha256':sha(directory/(name+'.json')) for name in ['plan','result']})
    print({'batch_complete':True,'pairs':result['forward_pairs'],'errors':sum(r['state']=='error' for r in result['results'])},flush=True)


def assess(directory):
    plan=read_json(directory/'plan.json');complete=read_json(directory/'batch-completed.json')
    if complete!={name+'_sha256':sha(directory/(name+'.json')) for name in ['plan','result']}:raise ValueError('NLI artifact changed')
    for p,h in plan['inputs'].items():
        if sha(p)!=h:raise ValueError('Frozen input changed')
    report=summarize(plan,read_json(directory/'result.json'));write(directory/'report.json',report)
    write(directory/'completed.json',{**complete,'report_sha256':sha(directory/'report.json'),
          'llm_report_sha256':sha(Path(plan['source'])/'report.json')})
    print({k:{f:v for f,v in row.items() if f!='actual'} for k,row in report.items()},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run','assess']);p.add_argument('directory',type=Path);p.add_argument('--source',type=Path)
    a=p.parse_args()
    if a.phase=='prepare':prepare(a.directory,a.source)
    elif a.phase=='run':run(a.directory)
    else:assess(a.directory)
