"""Snapshot-bound canonical source vectors, independent of claim extraction."""
import math

from commentscope.factory.automatic_contract import digest

VERSION = 'canonical-source-vector-index-0.1'


def normalize(vectors):
    result = []; dimension = None
    for vector in vectors:
        if (not vector or (dimension is not None and len(vector) != dimension)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)):
            raise ValueError('Invalid source index vector')
        norm = math.sqrt(sum(v*v for v in vector))
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError('Invalid source index norm')
        result.append([v/norm for v in vector]); dimension = len(vector)
    return result


def build(rows, vectors, snapshot_sha256, model, revision, *, sources):
    ids = [row.comment_id for row in rows]
    if (not ids or ids != sorted(set(ids)) or len(ids) != len(vectors)
            or any(row.duplicate_of is not None or not row.text_analysis for row in rows)):
        raise ValueError('Complete ordered canonical nonempty rows required')
    return {'artifact_kind': VERSION, 'snapshot_sha256': snapshot_sha256,
            'model': model, 'model_revision': revision, 'source_ids': ids,
            'source_sha256': [digest(sources[row.comment_id]) for row in rows],
            'embedding_texts': [row.text_analysis for row in rows],
            'vectors': normalize(vectors), 'membership_approval': False}


def validate(index, rows, snapshot_sha256, model, revision, *, sources):
    expected = build(rows, index['vectors'], snapshot_sha256, model, revision, sources=sources)
    # Stored vectors may be normalized again with harmless float roundoff.
    if {k: v for k, v in index.items() if k != 'vectors'} != {k: v for k, v in expected.items() if k != 'vectors'}:
        raise ValueError('Source index snapshot/population/text/model binding changed')
    return expected['vectors']
