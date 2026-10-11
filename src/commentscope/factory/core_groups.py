"""Bounded diagnostic assembly: freeze a seed core, then require direct support from each member."""
from commentscope.factory.automatic_contract import digest

VERSION='common-core-assembly-0.1'


def assemble(units, candidates, discover, attach, *, budget=64, seed_limit=2, max_chars=10000,
             cross_mode=False):
    if type(cross_mode) is not bool: raise ValueError('Invalid mode policy')
    if type(budget) is not int or not 1<=budget<=250: raise ValueError('Invalid diagnostic budget')
    if type(seed_limit) is not int or not 1<=seed_limit<=2: raise ValueError('Invalid seed limit')
    by_id={u['claim_id']:u for u in units}
    if len(by_id)!=len(units) or set(candidates)!=set(by_id): raise ValueError('Invalid unit/candidate inventory')
    for uid,rows in candidates.items():
        if len(rows)>12 or len({r['claim_id'] for r in rows})!=len(rows): raise ValueError('Invalid neighbor count')
        for row in rows:
            mid=row['claim_id']
            if (mid not in by_id or uid==mid or by_id[uid]['source_comment_id']==by_id[mid]['source_comment_id']
                    or (not cross_mode and by_id[uid]['mode']!=by_id[mid]['mode'])): raise ValueError('Invalid candidate edge')
    remaining=set(by_id)
    groups,decisions=[],[]
    exhausted=False
    size=lambda uid:sum(len(s['text']) for s in by_id[uid]['spans'])
    for aid in sorted(by_id,key=lambda uid:(-len(candidates[uid]),uid)):
        if aid not in remaining or (not cross_mode and by_id[aid]['mode']=='unclear'): continue
        choices=[r['claim_id'] for r in candidates[aid] if r['claim_id'] in remaining]
        if len({by_id[uid]['source_comment_id'] for uid in [aid,*choices]})<3: continue
        for mid in choices[:seed_limit]:
            if len(decisions)>=budget: exhausted=True;break
            if size(aid)+size(mid)>max_chars: continue
            trace=discover(by_id[aid],by_id[mid])
            seed_index=len(decisions)
            decisions.append({'kind':'seed','anchor_id':aid,'member_id':mid,'result':trace})
            core=trace['selected_core']
            if not core: continue
            members=[aid,mid]
            sources={by_id[u]['source_comment_id'] for u in members}
            chars=size(aid)+size(mid)
            for uid in choices:
                if by_id[uid]['source_comment_id'] in sources or chars+size(uid)>max_chars: continue
                if len(members)>=9: break
                if len(decisions)>=budget: exhausted=True;break
                result=attach(by_id[uid],core)
                decisions.append({'kind':'attach','seed_index':seed_index,'member_id':uid,'core':core,'result':result})
                if result['allowed']:
                    members.append(uid);sources.add(by_id[uid]['source_comment_id']);chars+=size(uid)
            if len(sources)>=3:
                groups.append({'cluster_id':f'SC{len(groups)+1:03d}','seed_index':seed_index,
                               'common_claim':core,'member_ids':members,'source_count':len(sources)})
                remaining.difference_update(members)
                break
            if exhausted: break
        if exhausted: break
    return {'artifact_kind':'common-core-assembly-0.2' if cross_mode else VERSION,
            **({'cross_mode':True} if cross_mode else {}),
            'unit_digest':digest(units),'candidate_digest':digest(candidates),
            'budget':budget,'seed_limit':seed_limit,'max_chars':max_chars,'decisions':decisions,'groups':groups,
            'unassigned_ids':sorted(remaining),'budget_exhausted':exhausted,'human_handling':False,
            'accepted_perspectives':0}


def replay(units,candidates,stored,verify_seed,verify_attach):
    stream=iter(stored['decisions'])
    def next_row():
        try:return next(stream)
        except StopIteration:raise ValueError('Missing assembly decision') from None
    def discover(a,b):
        row=next_row()
        if row.get('kind')!='seed' or row['anchor_id']!=a['claim_id'] or row['member_id']!=b['claim_id']:
            raise ValueError('Seed edge changed')
        if verify_seed(a,b)!=row['result']:raise ValueError('Seed replay changed')
        return row['result']
    def attach(u,core):
        row=next_row()
        if row.get('kind')!='attach' or row['member_id']!=u['claim_id'] or row['core']!=core:
            raise ValueError('Attachment edge changed')
        if verify_attach(u,core)!=row['result']:raise ValueError('Attachment replay changed')
        return row['result']
    rebuilt=assemble(units,candidates,discover,attach,budget=stored['budget'],
                     seed_limit=stored['seed_limit'],max_chars=stored['max_chars'],cross_mode=stored.get('cross_mode',False))
    if next(stream,None) is not None or rebuilt!=stored:raise ValueError('Assembly changed')
    return rebuilt
