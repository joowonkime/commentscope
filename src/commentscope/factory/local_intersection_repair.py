"""Re-propose local intersections when an earlier common text has a deictic gap.

Every nominated original enters unchanged, including false nominations. No
review labels or repaired pack enters the model. New outputs remain unapproved
hypotheses and must pass the ordinary original/argument/fact gates.
"""
from copy import deepcopy
import re
from commentscope.factory import minimal_claims as mc,shared_claims
from commentscope.factory.automatic_contract import digest

VERSION='deictic-common-neighborhood-repair-20261023-v1'
DEICTIC=re.compile(r'\b(?:this|that)\s+(?:much|amount|money|policy|model|way)\b|\bfor\s+(?:it|them)\b',re.I)


def neighborhoods(sources,candidates):
    ss=mc.source_index(sources);seen=set();groups=[]
    for candidate in sorted(candidates,key=lambda c:c['id']):
        mc.validate_candidate(candidate)
        if candidate['id'] in seen:raise ValueError('Duplicate common hypothesis')
        seen.add(candidate['id'])
        if any(sid not in ss or digest(ss[sid])!=bound for sid,bound in candidate['nominees'].items()):
            raise ValueError('Every nominated original must retain exact provenance')
        if not DEICTIC.search(candidate['text']) or len(candidate['nominees'])<3:continue
        ids=sorted(candidate['nominees'])
        if len(ids)>shared_claims.BATCH_SIZE:raise ValueError('Unsplit local group exceeds frozen proposal capacity')
        groups.append({'candidate_id':candidate['id'],'candidate_sha256':digest(candidate),
            'source_ids':ids,'sources':[deepcopy(ss[sid]) for sid in ids],
            'prior_nominees_are_support':False,'semantic_approval':False})
    return groups


def request(group):
    if [s['id'] for s in group['sources']]!=group['source_ids']:raise ValueError('Complete local source inventory required')
    # The old generated text is deliberately absent: regenerate the intersection
    # from originals rather than inviting the model to defend its old verdict.
    return shared_claims.request(group['sources'],version=shared_claims.COMMON)


def bind(group,result):
    request(group)
    return shared_claims.bind(group['sources'],result,version=shared_claims.COMMON)
