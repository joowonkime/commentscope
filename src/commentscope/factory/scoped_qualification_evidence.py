"""Source-only, role-bound evidence addresses for a fixed position's details.

No candidate text is used to discover source evidence. Unknown syntax does not
invent a reason, and another position, parent comment or discourse target cannot
donate a ground. Exact addresses constrain the later semantic comparison.
"""
from copy import deepcopy
import re

from commentscope.factory import contextual_dependencies as cd, explicit_discourse as ed
from commentscope.factory import source_discourse_acts as acts, owned_arguments as oa
from commentscope.factory.automatic_contract import digest

VERSION='scoped-qualification-evidence-20261017-v1'
ROLES={'reason':'reason','necessary_condition':'condition','concession':'concession'}


def inventory(scope):
    cd.validate(scope);bundle=scope['bundle'];source=bundle['source'];text=source['text']
    graph=ed.parse(source);nodes={n['id']:n for n in graph['nodes']};rows=[]
    for edge in bundle['owned_edges']:
        if edge['parent_id']!=bundle['node_id']:raise ValueError('Foreign qualification parent')
        rows.append({'role':ROLES[edge['relation']], 'span':deepcopy(nodes[edge['ground_id']]['span']),
                     'parent_node_id':bundle['node_id'], 'syntax_proof':{'kind':'original_owned_edge','edge_id':edge['id']}})
    act=acts.structure(bundle);body=act['following_own_utterance'] if act else bundle['assertion']
    if body:
        # The old discourse graph intentionally holds multiple operators. This
        # separate bounded witness can preserve an entire coordinated reason
        # without changing that graph, its parent or any historical node IDs.
        ops=ed.operators(text,body,graph['quotation_ranges'])
        quotes=any(q['start']<body['end'] and body['start']<q['end'] for q in graph['quotation_ranges'])
        coordinated=(len(ops)>1 and all(op['relation']=='reason' and op['direction']=='postfix' for op in ops)
            and all(re.search(r'\band\s*$',text[body['start']:op['span']['start']],re.I) for op in ops[1:])
            and not quotes and not ed.AMBIGUOUS_NEGATION.search(body['text'])
            and not ed.UNSUPPORTED.search(body['text']) and not re.search(r'[;:()\[\]{}]',body['text']))
        if coordinated and text[body['start']:ops[0]['span']['start']].strip():
            rows.append({'role':'reason','span':ed.span(text,ops[0]['span']['start'],body['end']),
                'parent_node_id':bundle['node_id'], 'syntax_proof':{'kind':'coordinated_explicit_reasons',
                    'operators':[deepcopy(op['span']) for op in ops],
                    'parent_span':ed.span(text,body['start'],ops[0]['span']['start'])}})
        for anchor in oa.temporal_anchors(body['text']):
            rows.append({'role':'time_restriction',
                'span':ed.span(text,body['start']+anchor['start'],body['start']+anchor['end']),
                'parent_node_id':bundle['node_id'], 'syntax_proof':{'kind':'own_temporal_anchor'}})
    unique={digest([r['role'],r['span']]):r for r in rows}
    rows=sorted(unique.values(),key=lambda r:(r['span']['start'],r['span']['end'],r['role']))
    for i,row in enumerate(rows,1):row['id']=f'E{i}'
    return {'artifact_kind':VERSION,'source_id':source['id'],'source_sha256':digest(source),
        'scope_sha256':digest(scope),'parent_node_id':bundle['node_id'],'evidence':rows,
        'coverage':'bounded_explicit_syntax_only','model_calls':0,'semantic_approval':False}


def eligible(scope,role,*,include_attached=True):
    body=scope['bundle']['assertion']
    return [e for e in inventory(scope)['evidence'] if e['role']==role and
            (include_attached or body['start']<=e['span']['start'] and e['span']['end']<=body['end'])]
