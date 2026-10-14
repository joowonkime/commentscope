"""Raw-source retrieval before any generative selection or eligibility gate.

Candidates and queued comparisons are NOT claims, cluster members or support votes.
Every selected canonical nonempty source remains in the registry, even with no edge.
"""
from collections import Counter
import math
import re

from commentscope.factory.automatic_contract import digest
from commentscope.ingestion import normalize_snapshot

VERSION = 'raw-candidates-0.1'
POLICY = {'semantic_slots': 8, 'lexical_slots': 4, 'pair_budget': 64,
          'max_sources': 1000, 'generative_calls': 0, 'support_votes': 0}


def registry(snapshot, selected_ids=None):
    normalized = {r.comment_id:r for r in normalize_snapshot(snapshot)}
    originals = {c.comment_id:c for c in snapshot.comments}
    requested = list(originals) if selected_ids is None else list(selected_ids)
    if len(requested) != len(set(requested)) or any(cid not in originals for cid in requested):
        raise ValueError('Duplicate or unknown source selection')
    selected = set(requested)
    # Include canonical targets of requested duplicate aliases; never count aliases twice.
    canonical = {normalized[cid].duplicate_of or cid for cid in selected}
    if len(canonical) > POLICY['max_sources']: raise ValueError('Source budget exceeded')
    sources = []
    for cid in sorted(canonical):
        original = originals[cid]
        sources.append({'source_id':cid, 'text':original.text_original,
                        'source_digest':digest(original.text_original),
                        'parent_id':original.parent_id,
                        'indexable':bool(normalized[cid].text_analysis)})
    return {'version':VERSION, 'sources':sources,
            'aliases':{cid:normalized[cid].duplicate_of for cid in sorted(selected) if normalized[cid].duplicate_of},
            'selected_input_ids':sorted(selected), 'semantic_filter_applied':False}


def validate_registry(value, snapshot):
    if value != registry(snapshot,value['selected_input_ids']):
        raise ValueError('Registry source, selection or alias changed')


def normalized_vectors(rows, count):
    if len(rows) != count: raise ValueError('Vector count mismatch')
    result, dim = [], None
    for v in rows:
        if (not isinstance(v,list) or not v or
                any(type(x) not in (float,int) or not math.isfinite(x) for x in v) or
                dim is not None and len(v) != dim): raise ValueError('Invalid vector')
        dim = len(v)
        length = math.sqrt(sum(x*x for x in v))
        if not length or not math.isfinite(length): raise ValueError('Invalid norm')
        result.append([x/length for x in v])
    return result


def search(value, vectors, *, backend='python'):
    sources = value['sources']
    ids = [s['source_id'] for s in sources]
    if (len(ids) != len(set(ids)) or len(ids) > POLICY['max_sources'] or
            any(s['source_digest'] != digest(s['text']) for s in sources)):
        raise ValueError('Invalid source registry')
    active = [s for s in sources if s['indexable']]
    active_ids = [s['source_id'] for s in active]
    rows = normalized_vectors(vectors,len(active))
    if backend not in ('python','numpy'): raise ValueError('Invalid vector backend')
    # Vectorized dense similarity for this <=1000 MVP. No all-pairs LLM calls.
    if backend == 'numpy' and rows:
        import numpy as np
        matrix = np.asarray(rows,dtype=np.float64)
        similarities = np.clip(matrix @ matrix.T,-1.,1.).tolist()
    else:
        similarities = [[max(-1.,min(1.,sum(a*b for a,b in zip(x,y)))) for y in rows] for x in rows]
    counts = [Counter(re.findall(r'\w+',s['text'].casefold())) for s in active]
    df = Counter(t for c in counts for t in c)
    lexical = [{t:(1+math.log(n))*math.log(1+len(active)/df[t]) for t,n in c.items()} for c in counts]
    norms = [math.sqrt(sum(x*x for x in r.values())) for r in lexical]
    result = {sid:[] for sid in ids}
    for i,sid in enumerate(active_ids):
        eligible = [j for j in range(len(active)) if i != j]
        semantic = sorted(eligible,key=lambda j:(-similarities[i][j],active_ids[j]))[:POLICY['semantic_slots']]
        lexical_scores = {j:sum(x*lexical[j].get(t,0.) for t,x in lexical[i].items())/(norms[i]*norms[j])
                          if norms[i] and norms[j] else 0. for j in eligible}
        extra = sorted((j for j in eligible if j not in semantic and lexical_scores[j] > 0),
                       key=lambda j:(-lexical_scores[j],active_ids[j]))[:POLICY['lexical_slots']]
        result[sid] = [{'source_id':active_ids[j], 'cosine':similarities[i][j], 'lexical':lexical_scores[j],
                        'route':'semantic' if j in semantic else 'lexical'} for j in [*semantic,*extra]]
    return result


