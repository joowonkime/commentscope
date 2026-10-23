"""Directional entailment of a common core by a fixed, own statement node.

Only a complete, unquoted, unconditional source frame is eligible here. This
does not replace whole-original membership, ownership/audits or external fact
checks. A stronger source can entail a weaker core without claiming that the
source author was uncertain. Missing scope never becomes a positive proof.
"""
from copy import deepcopy
from commentscope.factory import explicit_discourse as ed,minimal_claims as mc,nli_fact_records
from commentscope.factory import shared_owned_positions
from commentscope.factory.automatic_contract import digest
from commentscope.providers import evidence_nli

VERSION='fixed-own-node-directional-nli-20261023-v1'


def guards(graph,node,candidate,metadata,*,named_target=None):
    from commentscope.factory import owned_arguments as oa
    ed.validate(graph);mc.validate_candidate(candidate)
    if node not in graph['nodes']:raise ValueError('Exact immutable own node required')
    oa.validate_metadata(graph,node,metadata)
    reasons=[]
    if named_target is not None:
        from commentscope.factory import policy_target
        policy_target.validate(graph,node,candidate,named_target)
        if not named_target['passed']:reasons.append('own_named_policy_reference_unbound')
    if graph['holds']:reasons.append('source_syntax_unresolved')
    if node['kind']!='statement':reasons.append('not_own_statement')
    if metadata['output']['authorship']!='asserted_or_endorsed':reasons.append('own_authorship_unproved')
    if metadata['output']['kind']=='uncertain':reasons.append('source_node_type_unresolved')
    if metadata['output']['time_ids']:reasons.append('time_scope_needs_separate_proof')
    if metadata['assertion_mode']!='assertion':reasons.append('nonassertion_source_node')
    if shared_owned_positions.condition_inventory(graph,node):reasons.append('essential_condition_needs_separate_scope_proof')
    if any(q['start']<node['span']['end'] and node['span']['start']<q['end'] for q in graph['quotation_ranges']):
        reasons.append('quoted_span_needs_separate_authorship_proof')
    if 'meaning_context' in candidate:reasons.append('contextual_core_needs_reference_proof')
    return reasons


def case(graph,node,candidate):
    return {'id':'OWN'+digest([VERSION,graph['source']['id'],node['id'],candidate['id']]),
        'text':candidate['text'],'evidence':[{'id':node['id'],'text':node['span']['text']}]}


def invocation(jobs):
    cases=[];seen=set()
    for job in jobs:
        graph,node,candidate,metadata=(job[k] for k in ['graph','node','candidate','metadata'])
        if guards(graph,node,candidate,metadata,named_target=job.get('named_target')):continue
        row=case(graph,node,candidate)
        if row['id'] in seen:raise ValueError('Duplicate own-node comparison')
        seen.add(row['id']);cases.append(row)
    return {'system':evidence_nli.VERSION,'schema':{},'max_tokens':1,'data':{'cases':cases}}


def bind(graph,node,candidate,metadata,comparison,*,named_target=None):
    reasons=guards(graph,node,candidate,metadata,named_target=named_target)
    if reasons:
        if comparison is not None:raise ValueError('An ineligible scope cannot receive an entailment approval')
    else:
        expected=case(graph,node,candidate)
        if (not isinstance(comparison,dict) or set(comparison)!={'case','result','metadata','batch_request_sha256'} or
                comparison['case']!=expected):raise ValueError('Exact own-node/core comparison required')
        key=comparison['batch_request_sha256']
        if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Actual comparison batch identity required')
        nli_fact_records.validate_result(comparison['result'],expected,comparison['metadata'])
        if any(not p['errors'] and (type(p.get('input_tokens')) is not int or
                not 1<=p['input_tokens']<=512) for p in comparison['result']['pairs']):
            raise ValueError('Untruncated own-node comparison token boundary exceeded')
        if comparison['result']['state']!='supported':reasons.append('own_node_entailment_unproved')
    result={'artifact_kind':VERSION,'graph_sha256':digest(graph),'node_id':node['id'],
        'candidate_sha256':digest(candidate),'source_metadata':deepcopy(metadata),'comparison':deepcopy(comparison),
        'relation':'not_proved' if reasons else 'supports_core','guards':reasons,
        'semantic_approval':False,'factual_verification':False}
    if named_target is not None:result['named_target']=deepcopy(named_target)
    return result


def records(jobs,response):
    request=invocation(jobs);cases=request['data']['cases']
    if cases:
        if (not isinstance(response,dict) or [r['id'] for r in response['results']]!=[c['id'] for c in cases] or
                response['forward_pairs']!=len(cases)):raise ValueError('Complete actual own-node comparison required')
        lookup={c['id']:{'case':c,'result':r,'metadata':response['metadata'],'batch_request_sha256':digest(request)}
            for c,r in zip(cases,response['results'],strict=True)}
    else:
        if response is not None:raise ValueError('No eligible own nodes require no classifier invocation')
        lookup={}
    return [bind(j['graph'],j['node'],j['candidate'],j['metadata'],
        lookup.get(case(j['graph'],j['node'],j['candidate'])['id']),named_target=j.get('named_target')) for j in jobs]


def validate(graph,node,candidate,record):
    if bind(graph,node,candidate,record['source_metadata'],record['comparison'],named_target=record.get('named_target'))!=record:
        raise ValueError('Directional own-node ownership changed')
    return record
