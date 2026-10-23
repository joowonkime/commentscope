"""Literal assertions with separately bound interpretation context.

The original assertion is never rewritten or joined to another assertion.
Context accompanies identity and every consumer; it does not become a shared
requirement, an author's evidence or an approved interpretation by being present.
"""
from copy import deepcopy
import re

from commentscope.factory import minimal_claims as mc, explicit_discourse as ed
from commentscope.factory import literal_discovery as ld, source_scope as ss
from commentscope.factory.automatic_contract import digest

VERSION = 'contextual-propositions-20261017-v1'
BUNDLE = VERSION+'-bundle'
INTERPRETED_VERSION = 'contextual-propositions-20261017-v2'
VERSIONS = (VERSION,INTERPRETED_VERSION)


def bundle(graph, node_id, setting_ids=()):
    ed.validate(graph);nodes={n['id']:n for n in ld.roots(graph)}
    if node_id not in nodes:raise ValueError('Only a fixed original assertion node can be nominated')
    if not isinstance(setting_ids,(list,tuple)) or len(setting_ids)!=len(set(setting_ids)):
        raise ValueError('Unique context setting nodes required')
    heading=ss.initial_heading(graph)
    if any(nid not in nodes or nodes[nid]['span']!=heading for nid in setting_ids):
        raise ValueError('Setting proposal must be an eligible original initial fragment')
    node=nodes[node_id]
    return {'artifact_kind':BUNDLE,'source':deepcopy(graph['source']),'graph_sha256':digest(graph),
            'node_id':node_id,'assertion':deepcopy(node['span']),
            'setting_node_ids':sorted(setting_ids),'scope_inventory':ss.inventory(graph,node),
            'owned_edges':[deepcopy(e) for e in graph['edges'] if e['parent_id']==node_id],
            'assertion_rewritten':False,'context_asserted_separately':False,'semantic_approval':False}


def validate_bundle(value):
    if (not isinstance(value,dict) or value.get('artifact_kind')!=BUNDLE
            or bundle(ed.parse(value['source']),value['node_id'],value['setting_node_ids'])!=value):
        raise ValueError('Literal assertion or its interpretation context changed')
    return value


def claim_id(value):
    validate_bundle(value)
    return 'CP'+digest([VERSION,value])


def packet(value):
    validate_bundle(value);graph=ed.parse(value['source']);source=value['source']
    # Full literal source context is preserved once; no enumeration of all word
    # windows, no inferred antecedent text, and no implicit context truncation.
    return {'assertion':deepcopy(value['assertion']),
            'INTERPRETATION_CONTEXT_ONLY':{
                'source_id':source['id'],'source_sha256':digest(source),
                'comment_text':source['text'],'assertion_node_id':value['node_id'],
                'PARENT_CONTEXT_ONLY':deepcopy(source['parent']),
                'VIDEO_CONTEXT_ONLY':deepcopy(source.get('video_context')),
                'setting_proposals':[deepcopy(n['span']) for n in graph['nodes'] if n['id'] in value['setting_node_ids']],
                'scope_inventory':deepcopy(value['scope_inventory'])},
            'OWNED_RELATIONS':[{'relation':e['relation'],
                'ground':deepcopy(next(n['span'] for n in graph['nodes'] if n['id']==e['ground_id']))}
                for e in value['owned_edges']],
            'context_is_not_an_asserted_conjunction':True,
            'interpretation_and_membership_unapproved':True}


def reference_only(text):
    return bool(re.fullmatch(r'\s*(?:this|that|these|those|it|they|them)[.!?\s]*',text,re.I))


def assemble(graph,batches):
    ed.validate(graph);nodes=ld.roots(graph);decisions={};refs={}
    for batch in batches:
        if ld.bind_selection(graph,batch['node_ids'],{'output':batch['response']})!=batch:
            raise ValueError('Contextual source selection changed')
        for row in batch['selections']:
            if row['node_id'] in decisions:raise ValueError('Duplicate assertion selection')
            decisions[row['node_id']]=row;refs[row['node_id']]=digest(batch)
    return _assemble(graph,decisions,refs,batches)


def assemble_interpreted(graph,interpretations):
    from commentscope.factory import contextual_interpretation as ci
    ed.validate(graph);nodes={n['id']:n for n in ld.roots(graph)};decisions={};refs={}
    for record in interpretations:
        nid=record['node_id']
        if nid not in nodes or nid in decisions:raise ValueError('Unique original position interpretation required')
        decisions[nid]=ci.decision(graph,nodes[nid],record);refs[nid]=digest(record)
    result=_assemble(graph,decisions,refs,[])
    result.update(artifact_kind=INTERPRETED_VERSION,interpretations=deepcopy(interpretations),
                  position_bundles=[bundle(graph,n['id']) for n in ld.roots(graph)])
    return result


