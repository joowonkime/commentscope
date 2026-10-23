"""Combine disjoint actual nomination censuses without inventing a joint call."""
from copy import deepcopy
from commentscope.factory import policy_stance_hypotheses as stance,minimal_claims as mc
from commentscope.factory.automatic_contract import digest

VERSION='disjoint-original-policy-censuses-20261023-v1'


def combine(records,sources):
    expected=mc.source_index(sources);seen={}
    if not isinstance(records,list) or not records:raise ValueError('Actual disjoint census records required')
    topic=records[0]['topic'];alias=records[0]['alias']
    stance.hypotheses(sources,topic,alias)
    for record in records:
        stance.validate(record)
        if record['topic']!=topic or record['alias']!=alias:raise ValueError('Policy topic changed across actual batches')
        for source in record['sources']:
            sid=source['id']
            if sid in seen or expected.get(sid)!=source:raise ValueError('Duplicate or changed original across actual censuses')
            seen[sid]=source
    if seen!=expected:raise ValueError('Every original must retain exactly one actual comparison batch')
    return {'artifact_kind':VERSION,'sources':deepcopy(sources),'topic':topic,'alias':alias,
        'parts':deepcopy(records),'semantic_approval':False,'synthetic_joint_request':False}


def validate(record):
    if combine(record['parts'],record['sources'])!=record:raise ValueError('Disjoint source-census union changed')
    return record


def candidates(record):
    validate(record);lookup={row['id']:row for part in record['parts'] for row in part['response']['results']};out=[]
    for hypothesis in stance.hypotheses(record['sources'],record['topic'],record['alias']):
        cid=hypothesis['id'];nominees={s['id']:digest(s) for s in record['sources']
            if lookup['SP'+digest([s['id'],cid])]['state']=='supported'}
        if nominees:out.append(mc.validate_candidate({'id':cid,'text':hypothesis['text'],'aliases':[cid],
            'nominees':nominees,'extraction_refs':[digest(record)],'equivalence_refs':[]}))
    return sorted(out,key=lambda c:c['id'])
