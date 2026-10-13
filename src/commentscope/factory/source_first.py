"""Source-first candidate assembly using a frozen existing extraction contract.

No generated summary is fed back into extraction. Medoids nominate immutable
targets, not consensus. All nominated sources still need independent membership.
Strict frame buckets are a measurable retrieval heuristic, not semantic gold.
"""
from collections import defaultdict
from copy import deepcopy
import math

from commentscope import claim_prompt
from commentscope.contracts.claim_generation import constrained_schema
from commentscope.contracts.claims import bind_source
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import average_linkage

VERSION = 'source-first-medoid-candidates-0.1'


def schedule(raw, group_limit=20):
    if type(group_limit) is not int or group_limit < 1:
        raise ValueError('Positive group limit required')
    groups = sorted((g for g in raw['clusters'] if len(set(g['members'])) >= 3),
                    key=lambda g: (-len(set(g['members'])), g['id']))[:group_limit]
    queues = [sorted(set(g['members']), key=digest) for g in groups]
    result, seen = [], set()
    while any(queues):
        for queue in queues:
            if queue:
                sid = queue.pop(0)
                if sid not in raw['sources']:
                    raise ValueError('Candidate contains unknown source')
                if sid not in seen:
                    seen.add(sid); result.append(sid)
    return result


def invocation(text):
    # Same SYSTEM and generation schema; no newly authored semantic instructions.
    return {'system': claim_prompt.SYSTEM, 'data': {'TARGET': text, 'PARENT': None},
            'schema': constrained_schema(), 'max_tokens': 1200}


def bind(sid, text, result):
    if result['errors']:
        return {'source_id': sid, 'source_sha256': digest(text), 'status': 'call_or_contract_error',
                'errors': deepcopy(result['errors']), 'units': []}
    try:
        value = bind_source(result['output'], sid, text)
    except (ValueError, KeyError, TypeError) as exc:
        return {'source_id': sid, 'source_sha256': digest(text), 'status': 'extraction_contract_error',
                'errors': [str(exc)], 'units': []}
    return {'source_id': sid, 'source_sha256': digest(text), 'status': value['eligibility'],
            'errors': [], 'units': value['claims']}


def embedding_text(unit):
    # Do not make different incidental reasons the primary grouping feature.
    return '\n'.join(str(unit[k]) for k in ('issue', 'claim', 'condition') if unit[k])


def bucket(unit):
    if unit['scope'] == 'unclear' or unit['modality'] == 'unclear' or unit['stance'] in {'mixed', 'unclear'}:
        return None
    target = ' '.join((unit['stance_target'] or '').casefold().split())
    return unit['scope'], unit['modality'], unit['stance'], target


def candidates(units, vectors, sources, *, threshold=.45, cluster=average_linkage, minimum_sources=3):
    if type(minimum_sources) is not int or minimum_sources not in (1, 3):
        raise ValueError('Discovery minimum must be explicit 1 or legacy 3; admission stays 3')
    if not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ValueError('Finite distance threshold in (0,1) required')
    if len(units) != len(vectors) or len({u['claim_id'] for u in units}) != len(units):
        raise ValueError('Unique unit/vector binding required')
    dimension = None
    for vector in vectors:
        if not vector or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ValueError('Invalid unit vector')
        if dimension is not None and dimension != len(vector):
            raise ValueError('Mixed vector dimensions')
        dimension = len(vector)
        if not math.isfinite(sum(v*v for v in vector)) or sum(v*v for v in vector) <= 0:
            raise ValueError('Invalid unit vector norm')
    groups, deferred = defaultdict(list), []
    for index, unit in enumerate(units):
        sid = unit['source_comment_id']
        if sid not in sources or unit['quote'] not in sources[sid]:
            raise ValueError('Unit lacks original source quote')
        key = bucket(unit)
        if key is None:
            deferred.append({'claim_id': unit['claim_id'], 'reason': 'ambiguous_frame'})
        else:
            groups[key].append(index)
    proposals = []
    for key in sorted(groups):
        indexes = sorted(groups[key], key=lambda i: units[i]['claim_id'])
        grouped, normalized = cluster([vectors[i] for i in indexes], threshold)
        for members in grouped:
            original = [indexes[j] for j in members]
            by_source = defaultdict(list)
            for j in members:
                by_source[units[indexes[j]]['source_comment_id']].append(j)
            if len(by_source) < minimum_sources:
                deferred.append({'claim_ids': [units[i]['claim_id'] for i in original], 'reason': 'fewer_than_three_sources'})
                continue
            # One source gets one weight even if it emits many paraphrases.
            def score(j):
                distance = lambda k: 1-max(-1, min(1, sum(a*b for a, b in zip(normalized[j], normalized[k]))))
                return sum(min(distance(k) for k in js) for js in by_source.values()), units[indexes[j]]['claim_id']
            selected = units[indexes[min(members, key=score)]]
            claim = {'id': 'C', 'text': selected['claim'], 'kind': 'fact',
                     'scope': {'entity': selected['scope'], 'time': '', 'conditions': selected['condition'] or ''}, 'requires': []}
            proposals.append({'claims': {'C': claim}, 'sources': {sid: sources[sid] for sid in sorted(by_source)},
                              'anchor_unit_id': selected['claim_id'],
                              'candidate_unit_ids': [units[i]['claim_id'] for i in original],
                              'semantic_approval': False, 'typing_required': True})
    proposals.sort(key=lambda p: (-len(p['sources']), p['anchor_unit_id']))
    for i, proposal in enumerate(proposals, 1):
        proposal['id'] = f'SC{i:03}'
    return {'artifact_kind': VERSION, 'proposals': proposals, 'deferred': deferred, 'quality_gate_passed': False}
