"""Bounded surface forms for speech act and modality, never factual truth.

An antecedent does not assert that its condition is satisfied. A recognized
copular possibility retains its modal wording. Direct unquoted speech can be
attributed without deciding its position, factual type, or candidate membership.
Everything outside this grammar remains for interpretation or an explicit hold.
"""
import re
from commentscope.factory import explicit_discourse as ed
from commentscope.factory.automatic_contract import digest

VERSION='source-speech-forms-20261016-v1'
REPORT=re.compile(r'\b(?:say|says|said|reported?|reports|thinks?|thought|claims?|claimed|according|asks?|asked|told|whether|wonder)\b|라고|다는|말했|말하|생각하|주장하',re.I)
EMBEDDED=re.compile(r'\b(?:and|or|but|if|unless|because|although|that|who|which|since|when)\b',re.I)
WORD=r"[A-Za-z][A-Za-z0-9’'\-]*"
MODAL=re.compile(rf'(?P<subject>{WORD}(?:\s+{WORD}){{0,7}})\s+(?P<modal>may|might|could|would)\s+(?:not\s+)?be\s+(?P<predicate>{WORD}(?:\s+{WORD}){{0,5}})[.!]?',re.I)
FIRST_PERSON=re.compile(r'^I\s+(?:(?:support|oppose|prefer|want|disagree)\b|would\s+like\b)',re.I)
KOREAN_DIRECT=re.compile(r'(?:[가-힣]+야\s*(?:합니다|한다|해요)|(?:찬성|반대)\s*합니다)[.!。]?\s*$')
DYNAMIC_CONSEQUENCE=re.compile(r'would\s+(?:not\s+)?(?P<verb>make|reduce|increase|cause|create|allow|enable|prevent|improve|worsen|provide|leave|give|bring|lead|result)\s+(?P<complement>[^.!?;\r\n]+)[.!]?',re.I)
EVALUATIVE_MAKE=re.compile(r'(?:(?:a|an)\s+(?:good|bad|great|poor|terrible|fine|excellent)\b|(?:(?:no|any|perfect|little|a\s+lot\s+of)\s+)?sense\b)',re.I)
UNBOUNDED_EFFECT=re.compile(r'[\d$€£%]|,\s*(?:I|we|they|it|you|he|she|this|that|these|those|the)\b',re.I)


def interpret(graph,node,discourse_context=None):
    ed.validate(graph)
    if node not in graph['nodes']:raise ValueError('Bound source node required')
    edge=next((e for e in graph['edges'] if e['ground_id']==node['id']),None)
    body=node['span']['text'];binding=None
    context_wire=None
    if discourse_context is not None:
        from commentscope.factory import source_discourse
        context_wire=source_discourse.context_wire(graph,node,discourse_context)
    if edge and edge['relation']=='necessary_condition':
        binding={'rule':'necessary_condition_antecedent','kind':'uncertain','authorship':'not_asserted',
            'assertion_mode':'conditional_antecedent','parent_id':edge['parent_id']}
    elif node['kind']!='unresolved_statement' and not REPORT.search(graph['source']['text']):
        if edge and edge['operator']['start']==node['span']['start']:
            body=graph['source']['text'][edge['operator']['end']:node['span']['end']].strip()
        modal=MODAL.fullmatch(body)
        consequence=DYNAMIC_CONSEQUENCE.fullmatch(body)
        if (context_wire is not None and context_wire['relation'] in ('reason','concession') and
                consequence and not EMBEDDED.search(body) and not UNBOUNDED_EFFECT.search(body) and
                not (consequence['verb'].lower()=='make' and
                    EVALUATIVE_MAKE.match(consequence['complement']))):
            parent=next(e['parent_id'] for e in discourse_context['interpretation']['edges']
                if e['id']==discourse_context['edge_id'])
            binding={'rule':'source_bound_dynamic_modal_consequence','kind':'prediction',
                'authorship':'linked_to_parent','parent_id':parent,'assertion_mode':'assertion',
                'discourse_context_sha256':digest(discourse_context)}
        elif modal and not EMBEDDED.search(modal['subject']+' '+modal['predicate']):
            binding={'rule':'copular_epistemic_modal','kind':'prediction',
                'authorship':'linked_to_parent' if edge else 'asserted_or_endorsed',
                'assertion_mode':'assertion','parent_id':edge['parent_id'] if edge else None}
        elif (edge and edge['relation'] in ('reason','concession') and
                not any(q['start'] < node['span']['end'] and q['end'] > node['span']['start']
                        for q in graph['quotation_ranges'])):
            # Ownership follows this same-source explicit edge, not truth.
            # declare() still resolves the parent's actual attribution; a
            # conditional antecedent and reported/quoted speech stay guarded.
            binding={'rule':'literal_ground_parent_attribution','kind':None,
                'authorship':'linked_to_parent','parent_id':edge['parent_id'],
                'assertion_mode':'assertion'}
        elif node['kind']=='statement' and (FIRST_PERSON.search(body) or KOREAN_DIRECT.search(body)):
            binding={'rule':'direct_speech_form','kind':None,'authorship':'asserted_or_endorsed',
                'assertion_mode':'assertion','parent_id':None}
    return {'artifact_kind':VERSION,'graph_sha256':digest(graph),'node_id':node['id'],
        'binding':binding,'semantic_truth_verified':False,'candidate_support_verified':False}
