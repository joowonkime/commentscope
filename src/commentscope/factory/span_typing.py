"""Typing with host-bound reason ranges, not model-authored quotations.

Uses the existing semantic typing policy and exact sentence-span utilities.
Structural provenance does not establish reason relevance or correct typing.
"""
from copy import deepcopy
import json

from commentscope.contracts.perspective_draft import obj,array
from commentscope.factory import perspective_typing as legacy, positional_support
from commentscope.factory.automatic_contract import digest

VERSION='source-range-perspective-typing-0.1'
SYSTEM=legacy.SYSTEM.replace(
    'using exact complete source\nquotes.',
    'by selecting source_id and contiguous first/last sentence IDs. '
    'Never write quotation text. Each selected range must be complete and at most 500 characters.')


def prefix(sid,text):
    return digest([sid,text])[:12]+'-'


def inventory(sources):
    if not sources or any(not isinstance(sid,str) or not sid or not isinstance(text,str) or not text.strip()
                          for sid,text in sources.items()):
        raise ValueError('Nonempty member source registry required')
    return {sid:positional_support.parts(text,prefix(sid,text)) for sid,text in sorted(sources.items())}


def invocation(claim,sources):
    parts=inventory(sources)
    ids=[p['id'] for rows in parts.values() for p in rows]
    if len(ids)!=len(set(ids)):raise ValueError('Source range identity collision')
    ref={'type':'string','enum':ids}
    detail=obj({'id':{'type':'string','enum':['D1','D2']},
                'kind':{'type':'string','enum':list(legacy.KINDS)},
                'source_id':{'type':'string','enum':list(parts)},'first':ref,'last':ref})
    schema={'anyOf':[obj({'status':{'type':'string','const':'defer'},
                         'reason':{'type':'string','enum':['non_substantive','mixed_or_unclear','essential_grounds_overflow']}}),
        obj({'status':{'type':'string','const':'classified'},'kind':{'type':'string','enum':list(legacy.KINDS)},
             'details':array(detail,maximum=2),
             'required_fact_ids':array({'type':'string','enum':['D1','D2']},maximum=2)})]}
    request={'system':SYSTEM+'\nRequired schema:\n'+json.dumps(schema),
             'data':{'CORE':claim['text'],'MEMBER_SOURCES':parts},'schema':schema,'max_tokens':650}
    if len(json.dumps(request).encode())>27000:raise ValueError('Typing request byte budget exceeded')
    return request


def apply(proposal,value,members):
    if not isinstance(value,dict):raise ValueError('Invalid typing envelope')
    if value.get('status')=='defer':return legacy.apply(proposal,value,members)
    if set(value)!={'status','kind','details','required_fact_ids'} or not isinstance(value['details'],list) or len(value['details'])>2:
        raise ValueError('Invalid range typing envelope')
    bound=deepcopy(value);bound['details']=[];ranges=[];seen=set()
    for row in value['details']:
        if not isinstance(row,dict) or set(row)!={'id','kind','source_id','first','last'}:
            raise ValueError('Only range IDs may declare a detail')
        sid=row['source_id']
        if sid not in members:raise ValueError('Detail source is not a member')
        selection={'first':row['first'],'last':row['last']}
        span=positional_support.bind(members[sid],[selection],prefix(sid,members[sid]))
        key=(sid,span['start'],span['end'])
        if key in seen:raise ValueError('Duplicate detail range')
        seen.add(key)
        if not span['text'].strip() or len(span['text'])>500:raise ValueError('Detail range length budget exceeded')
        bound['details'].append({k:row[k] for k in ('id','kind','source_id')}|{'quote':span['text']})
        ranges.append({'detail_id':row['id'],'source_id':sid,**span})
    result=legacy.apply(proposal,bound,members)
    result['typing_request_sha256']=digest(invocation(proposal['claims']['C'],members))
    result['typing_version']=VERSION;result['selected_ranges']=ranges
    return result
