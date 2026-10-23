"""Deterministic, conservative source syntax and evidence ownership.

This module recognizes a bounded grammar, never author intent or factual truth.
It has no model, video ID, topic vocabulary, candidate or evaluation input.
An edge records an explicit surface construction; semantic use still needs the
Factory's attribution, complete-scope and fact checks. Unsupported syntax stays
verbatim and cannot silently become an approved argument.
"""
from copy import deepcopy
from collections import OrderedDict
import json
import re
from threading import Lock

from commentscope.factory import minimal_claims as mc
from commentscope.factory.automatic_contract import digest

VERSION = 'explicit-discourse-20261016-v1'
# Additive surface grammar: existing constructions retain byte-identical graph
# identities. New leading premises acquire their own literal nodes and edges.
LEADING_PREMISE_EXTENSION = 'explicit-leading-considering-premise-20261023-v1'
QUOTES = {'"':'"', "'":"'", '“':'”', '‘':'’', '«':'»'}
OPERATORS = (
    ('necessary_condition', 'postfix', re.compile(r'\bonly\s+(?:if|when)\b',re.I)),
    ('concession', 'postfix', re.compile(r'\b(?:even\s+though|although)\b',re.I)),
    ('reason', 'postfix', re.compile(r'\bbecause\b',re.I)),
    ('reason', 'leading_reason', re.compile(r'\bconsidering(?:\s+that)?\b',re.I)),
    ('necessary_condition', 'prefix', re.compile(r'때만')),
    ('reason', 'previous_statement', re.compile(r'때문(?:입니다|이에요|이다)(?=[.!?。！？\s]*$)')),
)
UNSUPPORTED = re.compile(r'\b(?:unless|provided|since|whereas|while|if|when|though)\b|때문|경우에만|한해서',re.I)
AMBIGUOUS_NEGATION = re.compile(r'\b(?:not|never)\s+(?:just\s+)?(?:because|only|although|even\s+though)\b|때문[^.!?]*아니',re.I)
ABBREVIATION = re.compile(r'\b(?:Mr|Mrs|Ms|Dr|Prof|e\.g|i\.e|a\.m|p\.m)\.$',re.I)
PARSE_CACHE_POLICY = 'immutable-source-syntax-cache-20261017-v1'
_PARSE_CACHE = OrderedDict()
_PARSE_CACHE_LOCK = Lock()
_PARSE_CACHE_ENTRIES = 128
_PARSE_CACHE_ENTRY_BYTES = 65536


def span(text,start,end):
    while start<end and text[start].isspace():start+=1
    while end>start and text[end-1].isspace():end-=1
    return {'start':start,'end':end,'text':text[start:end]}


def quotation_ranges(text):
    stack=[];ranges=[];issues=[]
    for i,ch in enumerate(text):
        # Apostrophes within words are not quotation boundaries.
        if ch in ("'",'’') and i and i+1<len(text) and text[i-1].isalnum() and text[i+1].isalnum():continue
        if stack and ch==stack[-1][1]:
            start,_=stack.pop();ranges.append(span(text,start,i+1));continue
        if ch in QUOTES:
            stack.append((i,QUOTES[ch]))
        elif ch in ('”','’','»'):
            issues.append({'code':'unmatched_closing_quote','offset':i})
    issues.extend({'code':'unclosed_quote','offset':start} for start,_ in stack)
    ranges.extend(span(text,start,len(text)) for start,_ in stack)
    return sorted(ranges,key=lambda s:(s['start'],s['end'])),issues


def statements(text,quotes):
    def inside(i):return any(q['start']<=i<q['end'] for q in quotes)
    ends=set();n=len(text)
    for i,ch in enumerate(text):
        if inside(i):continue
        if ch in '\n\r':ends.add(i+1)
        elif ch in '.!?。！？' and (i+1==n or text[i+1].isspace()):
            if ch=='.' and ABBREVIATION.search(text[:i+1]):continue
            ends.add(i+1)
    # A full quoted sentence can end before an independently starting sentence.
    # The quotation stays in the preceding context, never becomes an own claim.
    for q in quotes:
        end=q['end'];tail=text[end:];following=re.search(r'\S',tail)
        if end>=2 and text[end-2] in '.!?。！？' and following:
            next_char=tail[following.start()]
            if next_char.isupper() or '\uac00'<=next_char<='\ud7a3':ends.add(end)
    ends.add(n);result=[];start=0
    for end in sorted(ends):
        s=span(text,start,end)
        if s['text']:result.append(s)
        start=end
    return result


