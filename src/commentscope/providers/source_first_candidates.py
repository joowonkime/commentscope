"""Offline bounded-worker embedding and clustering of bound ClaimUnits."""
import math
import os

from commentscope.factory import source_first
from commentscope.factory.claim_clusters import embed

VERSION = 'source-first-candidate-provider-0.1'


def linkage(vectors, threshold):
    from sklearn.cluster import AgglomerativeClustering
    normalized = [[v/math.sqrt(sum(x*x for x in row)) for v in row] for row in vectors]
    if len(vectors) == 1:
        return [[0]], normalized
    labels = AgglomerativeClustering(n_clusters=None, metric='cosine', linkage='average',
                                    distance_threshold=threshold).fit_predict(normalized)
    groups = {}
    for i, label in enumerate(labels): groups.setdefault(int(label), []).append(i)
    return sorted(groups.values(), key=lambda g: (-len(g), g)), normalized


def generate(system, data, schema, max_tokens):
    if (system != VERSION or schema != {} or max_tokens != 1
            or set(data) != {'units', 'sources', 'threshold'}
            or not 0 < data['threshold'] < 1 or len(data['units']) > 6000):
        raise ValueError('Invalid bounded candidate request')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    units = data['units']
    texts = [source_first.embedding_text(unit) for unit in units]
    vectors = embed(texts) if texts else []
    result = source_first.candidates(units, vectors, data['sources'], threshold=data['threshold'], cluster=linkage)
    return {**result, 'unit_ids': [u['claim_id'] for u in units], 'embedding_texts': texts, 'vectors': vectors,
            'threshold': data['threshold'], 'runtime_reference_labels': False}
