"""Replay every saved graph/candidate batch without inference or artifact edits.

This is a development replay, never a fresh Factory gate. Changed/new facts
require a separately authorized execution and are not approved by this tool.
"""
import argparse
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'src'):
    if str(path) not in sys.path:sys.path.insert(0,str(path))

from commentscope.factory import source_evidence_adapter as adapter, pipeline_stages
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.file_integrity import source_code_hashes
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive as write

VERSION='source-evidence-lowering-replay-20261112-v1'


def completed(directory):
    directory=Path(directory).resolve();done=read_json(directory/'completed.json')
    if done['plan_sha256']!=sha(directory/'plan.json'):
        raise ValueError('Original completed plan changed')
    for name,expected in done['artifacts'].items():
        path=directory/name
        if not path.resolve().is_relative_to(directory/'artifacts') or sha(path)!=expected:
            raise ValueError('Original completed artifacts changed')
    for name in ('arguments','cores','argument-audits','validation-report'):
        if 'artifacts/'+name+'.json' not in done['artifacts']:
            raise ValueError('Complete source artifacts required')
    if read_json(directory/'artifacts/validation-report.json')!=done['report']:
        raise ValueError('Original completed report changed')
    return done


def rebuild(records,cores,audits):
    if len({r['source']['id'] for r in records})!=len(records) or len(audits)!=1:
        raise ValueError('Unique complete source inventory and original audit required')
    # Never retain only sources which will pass the new lowering.
    lowered=[adapter.lower(r['evidence_batches']) for r in records]
    if [r['source'] for r in lowered]!=[r['source'] for r in records]:
        raise ValueError('Original source inventory changed')
    return lowered,[adapter.audit(lowered,cores,audits[0]['core_checks'])]


def replay(original,output):
    original=Path(original).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Replay requires a new output directory')
    done=completed(original);plan=read_json(original/'plan.json')
    for filename,expected in plan['inputs'].items():
        if sha(filename)!=expected:raise ValueError('Original frozen input changed')
    a=original/'artifacts';records=read_json(a/'arguments.json');cores=read_json(a/'cores.json')
    lowered,audits=rebuild(records,cores,read_json(a/'argument-audits.json'))
    baseline=Path(plan['baseline_artifacts']);snapshot=load_snapshot(Path(plan['snapshot'])).snapshot
    def no_inference(request):raise ValueError('New facts require separate authorized execution; no inference in replay')
    inputs,checks=pipeline_stages.compile_agents(snapshot,read_json(baseline/'candidates.json'),
        read_json(baseline/'memberships.json'),lowered,cores,audits,no_inference,
        model=plan['classifier'],documents=plan['documents'],selections=plan['selections'],source_policy='candidate_verified_subset')
    result=dict(version=VERSION,original_run=str(original),original_completed_sha256=sha(original/'completed.json'),
        original_plan_sha256=sha(original/'plan.json'),code_sha256=source_code_hashes(),tool_sha256=sha(__file__),
        source_count=len(records),original_complete=sum(r['status']=='complete' for r in records),
        replay_complete=sum(r['status']=='complete' for r in lowered),
        profiles=[dict(candidate_id=p['candidate_id'],support_count=p['model_core_support_count'],entries=len(p['prompt_entries'])) for p in inputs['compiled']['profiles']],
        source_statuses=[dict(source_id=r['source']['id'],original_status=o['status'],replay_status=r['status'],hold_reasons=r['hold_reasons']) for o,r in zip(records,lowered)],
        model_calls=0,cost_usd='0',fresh_gate=False,semantic_adoption=False,runtime_verified=False)
    artifacts={'arguments':lowered,'cores':cores,'argument-audits':audits,'agent-inputs':inputs,'fact-checks':checks,'report':result}
    output.mkdir(parents=True)
    for name,value in artifacts.items():write(output/(name+'.json'),value)
    write(output/'manifest.json',dict(version=VERSION,report_sha256=digest(result),
        artifacts={name+'.json':sha(output/(name+'.json')) for name in artifacts}))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('original',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();result=replay(args.original,args.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('code_sha256','source_statuses')},ensure_ascii=False))
