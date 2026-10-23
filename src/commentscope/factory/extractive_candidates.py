"""Literal sentence candidates, similarity scheduling only, never support votes."""
from commentscope.factory.automatic_contract import digest, segments
from commentscope.factory import raw_support, raw_candidates, positional_support

VERSION = 'extractive-candidates-0.1'
POLICY = {'per_source_candidates': 2, 'max_core_characters': 249,
          'max_source_characters': 4000, 'max_source_segments': 80,
          'proposal_calls': 0, 'agents': False}


def inventory(sources):
    ids = [s['source_id'] for s in sources]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate source IDs')
    result = []
    for source in sources:
        raw_support.validate_source(source)
        pieces = segments(source['text'])
        over = len(source['text']) > POLICY['max_source_characters'] or len(pieces) > POLICY['max_source_segments']
        for part in pieces:
            reason = ('source_budget' if over else 'empty' if not part['text'].strip()
                      else 'core_character_budget' if len(part['text']) > POLICY['max_core_characters'] else None)
            result.append({'candidate_id': 'E'+digest([source['source_id'], source['source_digest'],
                                                      part['start'],part['end']])[:24],
                           'source_id':source['source_id'], 'source_digest':source['source_digest'],
                           'segment_id':part['id'], 'start':part['start'], 'end':part['end'],
                           'text':part['text'], 'eligible':reason is None, 'deferred_reason':reason})
    return result


def rank(sources, candidates, vectors):
    """Input carries no reference spans, labels or model-generated claims."""
    if len(sources) != 2 or len({s['source_id'] for s in sources}) != 2:
        raise ValueError('Expected two distinct sources')
    expected = inventory(sources)
    if candidates != expected:
        raise ValueError('Candidate source binding changed')
    active = [c for c in candidates if c['eligible']]
    if set(vectors) != {c['candidate_id'] for c in active}:
        raise ValueError('Vector inventory mismatch')
    normalized = raw_candidates.normalized_vectors([vectors[c['candidate_id']] for c in active],len(active))
    vm = {c['candidate_id']:v for c,v in zip(active,normalized)}
    sides = [[c for c in active if c['source_id'] == s['source_id']] for s in sources]
    rankings = {}
    for own, other in [(sides[0],sides[1]),(sides[1],sides[0])]:
        for c in own:
            matches = [{'candidate_id':p['candidate_id'],
                        'cosine':max(-1.,min(1.,sum(a*b for a,b in zip(vm[c['candidate_id']],vm[p['candidate_id']]))))}
                       for p in other]
            matches.sort(key=lambda r:(-r['cosine'],r['candidate_id']))
            rankings[c['candidate_id']] = {'best_match':matches[0] if matches else None}
    ordered = []
    for side in sides:
        side = [c for c in side if rankings[c['candidate_id']]['best_match']]
        ordered.append(sorted(side,key=lambda c:(-rankings[c['candidate_id']]['best_match']['cosine'],c['candidate_id'])))
    selected, by_text = [], {}
    for position in range(POLICY['per_source_candidates']):
        for side in ordered:
            if position >= len(side): continue
            c = side[position]
            origin = {'candidate_id':c['candidate_id'], 'source_id':c['source_id'], 'rank':position+1,
                      'best_match':rankings[c['candidate_id']]['best_match']}
            if c['text'] in by_text:
                selected[by_text[c['text']]]['origins'].append(origin)
            else:
                by_text[c['text']] = len(selected)
                selected.append({'core':c['text'], 'core_digest':digest(c['text']), 'origins':[origin]})
    selected_ids = {o['candidate_id'] for c in selected for o in c['origins']}
    rows = []
    for c in candidates:
        match = rankings.get(c['candidate_id'],{}).get('best_match')
        rows.append({**c, 'best_match':match,
                     'status':('selected' if c['candidate_id'] in selected_ids else
                               'deferred_budget' if c['eligible'] and match else
                               'no_other_candidate' if c['eligible'] else 'deferred_input')})
    return {'version':VERSION,'source_ids':[s['source_id'] for s in sources],
            'input_digest':digest(sources),'inventory':rows,'selected':selected,
            'support_count':None,'agents':[],'quality_gate_passed':False}


def assess(sources, candidate, calls, scores):
    if len(sources) != 2 or len({s['source_id'] for s in sources}) != 2:
        raise ValueError('Expected two distinct sources')
    valid = {c['candidate_id']:c for c in inventory(sources) if c['eligible']}
    if (not candidate['origins'] or candidate['core_digest'] != digest(candidate['core']) or
            any(o['candidate_id'] not in valid or valid[o['candidate_id']]['text'] != candidate['core']
                or valid[o['candidate_id']]['source_id'] != o['source_id'] for o in candidate['origins'])):
        raise ValueError('Unbound extractive target')
    checks = [positional_support.check(s,candidate['core'],calls,scores) for s in sources]
    return {**candidate, 'checks':checks,
            'model_pair_passed':all(c['state']=='support' for c in checks),
            'quality_gate_passed':False}
