"""Pinned offline embeddings to a private artifact, not an oversized IPC reply."""
import os
from pathlib import Path

from commentscope.factory.claim_clusters import embed, sha
from commentscope.factory.automatic_contract import digest
from commentscope.cluster_baseline import MODEL, REVISION
from commentscope.storage import write_json_exclusive as write

VERSION = 'framed-corpus-embedding-artifact-0.1'


def generate(system, data, schema, max_tokens):
    if system != VERSION or schema != {} or max_tokens != 1 or set(data) != {'texts', 'output'}:
        raise ValueError('Unexpected embedding artifact request')
    texts = data['texts']
    if (not isinstance(texts, dict) or not 1 <= len(texts) <= 10000
            or any(not isinstance(sid, str) or not sid or not isinstance(t, str) or not t.strip() for sid, t in texts.items())):
        raise ValueError('Nonempty identified embedding inputs required')
    output = Path(data['output'])
    if output.exists(): raise ValueError('Never overwrite embedding output')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    ids = sorted(texts); vectors = embed([texts[sid] for sid in ids])
    if len(vectors) != len(ids): raise ValueError('Embedding output incomplete')
    artifact = {'artifact_kind': VERSION, 'texts_sha256': digest(texts), 'model': MODEL, 'revision': REVISION,
                'local_files_only': True, 'vectors': dict(zip(ids, vectors, strict=True)), 'quality_gate_passed': False}
    write(output, artifact)
    return {'artifact_kind': VERSION, 'output': str(output), 'sha256': sha(output),
            'texts_sha256': digest(texts), 'count': len(ids), 'model': MODEL, 'revision': REVISION,
            'local_files_only': True, 'quality_gate_passed': False}
