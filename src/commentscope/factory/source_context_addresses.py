"""Exact token endpoints for local, prior and forward interpretation context.

The inventory is linear in the originals. It does not enumerate word windows,
rewrite assertions, parse grammatical roles or certify semantic coreference.
"""
from copy import deepcopy
import re

from commentscope.contracts.perspective_draft import obj
from commentscope.factory import explicit_discourse as ed, literal_discovery as ld
from commentscope.factory import source_scope as ss, minimal_claims as mc
from commentscope.factory.automatic_contract import digest
from commentscope.factory.position_frames import fields

LEGACY='source-context-addresses-20261017-v1'
VERSION='source-context-addresses-20261017-v2'


def origins(source):
    mc.source_index([source]);rows={'source':source['text']}
    if source['parent']:rows['parent']=source['parent']['text']
    if source.get('video_context'):rows['video_title']=source['video_context']['title']
    return rows


def inventory(source):
    rows=[]
    for origin,text in origins(source).items():
        quotes,_=ed.quotation_ranges(text);sentences=ed.statements(text,quotes)
        for match in ss.WORDS.finditer(text):
            if not re.search(r'\w',match.group()):continue
            part=ed.span(text,match.start(),match.end())
            sentence=next((i for i,s in enumerate(sentences)
                           if s['start']<=part['start'] and part['end']<=s['end']),None)
            if sentence is None:raise ValueError('Token has no original sentence address')
            rows.append({'id':f'T{len(rows)+1}','origin':origin,'span':part,'sentence_index':sentence})
    return rows


def regions(source):
    """Partition at original sentence and reference boundaries, without overlap."""
    tokens=inventory(source);result=[]
    for origin,text in origins(source).items():
        graph=ed.parse({'id':source['id']+':region:'+origin,'text':text,'parent':None})
        refs={}
        for node in graph['nodes']:
            scope=ss.inventory(graph,node)
            items=scope['references']+[s for s in scope['syntax'] if s['kind']=='quoted_reference_not_rewritten']
            for item in items:
                part=item['span'];refs[(part['start'],part['end'])]=part
        for sentence in graph['statements']:
            part=sentence['span'];cuts={part['start'],part['end']}
            for (a,b) in refs:
                if part['start']<=a and b<=part['end']:cuts.update((a,b))
            cuts=sorted(cuts)
            for a,b in zip(cuts,cuts[1:]):
                selected=[t for t in tokens if t['origin']==origin and a<=t['span']['start'] and t['span']['end']<=b]
                if not selected:continue
                result.append({'id':f'Z{len(result)+1}','origin':origin,
                    'span':ed.span(text,selected[0]['span']['start'],selected[-1]['span']['end']),
                    'token_ids':[t['id'] for t in selected],
                    'reference_span':deepcopy(refs.get((a,b)))})
    return result


def allowed_regions(source,expression):
    return [r['id'] for r in regions(source) if r['origin']!='source' or not
            (r['span']['start']<expression['end'] and expression['start']<r['span']['end'])]


def schema(source):
    rows=inventory(source);branches=[]
    for origin in origins(source):
        ids=[r['id'] for r in rows if r['origin']==origin]
        if ids:
            ref={'$ref':'#/$defs/context_tokens_'+origin}
            branches.append(obj({'first_token':ref,'last_token':ref}))
    return branches


def definitions(source,version=VERSION):
    if version==VERSION:
        result={}
        for region in regions(source):
            ids=region['token_ids'];key='context_region_'+region['id']
            if region['reference_span']:
                properties={'first_token':{'type':'string','const':ids[0]},
                            'last_token':{'type':'string','const':ids[-1]}}
            else:
                name='context_tokens_'+region['id'];result[name]={'type':'string','enum':ids}
                ref={'$ref':'#/$defs/'+name};properties={'first_token':ref,'last_token':ref}
            result[key]=obj(properties)
        return result
    if version!=LEGACY:raise ValueError('Unknown context address contract')
    rows=inventory(source)
    result={'context_tokens_'+origin:{'type':'string','enum':[r['id'] for r in rows if r['origin']==origin]}
            for origin in origins(source) if any(r['origin']==origin for r in rows)}
    result['context_span']={'anyOf':schema(source)}
    return result


def packet(source,version=VERSION):
    if version==VERSION:
        tokens={r['id']:r for r in inventory(source)}
        return [[r['id'],r['origin'],'whole_reference' if r['reference_span'] else 'span',
                 [[tid,tokens[tid]['span']['text']] for tid in r['token_ids']]] for r in regions(source)]
    if version!=LEGACY:raise ValueError('Unknown context address contract')
    return [[r['id'],r['origin'],r['span']['text']] for r in inventory(source)]


def bind(source,expression,selection,version=VERSION):
    """Bind one contiguous antecedent proposal; never accept its own trigger."""
    fields(selection,'first_token last_token');lookup={r['id']:r for r in inventory(source)}
    if any(not isinstance(v,str) or v not in lookup for v in selection.values()):
        raise ValueError('Unknown original context token')
    a,b=(lookup[selection[k]] for k in ('first_token','last_token'))
    if a['origin']!=b['origin'] or a['sentence_index']!=b['sentence_index']:
        raise ValueError('Context span must stay in one original origin and sentence')
    if a['span']['start']>b['span']['start']:raise ValueError('Reversed context token range')
    origin=a['origin'];start=a['span']['start'];end=b['span']['end']
    if source['text'][expression['start']:expression['end']]!=expression['text']:
        raise ValueError('Reference expression is not its source span')
    if origin=='source' and start<expression['end'] and expression['start']<end:
        raise ValueError('Reference cannot serve as its own antecedent')
    if version==VERSION:
        matches=[r for r in regions(source) if r['origin']==origin
                 and r['span']['start']<=start and end<=r['span']['end']]
        if len(matches)!=1:raise ValueError('Context span crosses an original reference boundary')
        region=matches[0]
        if region['reference_span'] and (start,end)!=(region['span']['start'],region['span']['end']):
            raise ValueError('Original reference phrase must be retained completely')
    elif version!=LEGACY:raise ValueError('Unknown context address contract')
    part=ed.span(origins(source)[origin],start,end)
    # Keep the existing unresolved-dependency boundary for selected subspans.
    # A new endpoint address must not be a shortcut around nested-reference holds.
    graph=ed.parse({'id':source['id']+':context:'+origin,'text':part['text'],'parent':None})
    scopes=[ss.inventory(graph,n) for n in ld.roots(graph)]
    nested={'references':[r for s in scopes for r in s['references']],
            'answer_condition':any(s['answer_condition'] for s in scopes),
            'heading':any(s['heading'] for s in scopes)}
    return {'id':'TOKEN:'+digest([origin,part]),'origin':origin,'span':part,
            'node_id':None,'scope_inventory':nested,
            'address_contract':version,'token_selection':deepcopy(selection),
            'context_only':True,'semantic_coreference_verified':False}
