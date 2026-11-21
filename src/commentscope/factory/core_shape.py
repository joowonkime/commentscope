"""Shared literal core boundaries, never an approval of source support."""
from commentscope.factory import explicit_discourse as discourse


def qualification_spans(text, qualifications):
    """Locate complete, unique literal qualifiers in the published core text."""
    if not isinstance(qualifications, list) or len(qualifications) > 4:
        raise ValueError('Bounded candidate qualifications required')
    spans = []
    for row in qualifications:
        if (not isinstance(row, dict) or set(row) != {'role', 'text'}
                or row['role'] not in ('condition', 'exception')):
            raise ValueError('Candidate qualification must be a condition or exception')
        fragment = row['text']
        if (not isinstance(fragment, str) or fragment != fragment.strip()
                or len(fragment.split()) < 2 or fragment == text or fragment not in text):
            raise ValueError('Qualification must quote a unique proper part of the candidate')
        start = text.index(fragment)
        end = start+len(fragment)
        if (text.find(fragment,start+1)!=-1
                or (start and text[start-1].isalnum() and text[start].isalnum())
                or (end < len(text) and text[end-1].isalnum() and text[end].isalnum())
                or spans and start < spans[-1]['end']):
            raise ValueError('Qualifiers must be ordered, separate whole-word spans')
        spans.append({'start':start, 'end':end, 'text':fragment})
    return spans


def holds(graph, qualifications=()):
    discourse.validate(graph)
    reasons = []
    for row in graph['holds']:
        if qualifications and row.get('codes') == ['unsupported_operator_requires_scope_analysis']:
            offsets = row['span']['start']
            operators = list(discourse.UNSUPPORTED.finditer(row['span']['text']))
            if len(operators)==1:
                start=offsets+operators[0].start()
                end=offsets+operators[0].end()
                if any(q['start']<=start and end<=q['end'] for q in qualifications):
                    continue
        reasons.append('core_syntax_unresolved')
        break
    if any(edge['relation'] != 'necessary_condition' for edge in graph['edges']):
        reasons.append('compound_core_requires_separate_interpretation')
    return reasons


def candidate_holds(candidate):
    shape = discourse.parse({'id': candidate['id'], 'text': candidate['text'], 'parent': None})
    return holds(shape, qualification_spans(candidate['text'], candidate.get('qualifications', [])))
