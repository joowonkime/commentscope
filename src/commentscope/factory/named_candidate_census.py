"""Automatic lexical nominations for completed, unapproved common hypotheses.

Ranking reads only originals, never parents or review labels. It is retrieval,
not a verdict: unselected pairs stay unassessed. Actual whole-source comparison
receipts supply nominations; all membership/ownership/fact gates run afterwards.
"""
from collections import Counter
from copy import deepcopy
import math
import re

from commentscope.factory import minimal_claims as mc,policy_target,explicit_discourse as ed
from commentscope.factory import source_entailment as se
from commentscope.factory.automatic_contract import digest
from commentscope.providers import evidence_nli

VERSION='named-common-lexical-census-20261023-v1'
UNNAMED='self-contained-common-lexical-census-20261023-v1'
STOP=set('a an the and or but to of in on at for with by from is are was were be been being it its this that these those i me my we our you your they their have has had do does did not would could can will should may might as than then if so even also about'.split())


def tokens(text):
    return [t for t in re.findall(r"[a-z]+(?:'[a-z]+)?",text.lower()) if t not in STOP]


def ranking(sources,proposals,topic,alias,*,limit=32,remaining_unnamed=False):
    ss=mc.source_index(sources)
    if type(limit) is not int or not 3<=limit<=100:raise ValueError('Frozen retrieval limit3..100 required')
    docs={sid:Counter(tokens(s['text'])) for sid,s in ss.items()};df=Counter()
    for doc in docs.values():df.update(doc.keys())
    average=sum(sum(d.values()) for d in docs.values())/len(docs)
    eligible={}
    for sid,source in ss.items():
        graph=ed.parse(source);reasons=[]
        if graph['holds']:reasons.append('source_syntax_unresolved')
        if not any(n['kind']=='statement' for n in graph['nodes']):reasons.append('no_fixed_statement')
        if any(len(n['span']['text'])>600 for n in graph['nodes']):reasons.append('literal_node_exceeds_claim_capacity')
        if not remaining_unnamed and not policy_target.anchors(source,topic,alias):reasons.append('own_named_policy_reference_unbound')
        eligible[sid]=reasons
    cs={c['id']:mc.validate_candidate(c) for c in proposals}
    if len(cs)!=len(proposals):raise ValueError('Duplicate common hypothesis')
    rows=[]
    for cid,candidate in sorted(cs.items()):
        named=bool(policy_target.anchors({**sources[0],'text':candidate['text']},topic,alias))
        query=set(tokens(candidate['text']))
        def score(sid):
            doc=docs[sid];length=sum(doc.values());value=0.0
            for term in sorted(query):
                freq=doc[term]
                if freq:
                    weight=math.log(1+(len(docs)-df[term]+.5)/(df[term]+.5))
                    value+=weight*freq*2.2/(freq+1.2*(.25+.75*length/max(average,1)))
            return value
        ordered=sorted(ss,key=lambda sid:(-score(sid),sid))
        selected=named if not remaining_unnamed else not named
        chosen=[sid for sid in ordered if not eligible[sid]][:limit] if selected else []
        rows.append({'candidate_id':cid,'candidate_sha256':digest(candidate),'named_policy':named,
            'selected_source_ids':chosen,'unselected_pair_status':'unassessed_not_rejected'})
    return {'artifact_kind':(UNNAMED if remaining_unnamed else VERSION)+'-ranking','sources':deepcopy(sources),'proposals':deepcopy(proposals),
        'topic':topic,'alias':alias,'limit':limit,'source_holds':eligible,'rows':rows,
        'semantic_approval':False,'parent_text_used_for_ranking':False}


def validate_ranking(record):
    if ranking(record['sources'],record['proposals'],record['topic'],record['alias'],limit=record['limit'],
            remaining_unnamed=record['artifact_kind']==UNNAMED+'-ranking')!=record:
        raise ValueError('Frozen automatic retrieval changed')
    return record


def invocation(record):
    validate_ranking(record);ss=mc.source_index(record['sources']);cs={c['id']:c for c in record['proposals']}
    return {'system':evidence_nli.VERSION,'schema':{},'max_tokens':1,'data':{'cases':[
        {'id':'SP'+digest([sid,row['candidate_id']]),'text':cs[row['candidate_id']]['text'],
         'evidence':[{'id':sid,'text':ss[sid]['text']}]} for row in record['rows'] for sid in row['selected_source_ids']]}}


def bind(ranked,completed_batches):
    expected=invocation(ranked)['data']['cases'];actual={}
    for request,response in completed_batches:
        for key,proof in se._completed_comparisons(request,response).items():
            if key in actual:raise ValueError('Duplicate actual comparison')
            actual[key]=proof
    if set(actual)!={c['id'] for c in expected} or any(actual[c['id']]['case']!=c for c in expected):
        raise ValueError('All and only frozen retrieved pairs need exact completed comparisons')
    return {'artifact_kind':UNNAMED if ranked['artifact_kind']==UNNAMED+'-ranking' else VERSION,'sources':deepcopy(ranked['sources']),'topic':ranked['topic'],
        'alias':ranked['alias'],'ranking':deepcopy(ranked),'completed_batches':deepcopy(completed_batches),
        'semantic_approval':False,'synthetic_joint_request':False}


def validate(record):
    if bind(record['ranking'],record['completed_batches'])!=record:raise ValueError('Common census provenance changed')
    return record


def candidates(record):
    validate(record);ss=mc.source_index(record['sources']);compared={}
    for request,response in record['completed_batches']:compared.update(se._completed_comparisons(request,response))
    out=[]
    for proposal in record['ranking']['proposals']:
        cid=proposal['id'];nominees={sid:digest(s) for sid,s in ss.items()
            if (proof:=compared.get('SP'+digest([sid,cid]))) is not None and proof['result']['state']=='supported'}
        if nominees:
            out.append(mc.validate_candidate({**deepcopy(proposal),'nominees':nominees,
                'extraction_refs':sorted(set([*proposal['extraction_refs'],digest(record)]))}))
    return sorted(out,key=lambda c:c['id'])
