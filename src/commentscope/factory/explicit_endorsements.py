"""Exact whole-proposition endorsement, with own-only speech-act comparison.

All sources are scanned before inference. Candidates retain complete normative
parent originals; no model proposal is repaired. A child supplies an explicit
agreement act, never its parent's rationale. Parent identity is a separate code
binding, not an extra comparator premise or another vote.
"""
from copy import deepcopy
import re
from commentscope.factory import minimal_claims as mc,explicit_discourse as ed
from commentscope.factory import source_entailment as se,owned_arguments as oa
from commentscope.factory.automatic_contract import digest
from commentscope.providers import evidence_nli

VERSION='exact-whole-proposition-endorsements-20261023-v1'
AGREE=re.compile(r'^(?:agreed|(?:I\s+)?(?:(?:totally|completely|fully|wholeheartedly)\s+)?agree(?:\s+with\s+(?:you|this|that))?)[.!\s]*$',re.I)
NORMATIVE=re.compile(r'\b(?:should|ought|must)\b',re.I)

def eligible_parent(source,topic,alias):
    mc.validate_source(source);text=source['text'];quotes,issues=ed.quotation_ranges(text)
    named=re.search(r'(?<!\w)(?:'+re.escape(topic)+'|'+re.escape(alias)+r')(?!\w)',text,re.I)
    parts=ed.statements(text,quotes)
    return bool(named and NORMATIVE.search(text) and len(text)<=600 and not quotes and not issues
        and len(parts)==1 and not text.rstrip().endswith('?') and not ed.operators(text,parts[0],quotes))

def inventory(sources,topic,alias):
    ss=mc.source_index(sources);groups=[]
    for pid,parent in sorted(ss.items()):
        if not eligible_parent(parent,topic,alias):continue
        children=[s for sid,s in sorted(ss.items()) if sid!=pid and s['parent'] is not None
            and s['parent']['id']==pid and s['parent']['text']==parent['text'] and AGREE.fullmatch(s['text'].strip())]
        if len(children)>=2:
            groups.append({'artifact_kind':VERSION+'-group','topic':topic,'alias':alias,
                           'parent':deepcopy(parent),'children':deepcopy(children)})
    return {'artifact_kind':VERSION+'-inventory','source_ids':sorted(ss),'sources_sha256':digest(sources),
            'groups':groups,'semantic_approval':False,'model_response_fabricated':False}

def validate_group(group):
    sources=[group['parent'],*group['children']]
    rebuilt=inventory(sources,group['topic'],group['alias'])['groups']
    if len(rebuilt)!=1 or rebuilt[0]!=group:raise ValueError('Exact complete normative parent/explicit reply binding required')
    return group

def candidate(group):
    validate_group(group);text=mc.normalize(group['parent']['text']);cid=mc.claim_id(text)
    return mc.validate_candidate({'id':cid,'text':text,'aliases':[cid],
        'nominees':{s['id']:digest(s) for s in [group['parent'],*group['children']]},
        'extraction_refs':[digest(group)],'equivalence_refs':[]})

def invocation(group):
    validate_group(group);c=candidate(group);pid=group['parent']['id']
    return {'system':evidence_nli.VERSION,'schema':{},'max_tokens':1,'data':{'cases':[
        {'id':'EP'+digest([VERSION,s['id'],c['id']]),
         'text':c['text'] if s['id']==pid else 'I agree.',
         'evidence':[{'id':s['id'],'text':s['text']}]} for s in [group['parent'],*group['children']]]}}

