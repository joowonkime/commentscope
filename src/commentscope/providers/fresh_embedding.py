"""Bounded-worker adapter for a fresh, offline whole-snapshot embedding run."""
import os
from pathlib import Path
from commentscope.factory.claim_clusters import sha, read_json
from commentscope.ingestion import load_snapshot

VERSION = 'fresh-snapshot-embedding-0.1'


def generate(system, data, schema, max_tokens):
    if (system != VERSION or schema != {} or max_tokens != 1
            or set(data) != {'snapshot','snapshot_sha256','output'}):
        raise ValueError('Unexpected embedding request')
    snapshot, output = Path(data['snapshot']), Path(data['output'])
    if sha(snapshot) != data['snapshot_sha256']:
        raise ValueError('Snapshot changed')
    if len(load_snapshot(snapshot).snapshot.comments) > 1000:
        raise ValueError('MVP snapshot cap is 1000 comments')
    # Process-local controls: never fetch missing model files from the network.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    from commentscope.cluster_baseline import run
    run(snapshot, output, threshold=.45)
    if sha(snapshot) != data['snapshot_sha256']:
        raise ValueError('Snapshot changed during analysis')
    report = read_json(output)
    if report['snapshot_sha256'] != data['snapshot_sha256']:
        raise ValueError('Embedding snapshot binding changed')
    return {'output':str(output), 'sha256':sha(output), 'summary':report['summary'],
            'fresh_embedding':True, 'quality_gate_passed':False}
