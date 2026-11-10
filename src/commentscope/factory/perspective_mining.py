"""Bounded candidate-first retrieval; scores/nominees never approve support."""
from collections import defaultdict, deque

from commentscope.factory import minimal_claims as mc, candidate_consolidation as cc
from commentscope.factory.automatic_contract import digest

VERSION = 'candidate-first-evidence-search-20261110-v1'
FIELDS = {'version', 'sources_per_candidate', 'maximum_pairs', 'maximum_sources', 'maximum_snapshot_comments'}


def policy(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value['version'] != VERSION:
        raise ValueError('Closed versioned perspective-mining policy required')
    for key, maximum in (('sources_per_candidate', 64), ('maximum_pairs', 1000000),
                         ('maximum_sources', 3000), ('maximum_snapshot_comments', 3000)):
        if type(value[key]) is not int or not 1 <= value[key] <= maximum:
            raise ValueError('Finite positive mining bound required: ' + key)
    if value['maximum_sources'] > value['maximum_snapshot_comments']:
        raise ValueError('Selected-source bound exceeds snapshot bound')
    return dict(value)


def bounds(value, source_count, candidate_count):
    value = policy(value)
    pairs = min(value['maximum_pairs'], candidate_count * min(source_count, value['sources_per_candidate']),
                min(source_count, value['maximum_sources']) * candidate_count)
    return {'pair_upper_bound': pairs,
            'source_upper_bound': min(source_count, value['maximum_sources'], pairs)}


def schedule(sources, candidates, source_vectors, candidate_vectors, *, configuration):
    configuration = policy(configuration)
    ss = mc.source_index(sources)
    if len(ss) > configuration['maximum_snapshot_comments']:
        raise ValueError('Snapshot exceeds explicit perspective-mining bound')
    cs = {c['id']: mc.validate_candidate(c) for c in candidates}
    if len(cs) != len(candidates) or set(source_vectors) != set(ss) or set(candidate_vectors) != set(cs):
        raise ValueError('Exact source/candidate/vector inventory required')
    for c in candidates:
        if any(sid not in ss or fingerprint != digest(ss[sid]) for sid, fingerprint in c['nominees'].items()):
            raise ValueError('Mining nominee belongs to another original')
    sv = cc.vectors(source_vectors)
    cv = cc.vectors(candidate_vectors) if cs else {}
    if cv and len(next(iter(sv.values()))) != len(next(iter(cv.values()))):
        raise ValueError('Mining vector spaces differ')
    def dot(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))
    def thread(sid):
        parent = ss[sid].get('parent')
        return parent['id'] if parent else sid
    queues = {}
    for cid in sorted(cs):
        scores = {}
        for sid in ss:
            own = dot(sv[sid], cv[cid]); parent = ss[sid].get('parent')
            inherited = dot(sv[parent['id']], cv[cid]) if parent and parent['id'] in sv else None
            scores[sid] = max(own, inherited) if inherited is not None else own
        ordered = sorted(ss, key=lambda sid: (sid not in cs[cid]['nominees'], -scores[sid], sid))
        groups = defaultdict(deque)
        for sid in ordered:
            groups[thread(sid)].append(sid)
        # First occurrence fixes thread order; breadth across threads precedes
        # another item from the same thread. This never transfers a parent vote.
        threads = deque(groups.values()); ranked = deque()
        while threads and len(ranked) < configuration['sources_per_candidate']:
            group = threads.popleft(); ranked.append(group.popleft())
            if group:
                threads.append(group)
        queues[cid] = ranked
    pairs = []; selected = set(); counts = dict.fromkeys(cs, 0)
    order = sorted(cs, key=lambda cid: (-len({thread(sid) for sid in cs[cid]['nominees']}),
                                       -len(cs[cid]['nominees']), cid))
    # Fund an evidence-search batch before opening the next candidate. Spreading
    # one pair to every hypothesis can leave all of them below the 3-source gate.
    # Priority is retrieval only; low-priority hypotheses remain unassessed.
    for cid in order:
        while (queues[cid] and counts[cid] < configuration['sources_per_candidate']
               and len(pairs) < configuration['maximum_pairs']):
            sid = queues[cid].popleft()
            if sid not in selected and len(selected) >= configuration['maximum_sources']:
                continue
            pairs.append({'source_id': sid, 'candidate_id': cid})
            selected.add(sid); counts[cid] += 1
        if len(pairs) >= configuration['maximum_pairs']:
            break
    stops = []
    if len(pairs) == configuration['maximum_pairs']: stops.append('pair_limit')
    if len(selected) == configuration['maximum_sources']: stops.append('source_limit')
    if any(n == configuration['sources_per_candidate'] for n in counts.values()): stops.append('candidate_limit')
    def retrieval(pair):
        sid, cid = pair['source_id'], pair['candidate_id']; parent = ss[sid].get('parent')
        return {**pair, 'own_similarity': dot(sv[sid], cv[cid]),
                'parent_similarity': dot(sv[parent['id']], cv[cid]) if parent and parent['id'] in sv else None,
                'nominated': sid in cs[cid]['nominees'], 'semantic_approval': False}
    return {'artifact_kind': VERSION, 'policy': configuration,
            'input_sha256': digest([sources, candidates, source_vectors, candidate_vectors]),
            'source_count': len(ss), 'candidate_count': len(cs), 'pairs': pairs,
            'candidate_search_order': order,
            'pair_retrieval': [retrieval(p) for p in pairs],
            'selected_source_ids': sorted(selected), 'selected_pair_count': len(pairs),
            'unassessed_pair_count': len(ss) * len(cs) - len(pairs),
            'candidate_states': [{'candidate_id': cid, 'selected_source_count': counts[cid],
                                  'unassessed_source_count': len(ss) - counts[cid]} for cid in sorted(cs)],
            'source_states': [{'source_id': sid, 'thread_context_id': thread(sid),
                               'state': 'selected_for_comparison' if sid in selected else 'not_selected'} for sid in sorted(ss)],
            'stop_reasons': stops or ['all_pairs_planned' if len(pairs) == len(ss) * len(cs) else 'no_candidates'],
            'semantic_approval': False, 'full_corpus_coverage': False}
