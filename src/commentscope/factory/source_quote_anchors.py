"""Exact copied quotes to immutable source addresses; no fuzzy repair or meaning."""
from copy import deepcopy

VERSION='source-exact-quote-anchors-20261112-v3'
TYPING=('speech_act','kind','epistemic','assertion_mode')


def anchor_schema(*,scope=False,reference=False,wire=False):
    from commentscope.contracts.perspective_draft import obj
    value=dict(quote={'type':'string','minLength':1},occurrence={'type':'integer'})
    if scope:value['origin']={'type':'string','enum':['unit','source',*(['parent'] if reference else [])]}
    if wire:value={dict(quote='q',occurrence='n',origin='o')[k]:v for k,v in value.items()}
    return obj(value)


def matches(env,quote,origin,own):
    source=env['source'];sid=source['id'];text=source['text']
    if origin=='parent':
        if not source.get('parent'):raise ValueError('Parent quote has no bound parent')
        sid=source['parent']['id'];text=source['parent']['text'];ranges=[(0,len(text))]
    elif origin=='unit':
        if not own:raise ValueError('Local scope needs bound unit spans')
        ranges=[(r['start'],r['end']) for r in own if r['source_id']==sid]
    elif origin=='source':ranges=[(0,len(text))]
    else:raise ValueError('Unknown quote search origin')
    found=set()
    for lower,upper in ranges:
        i=text.find(quote,lower,upper)
        while i!=-1:
            found.add((i,i+len(quote)));i=text.find(quote,i+1,upper)
    return [dict(source_id=sid,start=i,end=j) for i,j in sorted(found)]


def resolve(env,anchor,*,own=None,reference=False):
    from commentscope.factory import source_evidence_graph as g
    g.validate_envelope(env);g.check(anchor_schema(scope=own is not None,reference=reference),anchor)
    if own is not None:g.spans(env,own)
    found=matches(env,anchor['quote'],anchor.get('origin','source'),own)
    if anchor['occurrence']>=len(found):raise ValueError('Exact quote occurrence not present; no text repair')
    return found[anchor['occurrence']]


def address(env,ref,*,own=None,reference=False):
    """Encode authored canonical annotations, never assert a model call happened."""
    from commentscope.factory import source_evidence_graph as g
    g.spans(env,[ref],context=reference);source=env['source'];origin='source';text=source['text']
    if ref['source_id']!=source['id']:
        origin='parent';text=source['parent']['text']
    elif own is not None and any(r['start']<=ref['start'] and ref['end']<=r['end'] for r in own):origin='unit'
    quote=text[ref['start']:ref['end']];found=matches(env,quote,origin,own)
    result=dict(quote=quote,occurrence=found.index(ref))
    if own is not None:result['origin']=origin
    return result


def schema(canonical):
    from commentscope.contracts.perspective_draft import obj,array
    value=deepcopy(canonical);unit=value['properties']['units']['items'];props=unit['properties'];props.pop('envelope_spans');unit['required'].remove('envelope_spans')
    props['own_spans']=array(anchor_schema(wire=True),minimum=1,maximum=8)
    for key in list(props['scope']['properties']):
        if key.endswith('_refs'):props['scope']['properties'][key]=array(anchor_schema(scope=True,reference=key=='referent_refs',wire=True),maximum=16)
    typing={k:props.pop(k) for k in TYPING};unit['required']=[k for k in unit['required'] if k not in TYPING]+['typing']
    branches=[]
    for nonpropositional in (False,True):
        branch=deepcopy(typing)
        if nonpropositional:
            branch['kind']['enum']=['not_applicable'];branch['speech_act']['enum']=['question','other']
            branch['assertion_mode']['enum'].remove('assertion')
        else:
            branch['kind']['enum'].remove('not_applicable');branch['epistemic']['enum'].remove('not_applicable');branch['assertion_mode']['enum'].remove('non_assertive')
        branches.append(obj(branch))
    props['typing']={'anyOf':branches}
    value['properties']['edges']['items']['properties']['cue_refs']=array(anchor_schema(wire=True),maximum=16)
    value['properties']['coverage']['items']['properties']['span']={'anyOf':[anchor_schema(wire=True),obj({'whole_source':{'type':'string','enum':['own']}})]}
    value['properties']['issues']['items']['properties']['evidence_refs']=array(anchor_schema(wire=True),maximum=16)
    return value


def compact(anchor):return {dict(quote='q',occurrence='n',origin='o')[k]:v for k,v in anchor.items()}


def expand(anchor):return {dict(q='quote',n='occurrence',o='origin')[k]:v for k,v in anchor.items()}


def encode(env,canonical):
    from commentscope.factory import source_evidence_graph as g
    value=deepcopy(canonical)
    for unit in value['units']:
        own=unit['own_spans'];unit.pop('envelope_spans');unit['typing']={k:unit.pop(k) for k in TYPING}
        for key in g.SCOPE_REFS:unit['scope'][key]=[compact(address(env,r,own=own,reference=key=='referent_refs')) for r in unit['scope'][key]]
        unit['own_spans']=[compact(address(env,r)) for r in own]
    for edge in value['edges']:edge['cue_refs']=[compact(address(env,r)) for r in edge['cue_refs']]
    for row in value['coverage']:
        ref=row['span'];row['span']=({'whole_source':'own'} if ref==dict(source_id=env['source']['id'],start=0,end=len(env['source']['text'])) else compact(address(env,ref)))
    for issue in value['issues']:issue['evidence_refs']=[compact(address(env,r)) for r in issue['evidence_refs']]
    return value


def decode(env,wire):
    from commentscope.factory import source_evidence_graph as g
    value=deepcopy(wire);full=dict(source_id=env['source']['id'],start=0,end=len(env['source']['text']))
    for unit in value['units']:
        own=[resolve(env,expand(r)) for r in unit['own_spans']];unit['own_spans']=own;unit['envelope_spans']=[deepcopy(full)];unit.update(unit.pop('typing'))
        for key in g.SCOPE_REFS:unit['scope'][key]=[resolve(env,expand(r),own=own,reference=key=='referent_refs') for r in unit['scope'][key]]
    for edge in value['edges']:edge['cue_refs']=[resolve(env,expand(r)) for r in edge['cue_refs']]
    for row in value['coverage']:row['span']=deepcopy(full) if row['span']=={'whole_source':'own'} else resolve(env,expand(row['span']))
    for issue in value['issues']:issue['evidence_refs']=[resolve(env,expand(r)) for r in issue['evidence_refs']]
    return value
