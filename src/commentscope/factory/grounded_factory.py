"""Automatic proposal/membership to grounded bundle adapter; never reads labels.

All declared factual dependencies survive compilation. Missing verification
defers a dependent perspective instead of inventing replacement arguments.
"""
from copy import deepcopy
from commentscope.factory import fact_checks as facts, scoped_discovery as discovery
from commentscope.factory.automatic_contract import digest


def global_claims(proposal):
    prefix=proposal['id']+':'
    return {key:{**deepcopy(value),'id':prefix+key,'requires':[prefix+r for r in value['requires']]}
            for key,value in proposal['claims'].items()}


def relation(claim,sid,text,verdict,trace_id):
    if verdict not in {'supported','partial','unsupported','unclear','error','unassessed'}:
        raise ValueError('Invalid source verdict')
    return {'claim_id':claim['id'],'claim_sha256':facts.claim_identity(claim),
            'source_id':sid,'source_sha256':digest(text),
            'span':{'start':0,'end':len(text),'text':text},'verdict':verdict,
            'trace_id':trace_id,'origin':'local_model'}


def detail_requests(proposals,core_rows,core_verdicts):
    requests=[]
    for proposal in proposals:
        members={r['source_id'] for r in core_rows if r['candidate_id']==proposal['id'] and core_verdicts[r['id']]=='supported'}
        if len(members)<3: continue
        for key,claim in sorted(global_claims(proposal).items()):
            if key=='C':continue
            for sid in sorted(members):
                text=proposal['sources'][sid]; req=discovery.judge_request(text,claim)
                requests.append({'id':f'D{len(requests)+1:04}','candidate_id':proposal['id'],
                                 'source_id':sid,'claim':claim,'text':text,
                                 'request':req,'request_sha256':digest(req)})
    return requests


def bundle(proposals,core_rows,core_verdicts,detail_rows,detail_verdicts,*,expires_at,model,documents=(),checks=()):
    sources={};claims=[];relations=[];candidates=[]
    for proposal in proposals:
        mapped=global_claims(proposal); claims.extend(mapped.values())
        for sid,text in proposal['sources'].items():
            if sid in sources and sources[sid]['text']!=text: raise ValueError('Source identity collision')
            sources[sid]={'id':sid,'canonical_id':sid,'text':text}
        declared={'C',*([key for key in ['R1','R2'] if key in mapped])}
        def gather(key):
            for dep in proposal['claims'][key]['requires']:
                if dep not in declared: declared.add(dep);gather(dep)
        for key in list(declared):gather(key)
        candidates.append({'id':proposal['id'],'core_claim_id':mapped['C']['id'],
                           'reason_claim_ids':[mapped[key]['id'] for key in ['R1','R2'] if key in mapped],
                           'major_fact_ids':[mapped[key]['id'] for key in sorted(declared) if mapped[key]['kind']=='fact']})
        for row in core_rows:
            if row['candidate_id']==proposal['id']:
                if row['claim']!=proposal['claims']['C'] or row['text']!=sources[row['source_id']]['text']:
                    raise ValueError('Core request identity changed')
                relations.append(relation(mapped['C'],row['source_id'],row['text'],core_verdicts[row['id']],row['request_sha256']))
    for row in detail_rows:
        if row['text']!=sources[row['source_id']]['text']: raise ValueError('Detail source changed')
        relations.append(relation(row['claim'],row['source_id'],row['text'],detail_verdicts[row['id']],row['request_sha256']))
    return {'expires_at':expires_at,'sources':list(sources.values()),'claims':claims,'relations':relations,
            'documents':deepcopy(list(documents)),'checks':deepcopy(list(checks)),
            'candidates':candidates,'model':deepcopy(model)}


def fact_packets(bundle, selections):
    # A small configured evidence library is not universal web search. Missing
    # material remains unassessed/insufficient and cannot be inferred from votes.
    return [facts.packet(c,bundle['documents'],selections,bundle['expires_at']) for c in bundle['claims'] if c['kind']=='fact']