def operators(text,statement,quotes):
    found=[]
    for relation,direction,pattern in OPERATORS:
        for match in pattern.finditer(statement['text']):
            start=statement['start']+match.start();end=statement['start']+match.end()
            if any(q['start']<end and start<q['end'] for q in quotes):continue
            found.append({'relation':relation,'direction':direction,'span':span(text,start,end)})
    return sorted(found,key=lambda op:(op['span']['start'],op['span']['end']))


def parse(source):
    """Reuse syntax computation, never a semantic verdict or a mutable record.

    The complete original, parent and metadata form the key. JSON preserves key
    order for exact request serialization; every return is a separate object.
    At most 128 entries of 64 KiB of ASCII JSON each are retained (key and value).
    Oversized inputs still receive the exact original parser without caching.
    """
    mc.validate_source(source)
    key = json.dumps(source, ensure_ascii=True, separators=(',', ':'))
    with _PARSE_CACHE_LOCK:
        cached = _PARSE_CACHE.get(key)
        if cached is not None: _PARSE_CACHE.move_to_end(key)
    if cached is not None: return json.loads(cached)
    result = _parse_uncached(source)
    encoded = json.dumps(result, ensure_ascii=True, separators=(',', ':'))
    if len(key) + len(encoded) <= _PARSE_CACHE_ENTRY_BYTES:
        with _PARSE_CACHE_LOCK:
            _PARSE_CACHE[key] = encoded
            _PARSE_CACHE.move_to_end(key)
            while len(_PARSE_CACHE) > _PARSE_CACHE_ENTRIES: _PARSE_CACHE.popitem(last=False)
    return result


