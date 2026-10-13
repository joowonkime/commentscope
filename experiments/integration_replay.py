"""Continue a terminal cached trial without retrying any attempted inference."""
from collections import defaultdict
import json
from pathlib import Path
import sqlite3

from commentscope.agents.runtime import request
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import command
from experiments.fresh_grounded_pipeline import Runner

SEMANTIC_FIELDS = ('source','selection','typing_requests','typing_version',
                   'membership_policy','deployment','classifier','documents',
                   'selections','model_files','budget','limits','evaluation')


def bind_prefix(source, plan):
    """Bind the entire old prefix, including errors; never select good calls."""
    old=read_json(source/'plan.json');old_sha=sha(source/'plan.json')
    if (old.get('artifact_kind')!='cached-source-range-integration-0.3'
            or (source/'completed.json').exists() or not (source/'failed.json').exists()
            or read_json(source/'started.json')['plan_sha256']!=old_sha):
        raise ValueError('Expected terminal incomplete v0.3 trial')
    if any(old.get(k)!=plan.get(k) for k in SEMANTIC_FIELDS):
        raise ValueError('Continuation changed semantic inputs, deployment or limits')
    if (read_json(source/'membership-server/runtime.json')['command']!=command(plan['deployment'],'baseline')
            or read_json(source/'membership-server/stopped.json')['returncode']!=0):
        raise ValueError('Expected normally stopped owned server')
    # Only the integration orchestrator is replaced. Model-facing and policy
    # implementations must still match the historical frozen version.
    for p,h in old['code_sha256'].items():
        if p!='experiments/span_integration_probe.py' and sha(p)!=h:
            raise ValueError('Historical semantic code changed')
    if any(sha(p)!=h for p,h in old['inputs'].items()):
        raise ValueError('Historical input changed')
    files={str(source/n):sha(source/n) for n in ('plan.json','started.json','failed.json',
           'membership-server/runtime.json','membership-server/stopped.json')}
    records=[];ledger=defaultdict(list)
    with sqlite3.connect(Path(plan['budget']['ledger']).resolve().as_uri()+'?mode=ro',uri=True) as db:
        for req_sha,state,response in db.execute(
                'SELECT request_sha,state,response_json FROM calls WHERE plan_sha=? ORDER BY rowid',(old_sha,)):
            if state=='reserved':raise ValueError('Unfinished ledger reservation; never retry')
            ledger[req_sha].append((state,response))
    paths=sorted((source/'calls').glob('*.request.json'))
    if not paths:raise ValueError('No prefix to reuse')
    for i,path in enumerate(paths,1):
        prefix=path.name.removesuffix('.request.json')
        if prefix.split('-')[0]!=f'{i:04}' or prefix.split('-',1)[1] not in {'typing','detail'}:
            raise ValueError('Expected contiguous LLM call prefix')
        result_path=path.with_name(prefix+'.result.json')
        if not result_path.exists():raise ValueError('Missing response; recover ledger before continuing')
        req=read_json(path);result=read_json(result_path);rh=digest(req['request'])
        if req['plan_sha256']!=old_sha or req['request_sha256']!=rh or not ledger[rh]:
            raise ValueError('Historical request binding mismatch')
        state,response=ledger[rh].pop(0)
        if state=='ok':
            restored=request(None,None,None,lambda *_:json.loads(response))
            if any(restored[k]!=result[k] for k in ('raw','output','errors','usage')):
                raise ValueError('Historical response differs from ledger')
        elif (result['raw'] is not None or result['output'] is not None
              or result['errors']!=['bounded_call_failed']):
            raise ValueError('Failed call must remain a failed call')
        files.update({str(p):sha(p) for p in (path,result_path)})
        records.append({'prefix':prefix,'request_path':str(path),'result_path':str(result_path),
                        'request_file_sha256':sha(path),'result_file_sha256':sha(result_path)})
    if any(ledger.values()):raise ValueError('Unrepresented attempted call; never retry')
    if len(list((source/'calls').glob('*.result.json')))!=len(paths):
        raise ValueError('Unexpected response inventory')
    return records,files


class ReplayRunner(Runner):
    def call(self,stage,req,**kwargs):
        prefix=f'{self.seq+1:04}-{stage}'
        cached=self.plan.get('reused_calls',[])
        if self.seq>=len(cached):return super().call(stage,req,**kwargs)
        entry=cached[self.seq]
        if (entry['prefix']!=prefix or sha(entry['request_path'])!=entry['request_file_sha256']
                or sha(entry['result_path'])!=entry['result_file_sha256']):
            raise ValueError('Reused call changed')
        original=read_json(entry['request_path'])
        if original['request']!=req or original['request_sha256']!=digest(req):
            raise ValueError('Replay changed request or call order')
        result=read_json(entry['result_path']);self.seq+=1
        write(self.directory/'calls'/(prefix+'.request.json'),
              {'request':req,'request_sha256':digest(req),'plan_sha256':self.plan_sha,
               'reused_from':entry,'new_inference':False})
        write(self.directory/'calls'/(prefix+'.result.json'),result)
        print({'stage':stage,'call':self.seq,'reused':True},flush=True)
        return result
