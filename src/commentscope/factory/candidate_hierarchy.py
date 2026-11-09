"""Use observed candidate scope relations for retrieval, never vote propagation."""
from collections import defaultdict

from commentscope.factory import candidate_consolidation as cc, minimal_membership as mm
from commentscope.factory.automatic_contract import digest

VERSION = 'supported-parent-retrieval-20261110-v1'
MAXIMUM_PER_SOURCE = 3


def expansion(sources, initial_candidates, nominations, consolidation, equivalences,
              memberships, *, attempted=()):
    attempted=list(attempted)
    # Rebuild the exact graph provenance. A hand-edited alias or relation cannot
    # silently become a new search instruction. This invokes no model.
    rebuilt = cc.consolidate(sources, initial_candidates, nominations, equivalences)
    if rebuilt != consolidation:
        raise ValueError('Candidate hierarchy consolidation changed')
    candidates = consolidation['candidates']
    rows = mm.collect(sources, candidates, memberships)
    source_ids = {s['id'] for s in sources};candidate_ids = {c['id'] for c in candidates}
    tried = set()
    for pair in attempted:
        if (set(pair) != {'source_id','candidate_id'} or pair['source_id'] not in source_ids
                or pair['candidate_id'] not in candidate_ids):
            raise ValueError('Hierarchy attempted pair outside current scope')
        tried.add((pair['source_id'],pair['candidate_id']))
    tried.update((r['source_id'],r['candidate_id']) for r in rows)
    aliases = consolidation['alias_to_final'];parents = defaultdict(set)
    for batch in equivalences:
        for relation in batch['relations']:
            if relation['relation'] not in ('a_narrower','b_narrower'):
                continue
            child,parent = ((relation['a'],relation['b']) if relation['relation']=='a_narrower'
                            else (relation['b'],relation['a']))
            child,parent = aliases[child],aliases[parent]
            if child != parent:
                parents[child].add(parent)
    offered = defaultdict(set)
    for row in rows:
        if row['relation'] != 'supported':
            continue
        sid = row['source_id']
        # Only one hop from an already directly supported candidate. A new
        # search does not recursively expand its own hypothetical support.
        offered[sid].update(cid for cid in parents[row['candidate_id']] if (sid,cid) not in tried)
    selected = [];held = []
    for sid in sorted(offered):
        for index,cid in enumerate(sorted(offered[sid])):
            pair={'source_id':sid,'candidate_id':cid}
            if index < MAXIMUM_PER_SOURCE:selected.append(pair)
            else:held.append({**pair,'reason':'source_parent_search_limit'})
    return {'artifact_kind':VERSION,'sources_sha256':digest(sources),
            'initial_candidates_sha256':digest(initial_candidates),
            'consolidation_sha256':digest(consolidation),'equivalences_sha256':digest(equivalences),
            'memberships_sha256':digest(memberships),'attempted_sha256':digest(list(attempted)),
            'maximum_per_source':MAXIMUM_PER_SOURCE,'pairs':selected,'held_pairs':held,
            'memberships':[],'semantic_approval':False}