def _parse_uncached(source):
    mc.validate_source(source);text=source['text'];source_hash=digest(source)
    quotes,quote_issues=quotation_ranges(text);parts=statements(text,quotes)
    nodes=[];edges=[];records=[];holds=list(quote_issues)

    def node(s,kind,statement_index):
        value={'source_sha256':source_hash,'span':deepcopy(s),'kind':kind,'statement_index':statement_index}
        value['id']='DN'+digest([VERSION,value]);nodes.append(value);return value

    def edge(parent,ground,operator,attachment):
        value={'source_sha256':source_hash,'parent_id':parent['id'],'ground_id':ground['id'],
            'relation':operator['relation'],'operator':deepcopy(operator['span']),
            'attachment':attachment,'semantic_approval':False}
        value['id']='DE'+digest([VERSION,value]);edges.append(value);return value

    previous=None
    for index,statement in enumerate(parts):
        own_quotes=[q for q in quotes if q['start']<statement['end'] and statement['start']<q['end']]
        ops=operators(text,statement,quotes);reasons=[]
        if quote_issues:reasons.append('quotation_boundary_unresolved')
        if own_quotes:reasons.append('quoted_context_requires_attribution')
        if len(ops)>1:reasons.append('multiple_operators_require_scope_analysis')
        if statement['text'].endswith(('?','？')):reasons.append('question_requires_authorship_analysis')
        if ops and re.search(r'[()\[\]{}]',statement['text']):reasons.append('parenthetical_scope_requires_analysis')
        if AMBIGUOUS_NEGATION.search(statement['text']):reasons.append('negated_operator_requires_scope_analysis')
        for match in UNSUPPORTED.finditer(statement['text']):
            a=statement['start']+match.start();b=statement['start']+match.end()
            if any(q['start']<b and a<q['end'] for q in quotes):continue
            if not any(op['span']['start']<=a and b<=op['span']['end'] for op in ops):
                reasons.append('unsupported_operator_requires_scope_analysis');break
        if len(ops)==1 and not reasons:
            op=ops[0];a=op['span']['start'];b=op['span']['end']
            if op['direction']=='postfix':
                head=span(text,statement['start'],a);ground=span(text,a,statement['end'])
                if not head['text'] or not text[b:statement['end']].strip(' .!?。！？\t\n\r'):
                    reasons.append('operator_without_complete_local_sides')
                else:
                    # A necessary condition is kept in the complete parent.
                    parent=node(statement if op['relation']=='necessary_condition' else head,'statement',index)
                    child=node(ground,'ground',index);edge(parent,child,op,'within_statement')
                    previous=parent
            elif op['direction']=='prefix':
                condition=span(text,statement['start'],b);head=span(text,b,statement['end'])
                if not head['text'].strip(' .!?。！？') or condition['start']==a:
                    reasons.append('operator_without_complete_local_sides')
                else:
                    parent=node(statement,'statement',index);child=node(condition,'ground',index)
                    edge(parent,child,op,'within_statement');previous=parent
            elif op['direction']=='leading_reason':
                # Only a sentence-initial, single unambiguous comma boundary.
                # Thousands separators do not split a monetary/quantity claim.
                commas=[i for i in range(b,statement['end']) if text[i]==',' and
                    not (i>0 and i+1<len(text) and text[i-1].isdigit() and text[i+1].isdigit())]
                if a!=statement['start'] or len(commas)!=1:
                    reasons.append('leading_premise_boundary_unresolved')
                else:
                    comma=commas[0];ground=span(text,statement['start'],comma+1)
                    head=span(text,comma+1,statement['end'])
                    if (not text[b:comma].strip(' .!?。！？\t\n\r') or
                            not head['text'].strip(' .!?。！？')):
                        reasons.append('operator_without_complete_local_sides')
                    else:
                        parent=node(head,'statement',index);child=node(ground,'ground',index)
                        edge(parent,child,op,'within_statement');previous=parent
            else:
                gap=text[parts[index-1]['end']:statement['start']] if index else ''
                if previous is None or previous['statement_index']!=index-1 or re.search(r'\n\s*\n',gap):
                    reasons.append('explicit_fragment_without_adjacent_parent')
                else:
                    child=node(statement,'ground',index);edge(previous,child,op,'adjacent_explicit_fragment')
                    previous=None  # Do not chain a later ground onto this ground.
        elif not ops and not reasons:
            previous=node(statement,'statement',index)
        if reasons:
            previous=None;node(statement,'unresolved_statement',index)
            holds.append({'statement_index':index,'codes':sorted(set(reasons)),'span':deepcopy(statement)})
        records.append({'span':deepcopy(statement),'operators':ops,'quote_ranges':deepcopy(own_quotes),
            'status':'requires_interpretation' if reasons else 'syntax_recorded'})
    return {'artifact_kind':VERSION,'source':deepcopy(source),'source_sha256':source_hash,
        'statements':records,'quotation_ranges':quotes,'nodes':nodes,'edges':edges,'holds':holds,
        'model_calls':0,'generated_assertion_text':False,'semantic_approval':False,
        'attribution_verified':False,'factual_verification':False,'quality_gate_passed':False}


def validate(record):
    if parse(record['source'])!=record:raise ValueError('Deterministic discourse provenance or ownership changed')
    return record


def ground_for(record,edge_id,position_id):
    """Export a literal ground only under its immutable source-local parent.

    Caller still has to verify how that parent relates to a common candidate.
    This proof cannot stand in for a candidate membership or factual verdict.
    """
    validate(record)
    edge=next((e for e in record['edges'] if e['id']==edge_id),None)
    if edge is None or edge['parent_id']!=position_id:
        raise ValueError('A source ground cannot be transferred to another position')
    nodes={n['id']:n for n in record['nodes']}
    return {'artifact_kind':VERSION+'-ground-ownership','graph_sha256':digest(record),
        'source_sha256':record['source_sha256'],'edge':deepcopy(edge),
        'position':deepcopy(nodes[position_id]),'ground':deepcopy(nodes[edge['ground_id']]),
        'candidate_alignment_verified':False,'factual_verification':False}
