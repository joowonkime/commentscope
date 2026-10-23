"""Enumerate valid source ranges and encode factual dependency consistency.

This restricts syntax and provenance, not the model's semantic interpretation.
The host never trims selected text or changes the model's declared type.
"""
import json

from commentscope.contracts.perspective_draft import obj,array
from commentscope.factory import perspective_typing as legacy, span_typing
from commentscope.factory.automatic_contract import digest

VERSION='bounded-source-range-typing-0.1'
SYSTEM=legacy.SYSTEM.replace(
    'using exact complete source\nquotes.',
    'by selecting range_id from the allowed enum. A range_id is SOURCE_PREFIX:first:last, '
    'with zero-based inclusive sentence indexes. MEMBER_SOURCES preserves the full source. '
    'Never write quotation text. The host copies the selected original range.')
SYSTEM=SYSTEM.replace('required_fact_ids identify empirical premises whose failure defeats the core as\nworded,',
    'Set required_fact=true on an empirical reason whose failure defeats the core as worded,')
SYSTEM=SYSTEM.replace('or relabel them as values/forecasts to avoid checking.',
    'or relabel them as values/forecasts to avoid checking. Non-empirical reasons must use required_fact=false.')


def inventory(sources):
    original=span_typing.inventory(sources);ranges={};context={}
    for sid,parts in original.items():
        if len(parts)>128:raise ValueError('Source sentence budget exceeded')
        prefix=span_typing.prefix(sid,sources[sid])[:-1]
        if prefix in context:raise ValueError('Source identity collision')
        context[prefix]={'source_id':sid,'sentences':[{'index':i,'text':p['text']} for i,p in enumerate(parts)]}
        for first,left in enumerate(parts):
            for last in range(first,len(parts)):
                right=parts[last];text=sources[sid][left['start']:right['end']]
                if len(text)>500:break
                if not text.strip():continue
                rid=f'{prefix}:{first}:{last}'
                ranges[rid]={'source_id':sid,'source_digest':digest(sources[sid]),
                    'first':left['id'],'last':right['id'],'start':left['start'],'end':right['end'],'text':text}
                if len(ranges)>1000:raise ValueError('Selectable range budget exceeded')
    return context,ranges


def invocation(claim,sources):
    context,ranges=inventory(sources)
    ref={'$ref':'#/$defs/range_id'}
    detail={'anyOf':[
        obj({'range_id':ref,'kind':{'type':'string','const':'empirical_description'},'required_fact':{'type':'boolean'}}),
        obj({'range_id':ref,'kind':{'type':'string','enum':['normative_preference','future_expectation']},
             'required_fact':{'type':'boolean','const':False}})]}
    details=array(detail,maximum=2) if ranges else {'type':'array','maxItems':0,'items':{'type':'null'}}
    schema={'anyOf':[obj({'status':{'type':'string','const':'defer'},
                         'reason':{'type':'string','enum':['non_substantive','mixed_or_unclear','essential_grounds_overflow']}}),
        obj({'status':{'type':'string','const':'classified'},'kind':{'type':'string','enum':list(legacy.KINDS)},'details':details})]}
    if ranges:schema['$defs']={'range_id':{'type':'string','enum':list(ranges)}}
    req={'system':SYSTEM+'\nRequired schema:\n'+json.dumps(schema),
         'data':{'CORE':claim['text'],'MEMBER_SOURCES':context},'schema':schema,'max_tokens':650}
    if len(json.dumps(req).encode())>27000:raise ValueError('Typing request byte budget exceeded')
    return req


def apply(proposal,value,members):
    if not isinstance(value,dict):raise ValueError('Invalid typing envelope')
    if value.get('status')=='defer':return legacy.apply(proposal,value,members)
    if (set(value)!={'status','kind','details'} or value['status']!='classified'
            or not isinstance(value['details'],list) or len(value['details'])>2):
        raise ValueError('Invalid bounded typing envelope')
    _,allowed=inventory(members);details=[];required=[];selected=[];seen=set()
    for i,row in enumerate(value['details'],1):
        if (not isinstance(row,dict) or set(row)!={'range_id','kind','required_fact'}
                or row['kind'] not in legacy.KINDS or type(row['required_fact']) is not bool):
            raise ValueError('Invalid detail decision')
        rid=row['range_id']
        if not isinstance(rid,str) or rid not in allowed or rid in seen:raise ValueError('Unknown or duplicate range')
        if row['required_fact'] and row['kind']!='empirical_description':raise ValueError('Required reason must be empirical')
        seen.add(rid);span=allowed[rid];did=f'D{i}'
        details.append({'id':did,'kind':row['kind'],'source_id':span['source_id'],'quote':span['text']})
        if row['required_fact']:required.append(did)
        selected.append({'detail_id':did,'range_id':rid,**span})
    result=legacy.apply(proposal,{'status':'classified','kind':value['kind'],'details':details,'required_fact_ids':required},members)
    result.update(typing_version=VERSION,typing_request_sha256=digest(invocation(proposal['claims']['C'],members)),selected_ranges=selected)
    return result
