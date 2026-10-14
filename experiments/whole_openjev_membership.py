"""Existing OpenJev CPU classifier on full, untruncated membership sources.

The old 500-character wrapper is replaced by a byte guard plus the SAME 512-token
ceiling. This is not commercial Jev, a download, threshold tuning or approval.
"""
import argparse
from pathlib import Path
import time
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.fact_checks import live
from commentscope.providers.local_openjev import LocalOpenJev,MODEL,REVISION,SUBFOLDER,TEMPLATE,LABEL_MAP
from commentscope.providers.local_nli import decide,THRESHOLD
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments import fact_evidence_probe as base
from experiments.scoped_discovery_probe import code_hashes

VERSION='whole-source-openjev-membership-0.1'


def generate(system,data,schema,max_tokens):
    if system!=VERSION or schema!={} or max_tokens!=1 or set(data)!={'cases'}:raise ValueError('Batch contract changed')
    model=LocalOpenJev(device='cpu');results=[]
    for case in data['cases']:
        started=time.perf_counter();row={'id':case['id'],'errors':[],'raw':None,'scores':None,'relation':None}
        try:
            if not all(isinstance(t,str) and t.strip() and len(t.encode())<=30000 for t in [case['source'],case['target']]):raise ValueError('Text byte limit')
            encoded=model.tokenizer(TEMPLATE.format(premise=case['source'],hypothesis=case['target']),return_tensors='pt',truncation=False)
            row['input_tokens']=int(encoded['input_ids'].shape[1])
            if row['input_tokens']>512:raise ValueError('Token limit; not truncated')
            with model.torch.inference_mode():logits=model.model(**encoded).logits[0].float()
            row['raw']=logits.tolist();row['scores']={LABEL_MAP[i]:v for i,v in enumerate(logits.softmax(dim=-1).tolist())}
            row['relation']=decide(row['scores'],THRESHOLD)
        except (ValueError,RuntimeError,OSError) as exc:row['errors']=[type(exc).__name__]
        row['seconds']=time.perf_counter()-started;results.append(row)
    return {'metadata':{**model.metadata,'adapter':VERSION,'max_chars_per_text':None,'max_bytes_per_text':30000},
            'results':results,'quality_gate_passed':False}


def prepare(directory,source):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    old=read_json(source/'plan.json')
    req={'system':VERSION,'schema':{},'max_tokens':1,
         'data':{'cases':[{'id':r['id'],'source':r['text'],'target':r['claim']['text']} for r in old['rows']]}}
    root=Path('/home/taeng/.cache/huggingface/hub/models--AlexWortega--openjev/snapshots')/REVISION/SUBFOLDER
    plan={'request':req,'request_sha256':digest(req),'source':str(source),
          'inputs':{str(source/name):sha(source/name) for name in ['plan.json','references.json','reference-frozen.json','early-stopped.json']},
          'code_sha256':code_hashes(),'model_files':{str(p):sha(p) for p in root.iterdir() if p.is_file()},
          'model':{'name':MODEL,'revision':REVISION,'subfolder':SUBFOLDER,'device':'cpu','threshold':THRESHOLD},
          'expires_at':old['expires_at'],'timeout_seconds':600,'criteria':old['criteria'],
          'scope':'Same 100 assistant-labeled development relations; all 137 full-source pairs retained. Not independent gold.',
          'adoption':'Diagnostic. Only consider a fresh full LLM intersection trial if normal retention can reach80 percent and known LLM false supports can be removed.'}
    write(directory/'plan.json',plan);print({'prepared':True,'pairs':len(old['rows'])},flush=True)


def run(directory):
    plan=read_json(directory/'plan.json');live(plan['expires_at'])
    for field in ['inputs','code_sha256','model_files']:
        if any(sha(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen identity changed')
    write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
    budget=InferenceBudget(base.DEFAULT_BUDGET,base.CYCLE)
    result=budget.call(plan['request'],sha(directory/'plan.json'),timeout_seconds=600,provider=generate)
    write(directory/'result.json',result)
    if [r['id'] for r in result['results']]!=[r['id'] for r in plan['request']['data']['cases']]:raise ValueError('Case inventory changed')
    for row in result['results']:
        if not row['errors'] and row['relation']!=decide(row['scores'],THRESHOLD):raise ValueError('Decision changed')
    source=Path(plan['source']);p=read_json(source/'plan.json');refs=read_json(source/'references.json')['labels']
    actual={r['id']:r['relation'] if not r['errors'] else 'error' for r in result['results']}
    positive=[i for i in p['evaluation_ids'] if refs[i]=='supported'];accepted=[i for i in p['evaluation_ids'] if actual[i]=='supports']
    true=sum(refs[i]=='supported' for i in accepted)
    report={'accepted':len(accepted),'true_accepted':true,'positive_reference':len(positive),
            'precision':true/len(accepted) if accepted else 0,'positive_retention':true/len(positive),
            'false_accepted':[i for i in accepted if refs[i]!='supported'],
            'missed_positive':[i for i in positive if actual[i]!='supports'],
            'errors':[i for i in p['evaluation_ids'] if actual[i]=='error'],
            'quality_gate_passed':False,'independent_gold':False,'budget_after':budget.summary()}
    write(directory/'report.json',report)
    write(directory/'completed.json',{name+'_sha256':sha(directory/(name+'.json')) for name in ['plan','result','report']})
    print({k:v for k,v in report.items() if k!='budget_after'},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path);p.add_argument('--source',type=Path)
    a=p.parse_args();prepare(a.directory,a.source) if a.phase=='prepare' else run(a.directory)