def queue(value, candidates, budget=POLICY['pair_budget']):
    if type(budget) is not int or not 0 <= budget <= 10000: raise ValueError('Invalid pair budget')
    sources = {s['source_id']:s for s in value['sources']}
    if set(candidates) != set(sources): raise ValueError('Candidate registry mismatch')
    for sid, links in candidates.items():
        if (len(links) > POLICY['semantic_slots']+POLICY['lexical_slots'] or
                len({r['source_id'] for r in links}) != len(links) or
                (links and not sources[sid]['indexable']) or
                any(r['source_id'] not in sources or r['source_id'] == sid or
                    not sources[r['source_id']]['indexable'] for r in links)):
            raise ValueError('Invalid candidate references')
    # Rank-round-robin across stable source order; symmetric edges consume one slot.
    order = sorted(sources,key=lambda sid:(digest(['raw-queue',sid]),sid))
    pairs, seen = [], set()
    for rank in range(max(map(len,candidates.values()),default=0)):
        for sid in order:
            if rank >= len(candidates[sid]): continue
            other = candidates[sid][rank]['source_id']
            pair = tuple(sorted([sid,other]))
            if pair in seen: continue
            seen.add(pair)
            pairs.append({'pair_id':'R'+digest([[x,sources[x]['source_digest']] for x in pair])[:20],
                          'source_ids':list(pair), 'first_discovered_from':sid, 'candidate_rank':rank+1})
    return {'pairs':pairs[:budget], 'available_unique_pairs':len(pairs),
            'deferred_pairs':len(pairs)-min(budget,len(pairs)), 'pair_budget':budget,
            'budget_exhausted':len(pairs)>budget, 'support_count':None, 'agents':[],
            'quality_gate_passed':False, 'status':'candidates_only'}


def source_packet(value, pair):
    sources = {s['source_id']:s for s in value['sources']}
    ids = pair['source_ids']
    if len(ids)!=2 or len(set(ids))!=2 or any(s not in sources for s in ids):
        raise ValueError('Invalid pair sources')
    if any(sources[s]['source_digest'] != digest(sources[s]['text']) for s in ids):
        raise ValueError('Source text changed')
    expected = 'R'+digest([[x,sources[x]['source_digest']] for x in sorted(ids)])[:20]
    if pair['pair_id'] != expected: raise ValueError('Pair source binding changed')
    return {'sources':[{'source_id':sid,'source_digest':sources[sid]['source_digest'],
                        'text':sources[sid]['text']} for sid in ids]}


def build(value,vectors,*,backend='python',budget=POLICY['pair_budget']):
    links = search(value,vectors,backend=backend)
    pending = queue(value,links,budget)
    return {'version':VERSION, 'registry_digest':digest(value), 'vectors_digest':digest(vectors),
            'candidates':links, 'queue':pending,
            'summary':{'canonical_sources':len(value['sources']),
                       'indexable_sources':sum(s['indexable'] for s in value['sources']),
                       'duplicate_aliases':len(value['aliases']),
                       'directed_candidates':sum(map(len,links.values())),
                       'queued_pairs':len(pending['pairs']), 'deferred_pairs':pending['deferred_pairs'],
                       'generative_calls':0, 'support_count':None, 'agents_generated':0}}
