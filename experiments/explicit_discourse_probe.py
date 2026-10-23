"""Zero-inference syntax diagnostic for any local snapshot/source JSON.

This is not a G1/G4 run, utilization score or semantic correctness evaluation.
"""
import argparse
from collections import Counter
from pathlib import Path
import time

from commentscope.factory import explicit_discourse as ed
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.position_frames import source_packet
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.storage import write_json_exclusive as write
from experiments.minimal_factory_pipeline import private
from experiments.scoped_discovery_probe import code_hashes


def run(directory,*,snapshot=None,sources=None):
    private(directory)
    if directory.exists() or (snapshot is None)==(sources is None):raise ValueError('New directory and exactly one input required')
    path=Path(snapshot or sources)
    if snapshot:
        data=load_snapshot(path).snapshot
        rows=[source_packet(data,c.comment_id) for c in normalize_snapshot(data) if c.text_analysis and c.duplicate_of is None]
    else:
        rows=read_json(path)
        if not isinstance(rows,list):raise ValueError('Source list required')
    if len({s['id'] for s in rows})!=len(rows):raise ValueError('Unique source IDs required')
    write(directory/'plan.json',{'artifact_kind':ed.VERSION+'-diagnostic','input':str(path),'input_sha256':sha(path),
        'code_sha256':code_hashes(),'source_ids':[s['id'] for s in rows],
        'model_calls':0,'quality_gate_passed':False,'purpose':'Source syntax and immutable ownership only'})
    started=time.monotonic();counts=Counter();holds=Counter();results=[]
    for source in rows:
        record=ed.parse(source);ed.validate(record);results.append(record)
        counts.update(e['relation'] for e in record['edges'])
        for h in record['holds']:holds.update(h.get('codes',[h.get('code')]))
    write(directory/'graphs.json',results)
    report={'artifact_kind':ed.VERSION+'-diagnostic-result','source_count':len(rows),
        'node_count':sum(len(r['nodes']) for r in results),'edge_count':sum(len(r['edges']) for r in results),
        'edge_relations':dict(counts),'syntax_hold_reasons':dict(holds),'model_calls':0,
        'elapsed_seconds':time.monotonic()-started,'semantic_approval':False,'quality_gate_passed':False,
        'full_G1_passed':False,'utilization_not_measured':True}
    write(directory/'completed.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--snapshot',type=Path);group.add_argument('--sources',type=Path)
    args=parser.parse_args();print(run(args.directory,snapshot=args.snapshot,sources=args.sources))
