"""Continue a frozen fidelity run using settled truncated responses as holds.

No retry, response repair, output increase, new owner or deadline extension.
Original runner, requests, checkpoints, receipts and charges remain unchanged.
"""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3

from tools import source_fidelity_validation as live
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.pipeline_work import ModelResponseUnavailable
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT
from commentscope.providers.generation_limits import allocate
from commentscope.providers.openrouter_budget import units
from commentscope.storage import write_json_exclusive as write

VERSION='source-fidelity-settled-length-continuation-20261112-v1'
TOOL=Path(__file__).resolve()
GRAPH=('source-evidence-proposal','source-evidence-observation','source-evidence-candidates')


def saved_length(session,stage,request):
    """Return the exact failed result only after durable provenance/charge checks."""
    family=live.cost.canonical(stage,request)
    if family not in GRAPH:raise ValueError('Only original graph response holds are authorized')
    key=live.remote.role(family);field='deployment' if key=='generation' else 'verification_deployment'
    deployment=session.plan[field]
    actual=allocate(request,live.executor.openrouter.generation_allocation(deployment,require_explicit=True))
    wire_stage=key+'-'+family+'-'+digest(request)[:20]
    identity=dict(artifact_kind=CHECKPOINT,plan_sha256=sha(session.directory/'plan.json'),stage=wire_stage,
        request_sha256=digest(actual),provider=live.executor.openrouter.Runner.provider_identity)
    intent=session.directory/'checkpoints'/(digest(identity)+'.intent.json')
    done=intent.with_name(intent.name.replace('.intent.json','.result.json'));bound=read_json(done)
    if (read_json(intent)!=identity or set(bound)!={'identity','result','result_sha256'}
            or bound['identity']!=identity or digest(bound['result'])!=bound['result_sha256']):raise ValueError('Original failed checkpoint changed')
    result=bound['result'];transport=result.get('transport') or {};receipt=transport.get('provider_response') or {}
    live.remote.receipt(receipt,deployment)
    if (result.get('errors')!=['incomplete_generation'] or result.get('output') is not None
            or digest(receipt)!=transport.get('provider_response_sha256')
            or len(receipt.get('choices',[]))!=1 or receipt['choices'][0].get('finish_reason')!='length'
            or receipt['choices'][0]['message'].get('content')!=result.get('raw')
            or receipt.get('usage')!=result.get('usage') or not receipt.get('id')):
        raise ValueError('Original terminal length receipt required')
    requests=list((session.directory/'calls').glob('*-'+wire_stage+'.request.json'))
    if len(requests)!=1:raise ValueError('Unique original call required')
    saved=read_json(requests[0]);response=requests[0].with_name(requests[0].name.replace('.request.json','.result.json'))
    if (saved['request']!=actual or saved['request_sha256']!=digest(actual) or saved['plan_sha256']!=identity['plan_sha256']
            or read_json(response)!=result):raise ValueError('Saved request/result provenance changed')
    policy=session.plan['spend_policy'];money=live.executor.ledger(policy);account=money.summary()
    if account['reserved_calls'] or account['uncertain_calls']:raise live.BudgetExhausted('Unsettled charges still stop continuation')
    with closing(sqlite3.connect(Path(policy['ledger']).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute('SELECT state,charged FROM calls WHERE plan_sha=? AND request_sha=?',
            (session.plan['spend_scope_sha256'],digest(actual))).fetchall()
    if rows!=[('complete',units(receipt['usage']['cost']))]:raise ValueError('Unique complete charge must match original receipt')
    return result


def prepare(directory,manifest,*,user_request):
    directory=Path(directory).resolve();manifest=Path(manifest).resolve();plan=read_json(directory/'plan.json');live.guard(plan)
    live.executor.private(manifest)
    originals={h for p,h in plan['inputs'].items() if Path(p).name=='source_fidelity_validation.py'}
    if originals!={sha(Path(live.__file__))}:raise ValueError('Continuation must use the exact original runner')
    if not user_request.strip() or manifest.exists() or not manifest.is_relative_to(directory/'recoveries'):
        raise ValueError('New explicit private continuation manifest required')
    with live.experiment_lock(directory):
        if (directory/'completed.json').exists():raise ValueError('Completed original run is read only')
        session=type('SavedSession',(),dict(directory=directory,plan=plan))()
        proofs=[]
        for f in sorted((directory/'calls').glob('*.request.json')):
            response=f.with_name(f.name.replace('.request.json','.result.json'))
            if not response.exists():raise ValueError('Pending requests cannot be continued as settled failures')
            result=read_json(response)
            if not result.get('errors'):continue
            saved=read_json(f);actual=saved['request'];request=dict(actual)
            # Invert only the frozen output allocation, never alter the request.
            role='generation' if '-generation-' in f.name else 'verification'
            field='deployment' if role=='generation' else 'verification_deployment'
            runtime=live.executor.openrouter.generation_allocation(plan[field],require_explicit=True)
            request['max_tokens']-=runtime['reasoning_budget']
            stage=live.cost.canonical(f.name.split('-',2)[2].removesuffix('.request.json'),request)
            if saved_length(session,stage,request)!=result:raise ValueError('Failure proof changed')
            proofs.extend([f,response])
        if not proofs:raise ValueError('Saved settled length failure required')
        archive=manifest.parent/'launcher.py';archive.parent.mkdir(parents=True,exist_ok=True)
        if archive.exists():
            if sha(archive)!=sha(TOOL):raise ValueError('Archived continuation changed')
        else:archive.write_bytes(TOOL.read_bytes())
        body=dict(version=VERSION,run_directory=str(directory),user_request=user_request,
            created_at=datetime.now(timezone.utc).isoformat(),plan_sha256=sha(directory/'plan.json'),
            original_runner_sha256=sha(Path(live.__file__)),launcher_sha256=sha(TOOL),archive=str(archive),
            files={str(f):sha(f) for f in proofs},provider_retries=0,semantic_contract_unchanged=True)
        write(manifest,{**body,'integrity_sha256':digest(body)})
    validate(directory,manifest)
    return dict(saved_failures=len(proofs)//2,new_model_calls=0,provider_retries=0)


def validate(directory,manifest):
    directory=Path(directory).resolve();manifest=Path(manifest).resolve();m=read_json(manifest)
    body={k:v for k,v in m.items() if k!='integrity_sha256'}
    if (not manifest.is_relative_to(directory/'recoveries') or m['version']!=VERSION or m['run_directory']!=str(directory)
            or m['integrity_sha256']!=digest(body) or m['plan_sha256']!=sha(directory/'plan.json')
            or m['launcher_sha256']!=sha(TOOL) or sha(m['archive'])!=sha(TOOL)
            or m['original_runner_sha256']!=sha(Path(live.__file__)) or m['provider_retries']!=0
            or m['semantic_contract_unchanged'] is not True or not m['files']
            or any(not Path(p).resolve().is_relative_to(directory/'calls') or sha(p)!=h for p,h in m['files'].items())):
        raise ValueError('Frozen continuation changed')
    return m


def run(directory,manifest):
    directory=Path(directory).resolve();manifest=Path(manifest).resolve();validate(directory,manifest)
    pinned=sha(manifest);original=live.Session
    class ContinuationSession(original):
        def call(self,stage,request):
            if sha(manifest)!=pinned:raise ValueError('Continuation manifest changed during execution')
            validate(directory,manifest)
            try:return super().call(stage,request)
            except ModelResponseUnavailable:
                # A length response stays a failed response. The existing binder
                # rejects errors and records a source hold without a second call.
                return saved_length(self,stage,request)
    live.Session=ContinuationSession
    try:report=live.run(directory)
    finally:live.Session=original
    binding=dict(version=VERSION+'/completion',manifest_sha256=pinned,completed_sha256=sha(directory/'completed.json'),provider_retries=0)
    path=manifest.parent/'completion.json'
    if path.exists():
        if read_json(path)!=binding:raise ValueError('Continuation completion changed')
    else:write(path,binding)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','run'));p.add_argument('directory',type=Path)
    p.add_argument('manifest',type=Path);p.add_argument('--user-request',default='');p.add_argument('--key-file',type=Path);a=p.parse_args()
    if a.key_file:os.environ['OPENROUTER_API_KEY']=a.key_file.read_text().strip()
    result=prepare(a.directory,a.manifest,user_request=a.user_request) if a.action=='prepare' else run(a.directory,a.manifest)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
