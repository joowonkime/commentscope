"""Fixed-threshold NLI and LLM intersection on a frozen source membership set."""
import argparse
from pathlib import Path
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers import evidence_nli as nli
from commentscope.providers.budget import InferenceBudget
from commentscope.providers.local_nli import MODEL,REVISION,THRESHOLD
from commentscope.storage import write_json_exclusive as write
from experiments import fact_evidence_probe as base
from experiments.scoped_discovery_probe import code_hashes
from commentscope.factory.nli_fact_records import validate_result


def prepare(directory,source):
    if directory.exists():raise ValueError('Never overwrite an attempt')
    original=read_json(source/'plan.json')
    request={'system':nli.VERSION,'schema':{},'max_tokens':1,'data':{'cases':[
        {'id':r['id'],'text':r['claim']['text'],'evidence':[{'id':r['source_id'],'text':r['text']}]} for r in original['rows']]}}
    root=Path('/home/taeng/.cache/huggingface/hub/models--MoritzLaurer--DeBERTa-v3-base-mnli-fever-anli/snapshots')/REVISION
    plan={'request':request,'request_sha256':digest(request),'source':str(source),
          'inputs':{str(source/name):sha(source/name) for name in ['plan.json','references.json','reference-frozen.json','report.json']},
          'code_sha256':code_hashes(),'model_files':{str(p):sha(p) for p in root.iterdir() if p.is_file()},
          'threshold':THRESHOLD,'expires_at':original['expires_at'],'timeout_seconds':240,
          'criteria':original['criteria'],'scope':'Same offline development labels; not independent gold.'}
    write(directory/'plan.json',plan)
    print({'prepared':True,'relations':len(original['rows'])},flush=True)


def summarize(plan,result):
    source=Path(plan['source']); original=read_json(source/'plan.json')
    refs=read_json(source/'references.json')['labels']; llm=read_json(source/'report.json')['actual']
    for case,row in zip(plan['request']['data']['cases'],result['results'],strict=True):
        validate_result(row,case,result['metadata'])
    byid={r['id']:r['state'] for r in result['results']}
    output={}
    for variant in ['nli_only','intersection']:
        actual={r['id']:('supported' if byid[r['id']]=='supported' and (variant=='nli_only' or llm[r['id']]=='supported') else 'error' if byid[r['id']]=='error' else 'unassessed') for r in original['rows']}
        accepted=[i for i in original['evaluation_ids'] if actual[i]=='supported']; positive=[i for i in original['evaluation_ids'] if refs[i]=='supported']
        true=sum(refs[i]=='supported' for i in accepted)
        precision=true/len(accepted) if accepted else 0;recall=true/len(positive) if positive else 0
        output[variant]={'actual':actual,'accepted':len(accepted),'true_accepted':true,'positive_reference':len(positive),
                         'precision':precision,'positive_retention':recall,
                         'false_accepted':[i for i in accepted if refs[i]!='supported'],
                         'missed_positive':[i for i in positive if actual[i]!='supported'],
                         'development_gate_passed':precision>=.95 and recall>=.8,'quality_gate_passed':False}
    return output


def run(directory):
    plan=read_json(directory/'plan.json')
    from commentscope.factory.fact_checks import live
    live(plan['expires_at'])
    for field in ['inputs','code_sha256','model_files']:
        if any(sha(p)!=h for p,h in plan[field].items()):raise ValueError('Frozen identity changed')
    if digest(plan['request'])!=plan['request_sha256']:raise ValueError('Request changed')
    write(directory/'started.json',{'plan_sha256':sha(directory/'plan.json')})
    result=InferenceBudget(base.DEFAULT_BUDGET,base.CYCLE).call(plan['request'],sha(directory/'plan.json'),timeout_seconds=240,provider=nli.generate)
    write(directory/'result.json',result)
    report=summarize(plan,result);write(directory/'report.json',report)
    write(directory/'completed.json',{k+'_sha256':sha(directory/(k+'.json')) for k in ['plan','result','report']})
    print({k:{f:v for f,v in row.items() if f!='actual'} for k,row in report.items()},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['prepare','run']);p.add_argument('directory',type=Path);p.add_argument('--source',type=Path)
    a=p.parse_args();prepare(a.directory,a.source) if a.phase=='prepare' else run(a.directory)