def _assemble(graph,decisions,refs,batches):
    nodes=ld.roots(graph)
    heading=ss.initial_heading(graph)
    settings=[n['id'] for n in nodes if n['span']==heading and
              decisions.get(n['id'],{}).get('role')=='framing_context' and
              decisions.get(n['id'],{}).get('contribution')=='context']
    claims=[];holds=[];excluded=[]
    for node in nodes:
        row=decisions.get(node['id']);text=node['span']['text']
        if row is None:
            holds.append({'node_id':node['id'],'reason':'unassessed_position'});continue
        if row['contribution']=='non_substantive' or node['id'] in settings:
            excluded.append(node['id']);continue
        if row['contribution'] in ('context','uncertain'):
            holds.append({'node_id':node['id'],'reason':'meaning_or_role_unresolved'});continue
        if reference_only(text):
            holds.append({'node_id':node['id'],'reason':'reference_without_independent_speech_act'});continue
        if len(text)>600:
            holds.append({'node_id':node['id'],'reason':'literal_claim_capacity'});continue
        context=bundle(graph,node['id'],settings);authorship=row['authorship'];guards=[]
        if text.endswith(('?','？')):guards.append('question_not_automatically_asserted')
        outside=text
        for q in reversed(graph['quotation_ranges']):
            if node['span']['start']<=q['start'] and q['end']<=node['span']['end']:
                a=q['start']-node['span']['start'];b=q['end']-node['span']['start'];outside=outside[:a]+outside[b:]
        if outside!=text and re.fullmatch(r'[\d\s.%:;()—–\-+]*',outside):
            authorship='reported';guards.append('quoted_speech_not_own_endorsement')
        if guards and authorship in ('asserted','explicitly_endorsed'):authorship='uncertain'
        provenance={'node_id':node['id'],'selection_ref':refs[node['id']],'selection':deepcopy(row),'guards':guards}
        lookup={n['id']:n for n in graph['nodes']}
        claims.append({'id':claim_id(context),'text':mc.normalize(text),'source_id':graph['source']['id'],
            'source_sha256':digest(graph['source']),'record_id':'CR'+digest([VERSION,context,provenance]),
            'authorship':authorship,'evidence':[deepcopy(node['span'])],
            'essential_conditions':[deepcopy(lookup[e['ground_id']]['span']) for e in context['owned_edges'] if e['relation']=='necessary_condition'],
            'meaning_context':context,'source_selection':provenance,'generated_assertion_text':False})
    status=('partial' if claims else 'unresolved') if holds else ('covered' if claims else 'non_substantive')
    return {'artifact_kind':VERSION,'source':deepcopy(graph['source']),'source_sha256':digest(graph['source']),
        'graph':deepcopy(graph),'selection_batches':deepcopy(batches),'claims':claims,'status':status,
        'additional_passes':0,'holds':holds,'excluded_node_ids':excluded,
        'retained_ground_ids':[n['id'] for n in graph['nodes'] if n['kind']=='ground'],
        'coverage_scope':'assertion plus bound interpretation context; raw context alone is not utilization',
        'semantic_approval':False}


def validate(record):
    kind=record.get('artifact_kind')
    rebuilt=(assemble(record['graph'],record['selection_batches']) if kind==VERSION else
             assemble_interpreted(record['graph'],record['interpretations']) if kind==INTERPRETED_VERSION else None)
    if rebuilt!=record:
        raise ValueError('Contextual discovery provenance changed')
    return record


def discover(sources,work,save=None):
    from commentscope.factory import contextual_interpretation as ci
    mc.source_index(sources);save=save or (lambda name,value:None);records=[]
    for source in sources:
        graph=ed.parse(source);save('contextual-source-graphs/'+source['id'],graph)
        nodes={n['id']:n for n in ld.roots(graph)}
        save('contextual-position-bundles/'+source['id'],[bundle(graph,nid) for nid in nodes])
        tasks=[{'id':source['id'],'node_id':nid} for nid in nodes]
        interpreted=work('contextual-interpret',tasks,
            lambda group:ci.request(graph,nodes[group[0]['node_id']]),
            lambda group,result:ci.bind(graph,nodes[group[0]['node_id']],result),1)
        records.append(assemble_interpreted(graph,interpreted))
    return records