def bind_batch(group,request,response,selected_source_ids=None):
    if request!=invocation(group):raise ValueError('Actual own-only endorsement comparison request changed')
    c=candidate(group);sources=[group['parent'],*group['children']];ss=mc.source_index(sources)
    selected=sorted(ss) if selected_source_ids is None else selected_source_ids
    if not isinstance(selected,list) or not selected or selected!=sorted(set(selected)) or not set(selected)<=set(ss):
        raise ValueError('Exact explicit projection of completed source cases required')
    compared=se._completed_comparisons(request,response);rows=[]
    for case in request['data']['cases']:
        proof=compared[case['id']];sid=case['evidence'][0]['id'];source=ss[sid]
        if proof['case']!=case:raise ValueError('Endorsement comparator evidence changed')
        if any(not p['errors'] and (type(p.get('input_tokens')) is not int or not 1<=p['input_tokens']<=512)
               for p in proof['result']['pairs']):raise ValueError('Untruncated own-source comparator required')
        if sid not in selected:continue
        passed=proof['result']['state']=='supported'
        binding={'kind':'own_complete_parent_position' if sid==group['parent']['id'] else 'explicit_agreement_to_exact_parent',
                 'parent_source_sha256':digest(group['parent']),'whole_parent_text_sha256':digest(c['text']),
                 'own_source_sha256':digest(source),'parent_rationale_transferred':False}
        rows.append({'artifact_kind':VERSION,'source_id':sid,'candidate_id':c['id'],
            'source_sha256':digest(source),'candidate_text_sha256':digest(c['text']),
            'request_sha256':digest(request),'proof_sha256':digest([proof,binding]),
            'relation':'supported' if passed else 'uncertain','guards':[] if passed else ['own_speech_act_or_position_unproved'],
            'evidence':mc.validate_source(source),'reference_binding':binding,'semantic_approval':False})
    return {'artifact_kind':VERSION+'-batch','sources':deepcopy(sources),'candidates':[c],
        'group':deepcopy(group),'completed_request':deepcopy(request),'completed_response':deepcopy(response),
        'selected_source_ids':deepcopy(selected),'memberships':rows,'model_response_fabricated':False,
        'parent_text_used_as_comparator_premise_for_child':False,'quality_gate_passed':False}

def validate_batch(batch):
    if bind_batch(batch['group'],batch['completed_request'],batch['completed_response'],batch['selected_source_ids'])!=batch:
        raise ValueError('Endorsement source/target/actual comparator/reference binding changed')
    return batch['memberships']

def declare(group,batch,core,parent_metadata,source_id):
    from commentscope.factory import source_arguments as sa
    validate_group(group);rows=validate_batch(batch);c=candidate(group);sa.validate_core(core)
    parent=group['parent'];graph=ed.parse(parent)
    if len(graph['nodes'])!=1 or graph['nodes'][0]['kind']!='statement' or graph['holds']:
        raise ValueError('Complete one-position parent syntax required')
    oa.validate_metadata(graph,graph['nodes'][0],parent_metadata)
    if (core['candidate']!=c or core['output']['kind']!='value' or core.get('hold_reasons')
            or parent_metadata['output']['kind']!='value' or parent_metadata['output']['source_language']!='en'
            or parent_metadata['output']['authorship']!='asserted_or_endorsed'):
        raise ValueError('Complete normative parent must be independently typed and attributed')
    if batch['group']!=group or batch['selected_source_ids']!=[source_id] or len(rows)!=1:
        raise ValueError('One exact own source projection per argument declaration')
    source=next(s for s in batch['sources'] if s['id']==source_id)
    # The entire parent position is already the complete core. The child adds
    # only its own literal agreement, not another source's personal rationale.
    return {'artifact_kind':VERSION+'-arguments','source':deepcopy(source),'candidate_ids':[c['id']],
        'source_language':'en','status':'complete' if rows[0]['relation']=='supported' else 'unresolved',
        'units':[],'additional_passes':0,'batch_candidates':[c],'support_batches':[deepcopy(batch)],
        'group':deepcopy(group),'core':deepcopy(core),'parent_metadata':deepcopy(parent_metadata),
        'origin':'exact_complete_position_or_explicit_endorsement_without_own_additional_arguments',
        'parent_rationale_transferred':False,'semantic_approval':False}

def validate_arguments(record):
    if declare(record['group'],record['support_batches'][0],record['core'],record['parent_metadata'],record['source']['id'])!=record:
        raise ValueError('Explicit endorsement argument completeness/reference proof changed')
    return record
