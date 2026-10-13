"""Whole-corpus recall, cheap NLI reranking, then full-source nominations.

No reference labels, supporter counts, or semantic approvals are produced here.
NLI reads bounded verbatim windows only for ranking. Membership must subsequently
read the complete original source; a window can omit a qualifying context.
"""
from copy import deepcopy

from commentscope.cluster_baseline import MODEL, REVISION
from commentscope.factory.automatic_contract import digest
from commentscope.factory.source_first import embedding_text
from commentscope.factory.source_index import VERSION as INDEX_VERSION, normalize
from commentscope.factory.target_ranking import target, text
from commentscope.providers.local_nli import decide

VERSION = 'whole-corpus-support-retrieval-0.1'
LIMITS = {'candidates': 32, 'recall_sources': 24, 'nli_sources': 5,
          'cosine_reserve': 2, 'pairs': 1000, 'window_chars': 500, 'overlap_chars': 50}


def windows(source):
    start = 0
    while start < len(source):
        end = min(len(source), start + LIMITS['window_chars'])
        yield {'start': start, 'end': end, 'text': source[start:end]}
        if end == len(source): break
        start = end - LIMITS['overlap_chars']


def schedule(proposals, units, cache, index, sources):
    if (len(proposals) > LIMITS['candidates'] or len({p['id'] for p in proposals}) != len(proposals)
            or len({u['claim_id'] for u in units}) != len(units)):
        raise ValueError('Unique bounded candidate and unit population required')
    if (cache['unit_ids'] != [u['claim_id'] for u in units]
            or cache['embedding_texts'] != [embedding_text(u) for u in units]
            or len(cache['vectors']) != len(units)):
        raise ValueError('Query embedding binding changed')
    ids = index['source_ids']
    if (index['artifact_kind'] != INDEX_VERSION or index['model'] != MODEL or index['model_revision'] != REVISION
            or not ids or ids != sorted(set(ids)) or len(ids) != len(index['vectors'])
            or index['source_sha256'] != [digest(sources[sid]) for sid in ids]):
        raise ValueError('Canonical source index binding changed')
    vectors = normalize(index['vectors']); queries = normalize(cache['vectors'])
    if queries and len(queries[0]) != len(vectors[0]): raise ValueError('Embedding dimensions differ')
    lookup = {u['claim_id']: (u, q) for u, q in zip(units, queries, strict=True)}
    candidates = []; queues = []
    for proposal in sorted(proposals, key=lambda p: p['id']):
        unit, query = lookup[proposal['anchor_unit_id']]; anchor = unit['source_comment_id']
        if (proposal['claims']['C'] != target(unit) or anchor not in ids
                or not unit['quote'] or unit['quote'] not in sources[anchor]):
            raise ValueError('Immutable target/original anchor required')
        nearest = sorted(({'source_id': sid, 'similarity': sum(a*b for a, b in zip(query, vector, strict=True))}
                          for sid, vector in zip(ids, vectors, strict=True) if sid != anchor),
                         key=lambda r: (-r['similarity'], r['source_id']))[:LIMITS['recall_sources']]
        candidate = {'candidate_id': proposal['id'], 'anchor_source_id': anchor,
                     'recall': [{**r, 'pair_ids': [], 'unranked_reason': None} for r in nearest]}
        candidates.append(candidate); queues.append((unit, candidate['recall']))
    pairs = []
    # Fair allocation across targets. A source gets ALL its windows or remains
    # explicitly unranked; never treat an unprocessed suffix as negative evidence.
    for rank in range(LIMITS['recall_sources']):
        for candidate, (unit, recall) in zip(candidates, queues, strict=True):
            if rank >= len(recall): continue
            row = recall[rank]; passages = list(windows(sources[row['source_id']]))
            if len(text(unit)) > 500:
                row['unranked_reason'] = 'hypothesis_length'; continue
            if len(pairs) + len(passages) > LIMITS['pairs']:
                row['unranked_reason'] = 'pair_budget'; continue
            for passage in passages:
                pid = f'W{len(pairs)+1:04}'; row['pair_ids'].append(pid)
                pairs.append({'id': pid, 'candidate_id': candidate['candidate_id'],
                              'premise_source_id': row['source_id'],
                              'source_sha256': digest(sources[row['source_id']]),
                              'start': passage['start'], 'end': passage['end'],
                              'premise': passage['text'], 'hypothesis': text(unit)})
    return {'artifact_kind': VERSION, 'index_sha256': digest(index), 'limits': deepcopy(LIMITS),
            'pairs': pairs, 'candidates': candidates, 'membership_approval': False}


def assemble(proposals, units, cache, index, sources, scheduled, result):
    if scheduled != schedule(proposals, units, cache, index, sources):
        raise ValueError('Support retrieval population changed')
    if len(result['rows']) != len(scheduled['pairs']): raise ValueError('Incomplete NLI result')
    scores = {}; errors = []
    for pair, row in zip(scheduled['pairs'], result['rows'], strict=True):
        if row['id'] != pair['id'] or row['pair_sha256'] != digest(pair) or not isinstance(row['errors'], list):
            raise ValueError('NLI request/result binding changed')
        if row['errors']:
            scores[row['id']] = None; errors.append(row['id'])
        else:
            decide(row['scores']); scores[row['id']] = row['scores']['entailment']
    output = []; rankings = []; lookup = {p['id']: p for p in proposals}
    for candidate in scheduled['candidates']:
        rows = []
        for recalled in candidate['recall']:
            values = [scores[pid] for pid in recalled['pair_ids']]
            complete = bool(values) and all(v is not None for v in values)
            rows.append({**deepcopy(recalled), 'ranking_complete': complete,
                         'ranking_score': max(values) if complete else None})
        ranked = sorted((r for r in rows if r['ranking_complete']),
                        key=lambda r: (-r['ranking_score'], -r['similarity'], r['source_id']))
        chosen = [r['source_id'] for r in ranked[:LIMITS['nli_sources']]]
        # Reserve two recall slots independently of NLI. Errors/long premises are
        # unknown, not disproof; low NLI scores also are NOT a rejection gate.
        reserve = [r['source_id'] for r in rows if r['source_id'] not in chosen][:LIMITS['cosine_reserve']]
        chosen += reserve
        if len(chosen) < LIMITS['nli_sources'] + LIMITS['cosine_reserve']:
            chosen += [r['source_id'] for r in rows if r['source_id'] not in chosen][:
                       LIMITS['nli_sources'] + LIMITS['cosine_reserve'] - len(chosen)]
        chosen = [candidate['anchor_source_id']] + chosen
        p = deepcopy(lookup[candidate['candidate_id']])
        p.update(sources={sid: sources[sid] for sid in chosen},
                 retrieval_kind=VERSION, semantic_approval=False, typing_required=True)
        output.append(p)
        rankings.append({'candidate_id': p['id'], 'rows': rows, 'selected_source_ids': chosen,
                         'cosine_reserve_source_ids': reserve})
    return {'artifact_kind': VERSION, 'proposals': output, 'rankings': rankings, 'pair_errors': errors,
            'canonical_search_count': len(index['source_ids']), 'membership_approval': False,
            'quality_gate_passed': False, 'runtime_reference_labels': False}
