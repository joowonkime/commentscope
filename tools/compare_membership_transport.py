"""Free archived request sizing. No API calls, semantic reuse or price forecast."""
import argparse
from collections import defaultdict
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
for item in (ROOT,ROOT/'src'):
    if str(item) not in sys.path:sys.path.insert(0,str(item))

from commentscope.factory import source_membership_batch as batch, cost_planning as cost
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha
from commentscope.providers import openrouter
from commentscope.providers.generation_limits import allocate
from commentscope.storage import write_json_exclusive as write
from tools import plan_factory_cost as archives


def compare_requests(rows,deployment,*,phases=None):
    groups=defaultdict(list);scalar_bytes=scalar_output=0;phase_counts=defaultdict(lambda:[0,0])
    runtime=openrouter.generation_allocation(deployment)
    client=openrouter.Client(deployment)
    def size(req,*,allocated):
        actual=req if allocated else allocate(req,runtime)
        import json
        payload=client.payload(actual['system'],actual['data'],actual['schema'],actual['max_tokens'])
        return len(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()),actual['max_tokens']
    for stage,req,result in rows:
        if cost.canonical(stage,req)!='membership-raw':continue
        family=(phases or {}).get(digest(req)) if phases is not None else re.sub(r'-[a-f0-9]{20}$','',stage)
        # Remote role aliases erase phase names. Unresolved provenance must
        # stay singleton, never be merged into an apparently cheaper phase.
        singleton=digest(req) if family is None else ''
        if family is None:family='unresolved-alias-phase'
        common={k:v for k,v in req['data'].items() if k not in ('CANDIDATE','CANDIDATE_WORLD_OBSERVATION')}
        groups[(family,digest([common,req['system'],req['schema'],singleton]))].append(req)
        a,b=size(req,allocated=True);scalar_bytes+=a;scalar_output+=b;phase_counts[family][0]+=1
    batch_bytes=batch_output=packets=covered=0;distribution=defaultdict(int)
    for (family,_),requests in groups.items():
        for offset in range(0,len(requests),batch.MAX_TARGETS):
            subset=requests[offset:offset+batch.MAX_TARGETS]
            req=batch.from_logical_requests(subset)
            a,b=size(req,allocated=False);batch_bytes+=a;batch_output+=b
            packets+=1;covered+=len(subset);distribution[str(len(subset))]+=1;phase_counts[family][1]+=1
    original=sum(v[0] for v in phase_counts.values())
    return {'artifact_kind':batch.VERSION+'-offline-comparison','scalar_requests':original,
        'batched_requests':packets,'covered_pairs':covered,'all_archived_pairs_preserved':covered==original,
        'request_reduction_fraction':1-packets/original if original else 0,
        'scalar_wire_utf8_bytes':scalar_bytes,'batch_wire_utf8_bytes':batch_bytes,
        'wire_reduction_fraction':1-batch_bytes/scalar_bytes if scalar_bytes else 0,
        'scalar_output_reservation_tokens':scalar_output,'batch_output_reservation_tokens':batch_output,
        'packet_widths':dict(sorted(distribution.items())),
        'phases':{k:{'scalar_requests':v[0],'batched_requests':v[1]} for k,v in sorted(phase_counts.items())},
        'new_model_calls':0,'semantic_input_reuse':False,'semantic_equivalence_verified':False,
        'actual_batch_cost_usd':None,'quality_gate_passed':False,
        'limitations':['Archived requested pairs only; incomplete runs remain incomplete.',
            'No cross-phase deduplication inferred from wire text without full candidate provenance.',
            'Wire bytes and output reservations are not billed tokens or dollar savings.',
            'Historical prompt caching may reduce the actual financial benefit.']}


def compare(directory):
    directory=Path(directory)
    audited=archives.audit(directory) # Verifies original plan, source archive and receipts; no network.
    from commentscope.factory.claim_clusters import read_json
    plan=read_json(directory/'plan.json')
    from commentscope.factory import raw_membership as raw
    phases={}
    for path in (directory/'artifacts/bound').glob('*-raw-*.json'):
        record=read_json(path)
        if record.get('artifact_kind')!=raw.WORLD_CONTEXT:continue
        raw.validate(record)
        req=raw.request(record['source'],record['candidate'],version=raw.WORLD_CONTEXT,
            source_context=record['source_context'],source_world=record['source_world'],candidate_world=record['candidate_world'])
        prefix=path.name.split('-'+digest(req)[:20]+'-',1)
        if len(prefix)!=2:raise ValueError('Bound phase filename differs from exact logical request')
        allocated=allocate(req,openrouter.generation_allocation(plan['verification_deployment']))
        key=digest(allocated)
        if key in phases and phases[key]!=prefix[0]:phases[key]=None
        else:phases[key]=prefix[0]
    rows=[row for row in archives.call_rows(directory,plan) if row[2] is not None]
    result=compare_requests(rows,plan['verification_deployment'],phases=phases)
    result.update(origin=str(directory.resolve()),plan_sha256=sha(directory/'plan.json'),
                  archive_completed_responses=audited['completed_responses'],
                  archive_pending_requests=audited['pending_requests'],pending_requests_excluded=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if 'runs' not in args.output.parts:raise ValueError('Private comparison output belongs under runs/')
    result=compare(args.directory);write(args.output,result)
    import json
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
