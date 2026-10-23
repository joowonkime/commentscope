"""Bounded policy-value hypotheses nominated by original-only comparisons.

The topic must occur verbatim in the one video's metadata. Templates deliberately
state conditional possibility, never a shared rationale, universal endorsement
or fabricated condition. Classifier nominations do not count as source votes.
Raw authorship, own evidence, fixed conditions, reasons and facts still need
their independent downstream gates. Every original remains in the record.
"""
from copy import deepcopy

from commentscope.factory import minimal_claims as mc,nli_fact_records
from commentscope.factory.automatic_contract import digest
from commentscope.providers import evidence_nli

VERSION='original-policy-value-hypotheses-20261023-v1'
POLARITIES={'favorable':'can be a desirable policy under some circumstances.',
            'unfavorable':'can be an undesirable policy under some circumstances.'}


def hypotheses(sources,topic,alias):
    registry=mc.source_index(sources)
    if not registry or not all(isinstance(t,str) and t.strip()==t and 1<=len(t)<=80 for t in [topic,alias]):
        raise ValueError('Exact metadata topic and alias required')
    videos=[s.get('video_context') for s in sources]
    if (any(not isinstance(v,dict) for v in videos) or len({v['video_id'] for v in videos})!=1 or
            len({v['title'] for v in videos})!=1 or any(topic not in v['title'] or alias not in v['title'] for v in videos)):
        raise ValueError('Topic/alias must occur in the same immutable video title')
    label=topic if topic==alias else topic+' ('+alias+')'
    return [{'polarity':polarity,'id':mc.claim_id(label+' '+suffix),'text':label+' '+suffix}
            for polarity,suffix in POLARITIES.items()]


def invocation(sources,topic,alias):
    cs=hypotheses(sources,topic,alias)
    return {'system':evidence_nli.VERSION,'schema':{},'max_tokens':1,
        'data':{'cases':[{'id':'SP'+digest([s['id'],c['id']]),'text':c['text'],
            'evidence':[{'id':s['id'],'text':s['text']}]} for s in sorted(sources,key=lambda s:s['id'])
            for c in sorted(cs,key=lambda c:c['id'])]}}


def bind(sources,topic,alias,response):
    request=invocation(sources,topic,alias);cases=request['data']['cases']
    if ([r['id'] for r in response['results']]!=[c['id'] for c in cases] or response['forward_pairs']!=len(cases)):
        raise ValueError('Every original must be compared to both hypotheses exactly once')
    for case,result in zip(cases,response['results'],strict=True):
        nli_fact_records.validate_result(result,case,response['metadata'])
        if any(not p['errors'] and (type(p.get('input_tokens')) is not int or
                not 1<=p['input_tokens']<=512) for p in result['pairs']):
            raise ValueError('Whole source must not be truncated beyond classifier capacity')
    return {'artifact_kind':VERSION,'sources':deepcopy(sources),'topic':topic,'alias':alias,
        'request_sha256':digest(request),'response':deepcopy(response),'semantic_approval':False}


def validate(record):
    if bind(record['sources'],record['topic'],record['alias'],record['response'])!=record:
        raise ValueError('Policy-value source/comparison provenance changed')
    return record


def candidates(record):
    validate(record);lookup={r['id']:r for r in record['response']['results']};out=[]
    for hypothesis in hypotheses(record['sources'],record['topic'],record['alias']):
        cid=hypothesis['id'];nominees={s['id']:digest(s) for s in record['sources']
            if lookup['SP'+digest([s['id'],cid])]['state']=='supported'}
        if nominees:out.append(mc.validate_candidate({'id':cid,'text':hypothesis['text'],'aliases':[cid],
            'nominees':nominees,'extraction_refs':[digest(record)],'equivalence_refs':[]}))
    return sorted(out,key=lambda c:c['id'])
