"""Audit all saved source graphs under a new host policy without inference.

Original model requests/results stay original. Missing candidate observations
remain pending. This replay does not produce fresh gate or runtime evidence.
"""
import argparse
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'src'):
    if str(path) not in sys.path:sys.path.insert(0,str(path))

from commentscope.factory import source_evidence_graph as g,source_evidence_requests as reqs,source_evidence_adapter as adapter,pipeline_stages
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.providers import remote_verification as remote,openrouter
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from tools.replay_source_evidence_lowering import completed

VERSION='source-role-policy-replay-20261113-v1'


def compare_graph(original):
    proposal=original['proposal'];g.validate_proposal(proposal)
    observed=g.bind_observation(proposal,{'output':original['observation']['output']})
    if observed!=original['observation']:raise ValueError('Original observation wire/provenance changed')
    return g.verify(proposal,observed)


def original_call(directory,plan,stage,request,output):
    role=remote.role(stage);deployment=plan['deployment' if role=='generation' else 'verification_deployment']
    actual=allocate(request,openrouter.generation_allocation(deployment,require_explicit=True))
    paths=list((directory/'calls').glob('*-'+role+'-'+stage+'-'+digest(request)[:20]+'.request.json'))
    if len(paths)!=1:raise ValueError('Unique saved original model call required')
    saved=read_json(paths[0]);result=read_json(paths[0].with_name(paths[0].name.replace('.request.json','.result.json')))
    if (saved['request']!=actual or saved['request_sha256']!=digest(actual)
            or saved['plan_sha256']!=sha(directory/'plan.json') or result.get('output')!=output):
        raise ValueError('Saved original request/output changed')
    remote.parsed_receipt(result,request,deployment)


def rebind_batch(batch,old_graphs,new_graphs):
    sid=batch['verified']['proposal']['source']['id']
    if batch['verified']!=old_graphs[sid]:raise ValueError('Candidate observation has another original graph')
    verified=new_graphs[sid];request=reqs.candidate_request(verified,batch['candidates'])
    if digest(request)!=batch['request_sha256']:raise ValueError('Model request changed; cannot reuse observation')
    if any(c['verified_sha256']!=digest(old_graphs[sid]) or c['request_sha256']!=batch['request_sha256'] for c in batch['certificates']):
        raise ValueError('Original candidate certificate binding changed')
    return reqs.bind_candidates(verified,batch['candidates'],batch['support_batches'],{'output':batch['response']})


def replay(original,output):
    original=Path(original).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Replay requires a new output directory')
    done=completed(original);plan=read_json(original/'plan.json')
    for filename,expected in plan['inputs'].items():
        if sha(filename)!=expected:raise ValueError('Original input changed')
    names=sorted(n for n in done['artifacts'] if n.startswith('artifacts/source-evidence-graphs/'))
    old_graphs={};graphs={}
    for name in names:
        old=read_json(original/name);sid=old['proposal']['source']['id']
        if sid in graphs:raise ValueError('Duplicate original source graph')
        original_call(original,plan,'source-evidence-proposal',g.proposal_request(old['proposal']['envelope']),old['proposal']['wire_output'])
        original_call(original,plan,'source-evidence-observation',g.observation_request(old['proposal']),old['observation']['output'])
        old_graphs[sid]=old;graphs[sid]=compare_graph(old)
    records=read_json(original/'artifacts/arguments.json');lowered=[]
    for record in records:
        batches=[]
        for batch in record['evidence_batches']:
            rebound=rebind_batch(batch,old_graphs,graphs)
            original_call(original,plan,'source-evidence-candidates',reqs.candidate_request(rebound['verified'],batch['candidates']),batch['response'])
            batches.append(rebound)
        lowered.append(adapter.lower(batches))
    if [r['source'] for r in lowered]!=[r['source'] for r in records]:raise ValueError('Original record inventory changed')
    cores=read_json(original/'artifacts/cores.json');old_audits=read_json(original/'artifacts/argument-audits.json')
    if len(old_audits)!=1:raise ValueError('Complete original core audit required')
    audits=[adapter.audit(lowered,cores,old_audits[0]['core_checks'])]
    baseline=Path(plan['baseline_artifacts']);snapshot=load_snapshot(Path(plan['snapshot'])).snapshot
    def no_inference(request):raise ValueError('New factual inference is outside offline replay')
    inputs,checks=pipeline_stages.compile_agents(snapshot,read_json(baseline/'candidates.json'),read_json(baseline/'memberships.json'),
        lowered,cores,audits,no_inference,model=plan['classifier'],documents=plan['documents'],selections=plan['selections'],source_policy='candidate_verified_subset')
    recorded={r['source']['id'] for r in records}
    report=dict(version=VERSION,verification_policy=g.VERIFICATION_POLICY,original_run=str(original),
        original_completed_sha256=sha(original/'completed.json'),code_sha256=source_code_hashes(),tool_sha256=sha(__file__),
        original_graphs_complete=sum(r['status']=='complete' for r in old_graphs.values()),
        replay_graphs_complete=sum(r['status']=='complete' for r in graphs.values()),graphs=len(graphs),
        pending_candidate_source_ids=sorted(sid for sid,v in graphs.items() if v['status']=='complete' and sid not in recorded),
        graph_decisions=[dict(source_id=sid,original_status=old_graphs[sid]['status'],status=v['status'],issues=v['issues']) for sid,v in graphs.items()],
        records=len(records),complete_records=sum(r['status']=='complete' for r in lowered),
        profiles=[dict(candidate_id=p['candidate_id'],support_count=p['model_core_support_count'],entries=len(p['prompt_entries'])) for p in inputs['compiled']['profiles']],
        model_calls=0,cost_usd='0',fresh_gate=False,runtime_verified=False,semantic_adoption=False)
    artifacts={'graphs':graphs,'arguments':lowered,'cores':cores,'argument-audits':audits,'agent-inputs':inputs,'fact-checks':checks,'report':report}
    output.mkdir(parents=True)
    for name,value in artifacts.items():write(output/(name+'.json'),value)
    write(output/'manifest.json',dict(version=VERSION,artifacts={name+'.json':sha(output/(name+'.json')) for name in artifacts}))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('original',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();r=replay(a.original,a.output)
    print(json.dumps({k:v for k,v in r.items() if k not in ('code_sha256','graph_decisions')},ensure_ascii=False))
