"""Discovery may nominate one source; only later full-source support admits it."""
import os
from commentscope.factory import source_first
from commentscope.factory.claim_clusters import embed
from commentscope.providers.source_first_candidates import linkage

VERSION = 'discovery-seeds-without-support-precondition-0.1'


def generate(system, data, schema, max_tokens):
    if (system != VERSION or schema != {} or max_tokens != 1
            or set(data) != {'units', 'sources', 'threshold'} or len(data['units']) > 250):
        raise ValueError('Invalid bounded discovery request')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    units = data['units']; texts = [source_first.embedding_text(u) for u in units]
    vectors = embed(texts) if texts else []
    result = source_first.candidates(units, vectors, data['sources'], threshold=data['threshold'],
                                     cluster=linkage, minimum_sources=1)
    return {**result, 'unit_ids': [u['claim_id'] for u in units], 'embedding_texts': texts,
            'vectors': vectors, 'discovery_min_sources': 1, 'admission_min_sources': 3,
            'runtime_reference_labels': False}
