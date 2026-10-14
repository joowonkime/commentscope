"""Sparse retrieval across extraction frames; retrieval never approves support.

Every existing unit is a possible immutable target. Nearby canonical sources
nominate it, then NLI ranks targets for a bounded full-source membership pass.
No topic aliases, reference labels, generated consensus or frame merging.
"""
from collections import defaultdict
import math

from commentscope.factory.automatic_contract import digest
from commentscope.factory.source_first import bucket, embedding_text
from commentscope.factory.target_ranking import target, text
from commentscope.providers.local_nli import decide, THRESHOLD

VERSION = 'sparse-semantic-neighborhood-0.1'
LIMITS = {'units': 250, 'neighbors': 4, 'similarity_min': .55,
          'candidates': 6, 'source_overlap_max': .6}


def schedule(units, cache, sources):
    if len(units) > LIMITS['units'] or len({u['claim_id'] for u in units}) != len(units):
        raise ValueError('Unique bounded unit population required')
    if (cache['unit_ids'] != [u['claim_id'] for u in units]
            or cache['embedding_texts'] != [embedding_text(u) for u in units]
            or len(cache['vectors']) != len(units)):
        raise ValueError('Embedding/unit binding changed')
    normalized = []; dimension = None
    for u, vector in zip(units, cache['vectors'], strict=True):
        sid = u['source_comment_id']
        if sid not in sources or not u['quote'] or u['quote'] not in sources[sid]:
            raise ValueError('Unit lacks original source')
        if (not vector or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)
                or (dimension is not None and len(vector) != dimension)):
            raise ValueError('Invalid embedding')
        norm = math.sqrt(sum(v*v for v in vector))
        if not math.isfinite(norm) or norm <= 0: raise ValueError('Invalid embedding norm')
        normalized.append([v/norm for v in vector]); dimension = len(vector)
    pairs = []; neighborhoods = []; deferred = []
    for i in sorted(range(len(units)), key=lambda j: units[j]['claim_id']):
        anchor = units[i]; uid = anchor['claim_id']
        if bucket(anchor) is None:
            deferred.append({'unit_id': uid, 'reason': 'ambiguous_anchor_frame'}); continue
        nearby = []
        for j, other in enumerate(units):
            if other['source_comment_id'] == anchor['source_comment_id']: continue
            similarity = sum(a*b for a, b in zip(normalized[i], normalized[j], strict=True))
            if similarity >= LIMITS['similarity_min']:
                nearby.append((similarity, other))
        nearby.sort(key=lambda item: (-item[0], item[1]['claim_id']))
        seen = set(); chosen = []
        for similarity, other in nearby:
            sid = other['source_comment_id']
            if sid in seen: continue
            seen.add(sid); chosen.append((similarity, other))
            if len(chosen) == LIMITS['neighbors']: break
        if len(chosen) < 2:
            deferred.append({'unit_id': uid, 'reason': 'fewer_than_three_retrievable_sources'}); continue
        ids = []
        for similarity, other in chosen:
            pid = f'N{len(pairs)+1:04}'; ids.append(pid)
            pairs.append({'id': pid, 'target_unit_id': uid, 'premise_unit_id': other['claim_id'],
                          'premise_source_id': other['source_comment_id'],
                          'premise': text(other), 'hypothesis': text(anchor),
                          'similarity': similarity, 'crosses_frame': bucket(other) != bucket(anchor)})
        neighborhoods.append({'anchor_unit_id': uid, 'pair_ids': ids})
    return {'pairs': pairs, 'neighborhoods': neighborhoods, 'deferred': deferred}


def assemble(units, cache, sources, scheduled, result):
    if scheduled != schedule(units, cache, sources): raise ValueError('Retrieval population changed')
    if len(result['rows']) != len(scheduled['pairs']): raise ValueError('Incomplete ranking')
    index = {u['claim_id']: u for u in units}; by_target = defaultdict(list); errors = []
    for pair, row in zip(scheduled['pairs'], result['rows'], strict=True):
        if row['id'] != pair['id'] or row['pair_sha256'] != digest(pair) or not isinstance(row['errors'], list):
            raise ValueError('Ranking binding changed')
        if row['errors']:
            errors.append(pair['id']); score = 0.
        else:
            decide(row['scores']); score = row['scores']['entailment']
        by_target[pair['target_unit_id']].append((pair, score))
    ranked = []
    for neighborhood in scheduled['neighborhoods']:
        uid = neighborhood['anchor_unit_id']; evidence = by_target[uid]
        ranked.append({'unit_id': uid, 'estimated_other_sources': sum(s >= THRESHOLD for _, s in evidence),
                       'score_sum': sum(s for _, s in evidence)})
    ranked.sort(key=lambda r: (-r['estimated_other_sources'], -r['score_sum'], r['unit_id']))
    proposals = []; deferred = list(scheduled['deferred']); selected_sources = []
    for row in ranked:
        uid = row['unit_id']; anchor = index[uid]
        if row['estimated_other_sources'] < 2:
            deferred.append({'unit_id': uid, 'reason': 'ranking_below_nomination_threshold'}); continue
        neighbors = [p for p, _ in by_target[uid]]
        sids = {anchor['source_comment_id'], *(p['premise_source_id'] for p in neighbors)}
        # This only allocates a limited search budget. It is NOT a semantic
        # equivalence/merge decision; overlapping omitted targets remain visible.
        if any(len(sids & old)/len(sids | old) > LIMITS['source_overlap_max'] for old in selected_sources):
            deferred.append({'unit_id': uid, 'reason': 'retrieval_diversity_budget'}); continue
        if len(proposals) >= LIMITS['candidates']:
            deferred.append({'unit_id': uid, 'reason': 'candidate_budget'}); continue
        selected_sources.append(sids)
        proposals.append({'id': f'SN{len(proposals)+1:03}', 'claims': {'C': target(anchor)},
                          'sources': {sid: sources[sid] for sid in sorted(sids)},
                          'anchor_unit_id': uid,
                          'candidate_unit_ids': [uid]+[p['premise_unit_id'] for p in neighbors],
                          'typing_required': True, 'semantic_approval': False})
    return {'artifact_kind': VERSION, 'proposals': proposals, 'rankings': ranked,
            'deferred': deferred, 'pair_errors': errors, 'membership_approval': False,
            'quality_gate_passed': False, 'runtime_reference_labels': False}
