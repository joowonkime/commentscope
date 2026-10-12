"""Immutable candidate assertions and independent source membership (opt-in).

Similarity proposes targets; it never establishes support. The caller supplies
one source-only judgment per target/source. Counts remain model-provisional.
No rewritten details, exclusive assignments, or automatic agent promotion.
"""
from collections import defaultdict
from copy import deepcopy
import math

from commentscope.factory.automatic_contract import digest

VERSION = 'fixed-core-membership-0.1'


def select_cores(units, vectors, groups, sources, per_group=3):
    if type(per_group) is not int or per_group < 1:
        raise ValueError('Positive core budget required')
    by_source = {s['source_id']: s for s in sources}
    by_unit = {u['id']: u for u in units}
    if len(by_source) != len(sources) or len(by_unit) != len(units) or len(units) != len(vectors):
        raise ValueError('Duplicate identities or vector alignment mismatch')
    normalized = {}
    dimensions = set()
    for unit, vector in zip(units, vectors):
        dimensions.add(len(vector))
        if not vector or any(not math.isfinite(x) for x in vector):
            raise ValueError('Invalid vector')
        norm = math.sqrt(sum(x*x for x in vector))
        if not norm:
            raise ValueError('Zero vector')
        normalized[unit['id']] = [x/norm for x in vector]
        source = by_source[unit['source_id']]
        if not isinstance(unit['statement'], str) or not unit['statement'].strip() or not unit['spans']:
            raise ValueError('Empty target or provenance')
        for span in unit['spans']:
            start, end = span['start'], span['end']
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source['text']) or source['text'][start:end] != span['text']:
                raise ValueError('Unbound source span')
    if len(dimensions) > 1:
        raise ValueError('Vector dimensions differ')
    def cosine(left, right):
        return sum(a*b for a,b in zip(normalized[left], normalized[right]))
    cores, skipped = [], []
    seen_groups = set()
    for group in groups:
        if group['id'] in seen_groups:
            raise ValueError('Duplicate candidate identity')
        seen_groups.add(group['id'])
        ids = sorted(group['unit_ids'])
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate candidate unit')
        source_ids = sorted({by_unit[i]['source_id'] for i in ids})
        if source_ids != group['source_ids']:
            raise ValueError('Candidate source identity mismatch')
        if len(source_ids) < 2:
            skipped.append({'candidate_id': group['id'], 'reason': 'single_source', 'unit_ids': ids, 'source_ids': source_ids})
            continue
        by_sid = defaultdict(list)
        for uid in ids:
            by_sid[by_unit[uid]['source_id']].append(uid)
        # Each OTHER canonical source gets one vote, irrespective of claim count.
        centrality = {uid: sum(max(cosine(uid, v) for v in other)
                              for sid, other in by_sid.items() if sid != by_unit[uid]['source_id']) / (len(source_ids)-1)
                      for uid in ids}
        selected = []
        available = ids[:]
        while available and len(selected) < per_group:
            if not selected:
                chosen = min(available, key=lambda uid: (-centrality[uid], uid))
            else:
                chosen = min(available, key=lambda uid: (max(cosine(uid, v) for v in selected), -centrality[uid], uid))
            selected.append(chosen)
            # Only exact target strings are deduplicated; no semantic rewriting.
            available = [uid for uid in available if by_unit[uid]['statement'] != by_unit[chosen]['statement']]
        for rank, uid in enumerate(selected, 1):
            unit = by_unit[uid]
            identity = {'candidate_id': group['id'], 'anchor_unit_id': uid, 'text': unit['statement']}
            cores.append({'id': 'FC-'+digest(identity)[:20], **identity,
                          'core_sha256': digest(identity), 'selection_rank': rank,
                          'selection_centrality': centrality[uid],
                          'anchor_source_id': unit['source_id'], 'anchor_spans': deepcopy(unit['spans']),
                          'source_ids': source_ids})
    return {'artifact_kind': VERSION, 'cores': cores, 'skipped': skipped,
            'quality_gate_passed': False, 'agents': []}


def memberships(selection, sources, judge, minimum_sources=3):
    """judge(core, source) -> verdict/errors/trace. Never sees other sources.

    The anchor is checked too; source claims may support more than one core.
    Full originals are copied as quotations, NOT asserted to be a common reason.
    """
    if type(minimum_sources) is not int or minimum_sources < 3:
        raise ValueError('Minimum three distinct canonical sources required')
    by_source = {s['source_id']: s for s in sources}
    if len(by_source) != len(sources):
        raise ValueError('Duplicate source identity')
    cards = []
    for core in selection['cores']:
        identity = {k: core[k] for k in ['candidate_id', 'anchor_unit_id', 'text']}
        if digest(identity) != core['core_sha256'] or core['id'] != 'FC-'+digest(identity)[:20]:
            raise ValueError('Core mutated')
        if core['source_ids'] != sorted(set(core['source_ids'])):
            raise ValueError('Noncanonical membership list')
        relations, evidence = [], []
        for sid in core['source_ids']:
            source = by_source[sid]
            # Copies prevent a provider from mutating the target or source registry.
            result = judge(deepcopy(core), deepcopy(source))
            errors = list(result.get('errors', []))
            verdict = result.get('verdict')
            if verdict not in {'supported', 'partial', 'unsupported', 'unclear'} and not errors:
                errors.append('invalid_verdict')
            state = 'error' if errors else 'model_supported' if verdict == 'supported' else 'not_supported' if verdict in {'partial', 'unsupported'} else 'uncertain'
            relations.append({'source_id': sid, 'source_sha256': digest(source['text']),
                              'core_sha256': core['core_sha256'], 'state': state,
                              'judgment': {**deepcopy(result), 'errors': errors}})
            if state == 'model_supported':
                evidence.append({'source_id': sid, 'original_text': source['text'],
                                 'quotation_scope': 'whole_own_comment_not_shared_detail'})
        count = len(evidence)
        cards.append({'core': deepcopy(core), 'relations': relations,
                      'model_support_count': count, 'support_count': None,
                      'status': 'model_candidate_ge3' if count >= minimum_sources else 'rare_model_candidate' if count else 'unresolved',
                      'evidence': evidence, 'generated_details': [],
                      'quality_gate_passed': False})
    return {'artifact_kind': VERSION, 'cards': cards, 'skipped': deepcopy(selection['skipped']),
            'quality_gate_passed': False, 'agents': [], 'human_approved': False}
