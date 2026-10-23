"""Bounded existing-target search. NLI ranks proposals; it never admits members."""
from collections import defaultdict
from copy import deepcopy

from commentscope.factory.automatic_contract import digest
from commentscope.factory.source_first import bucket
from commentscope.providers.local_nli import decide, THRESHOLD

VERSION = 'existing-target-coverage-ranking-0.1'
MAX_PAIRS = 1000
MAX_UNITS_PER_GROUP = 24


def target(unit):
    return {'id':'C','text':unit['claim'],'kind':'fact',
            'scope':{'entity':unit['scope'],'time':'','conditions':unit['condition'] or ''},'requires':[]}


def text(unit):
    # Ranking cannot silently ignore a separately extracted condition.
    return unit['claim'] + ('\nCondition: '+unit['condition'] if unit['condition'] else '')


def schedule(proposals, units):
    index={u['claim_id']:u for u in units}
    if len(index)!=len(units) or len({p['id'] for p in proposals})!=len(proposals) or len(proposals)>20:
        raise ValueError('Unique bounded candidates and units required')
    pairs=[];eligible=[];deferred=[]
    for proposal in sorted(proposals,key=lambda p:p['id']):
        ids=sorted(proposal['candidate_unit_ids'])
        if len(set(ids))!=len(ids) or proposal['anchor_unit_id'] not in ids:
            raise ValueError('Unique units including original anchor required')
        selected=[index[i] for i in ids]
        if not selected or bucket(selected[0]) is None or any(bucket(u)!=bucket(selected[0]) for u in selected):
            raise ValueError('Ranking cannot merge incompatible frames')
        for u in selected:
            sid=u['source_comment_id']
            if sid not in proposal['sources'] or not u['quote'] or u['quote'] not in proposal['sources'][sid]:
                raise ValueError('Ranked unit must retain original source quote')
        if target(index[proposal['anchor_unit_id']])!=proposal['claims']['C']:
            raise ValueError('Original anchor target changed')
        if len(ids)>MAX_UNITS_PER_GROUP:
            deferred.append({'id':proposal['id'],'reason':'ranking_unit_budget'});continue
        queued=[{'candidate_id':proposal['id'],'premise_unit_id':p['claim_id'],
                 'premise_source_id':p['source_comment_id'],'target_unit_id':h['claim_id'],
                 'premise':text(p),'hypothesis':text(h)}
                for h in selected for p in selected if p['source_comment_id']!=h['source_comment_id']]
        if len(pairs)+len(queued)>MAX_PAIRS:
            deferred.append({'id':proposal['id'],'reason':'ranking_pair_budget'});continue
        eligible.append(proposal['id'])
        for row in queued:pairs.append({'id':f'K{len(pairs)+1:04}',**row})
    return {'pairs':pairs,'eligible':eligible,'deferred':deferred}


def assemble(proposals, units, scheduled, results):
    if scheduled!=schedule(proposals,units):raise ValueError('Ranking population changed')
    pairs=scheduled['pairs']; rows=results['rows']
    if len(rows)!=len(pairs):raise ValueError('Incomplete ranking results')
    scores=defaultdict(dict);errors=[]
    for pair,row in zip(pairs,rows,strict=True):
        if row['id']!=pair['id'] or row['pair_sha256']!=digest(pair):
            raise ValueError('Ranking score binding changed')
        if not isinstance(row['errors'],list):raise ValueError('Invalid ranking error record')
        if row['errors']:
            errors.append(pair['id']);value=0.
        else:
            decide(row['scores'])  # validates finite, normalized known labels
            value=row['scores']['entailment']
        key=(pair['candidate_id'],pair['target_unit_id']);sid=pair['premise_source_id']
        scores[key][sid]=max(value,scores[key].get(sid,0.))
    index={u['claim_id']:u for u in units};alternatives=[];rankings=[]
    for proposal in sorted(proposals,key=lambda p:p['id']):
        if proposal['id'] not in scheduled['eligible']:continue
        ranked=[]
        for uid in proposal['candidate_unit_ids']:
            per_source=scores[(proposal['id'],uid)]
            ranked.append({'unit_id':uid,'estimated_other_source_count':sum(v>=THRESHOLD for v in per_source.values()),
                           'score_sum':sum(per_source.values()),'source_max_scores':dict(sorted(per_source.items()))})
        ranked.sort(key=lambda r:(-r['estimated_other_source_count'],-r['score_sum'],
                                  r['unit_id']!=proposal['anchor_unit_id'],r['unit_id']))
        best=ranked[0]['unit_id']
        rankings.append({'candidate_id':proposal['id'],'ranked':ranked,'selected_unit_id':best})
        claim=target(index[best])
        if claim!=proposal['claims']['C']:
            alternatives.append({**deepcopy(proposal),'id':proposal['id']+'-N1',
                'parent_candidate_id':proposal['id'],'claims':{'C':claim},'anchor_unit_id':best,
                'semantic_approval':False,'typing_required':True})
    return {'artifact_kind':VERSION,'alternatives':alternatives,'rankings':rankings,
            'deferred':scheduled['deferred'],'pair_errors':errors,
            'membership_approval':False,'quality_gate_passed':False,'runtime_reference_labels':False}
