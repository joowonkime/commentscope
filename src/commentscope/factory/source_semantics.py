"""Immutable S1/S2 host records, never support, factual or quality approval.

Reuse the traced extraction and independent typed review binders. No model
calls, repairs, inferred observations or replacement of downstream checks.
"""
from copy import deepcopy

from commentscope.factory import compact_claims, source_interpretation
from commentscope.factory.automatic_contract import digest


VERSION = 'source-semantics-record-20261105-v1'
SCHEMA = 'factory-semantics-0.1'


def _snapshot_identity(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('Current snapshot SHA256 required')


def _extraction(record):
    try:
        compact_claims.validate(record)
    except (KeyError, TypeError) as exc:
        raise ValueError('Complete traced source extraction required') from exc
    if record['artifact_kind'] != compact_claims.TRACED_PROPOSALS:
        raise ValueError('Traced source extraction required')
    return record


def bind(extraction, reviews, *, snapshot_sha256):
    """Retain absent/failed reviews as holds; never fill them from S1 guesses."""
    _snapshot_identity(snapshot_sha256)
    _extraction(extraction)
    if not isinstance(reviews, list) or any(not isinstance(r, dict) for r in reviews):
        raise ValueError('A list of typed source reviews required')
    if any(r.get('artifact_kind') != source_interpretation.TYPED_REVIEW for r in reviews):
        raise ValueError('Typed source reviews required; no legacy observation fallback')
    try:
        admission = source_interpretation.nominate([extraction], reviews,
                                                 protocol=source_interpretation.TYPED_REVIEW)
    except (KeyError, TypeError) as exc:
        raise ValueError('Complete current source review bindings required') from exc
    ordered = sorted(reviews, key=digest)
    source = extraction['source']
    record = {'artifact_kind': VERSION, 'schema_version': SCHEMA, 'producer_contract': VERSION,
              'snapshot_sha256': snapshot_sha256, 'source_sha256': digest(source),
              'request_sha256': extraction['request_sha256'],
              'source_review_protocol': source_interpretation.TYPED_REVIEW,
              'review_request_sha256s': [r['request_sha256'] for r in ordered],
              'source': deepcopy(source), 'completion': extraction['status'],
              'extraction': deepcopy(extraction), 'reviews': deepcopy(ordered),
              'decisions': admission['decisions'],
              'semantic_approval': False, 'support_approved': False, 'factual_verification': False}
    return {**record, 'record_sha256': digest(record)}


def validate(record, *, snapshot_sha256, source):
    """Require the caller's actual scope, not only hashes stored in the record."""
    _snapshot_identity(snapshot_sha256)
    if (not isinstance(record, dict) or record.get('artifact_kind') != VERSION
            or record.get('snapshot_sha256') != snapshot_sha256 or record.get('source') != source):
        raise ValueError('Source record must bind the current snapshot and original')
    body = {key: value for key, value in record.items() if key != 'record_sha256'}
    if record.get('record_sha256') != digest(body):
        raise ValueError('Source record hash must cover the exact JSON payload')
    try:
        rebuilt = bind(record['extraction'], record['reviews'], snapshot_sha256=snapshot_sha256)
    except (KeyError, TypeError) as exc:
        raise ValueError('Complete source record required') from exc
    if rebuilt != record:
        raise ValueError('Source record, input, observations or approval flags changed')
    return record


def collect(extractions, reviews, *, snapshot_sha256):
    """Export completed S1 sources including unresolved/non-nominating records."""
    _snapshot_identity(snapshot_sha256)
    if not isinstance(extractions, list) or not isinstance(reviews, list):
        raise ValueError('Extraction and review lists required')
    registry = {}
    for extraction in extractions:
        _extraction(extraction)
        sid = extraction['source']['id']
        if sid in registry:
            raise ValueError('One traced extraction per source required')
        registry[sid] = extraction
    grouped = {sid: [] for sid in registry}
    for review in reviews:
        if (not isinstance(review, dict) or not isinstance(review.get('source'), dict)
                or not isinstance(review['source'].get('id'), str)
                or review['source']['id'] not in registry):
            raise ValueError('Foreign source review cannot enter source records')
        grouped[review['source']['id']].append(review)
    return [bind(extraction, grouped[sid], snapshot_sha256=snapshot_sha256)
            for sid, extraction in sorted(registry.items())]
