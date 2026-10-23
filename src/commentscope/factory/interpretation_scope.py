"""Small source-syntax recognizer; no topic/intent/factual classification.

Only the listed comma-delimited if/even-if and postfix only-if forms are
recognized. Unknown constructions remain literal and require interpretation.
"""
import re
from copy import deepcopy

from commentscope.factory import explicit_discourse as ed
from commentscope.factory.automatic_contract import digest

VERSION = 'interpretation-scope-20261017-v1'
MARKER = re.compile(r'\b(?:even\s+if|only\s+if|if|unless|when|provided|because|although|though)\b', re.I)


def parse(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Nonempty original quotation required')
    markers = list(MARKER.finditer(text))
    result = {'artifact_kind': VERSION, 'text': text, 'text_sha256': digest(text),
              'scopes': [], 'status': 'no_recognized_scope_marker',
              'semantic_approval': False, 'factual_verification': False}
    if not any(m.group().lower() not in ('because',) for m in markers):
        return result
    result['status'] = 'requires_interpretation'
    quotes, issues = ed.quotation_ranges(text)
    if quotes or issues or re.search(r'[()\[\]{};\n\r]', text) or len(ed.statements(text, quotes)) != 1:
        return result
    commas = [m.start() for m in re.finditer(',', text)]
    tokens = [' '.join(m.group().lower().split()) for m in markers]
    parts = []; start = 0
    for end in [*commas, len(text)]:
        parts.append(ed.span(text, start, end)); start = end + 1
    if any(not p['text'].strip(' .!?') for p in parts):
        return result
    selected = []
    if (tokens == ['if'] and len(parts) == 2
            and markers[0].start() == parts[0]['start']):
        selected = [('condition', parts[0])]
    elif (tokens == ['if', 'even if'] and len(parts) == 3
          and markers[0].start() == parts[0]['start'] and markers[1].start() == parts[1]['start']):
        selected = [('condition', parts[0]), ('concession', parts[1])]
    elif tokens == ['even if'] and len(parts) == 2:
        if markers[0].start() == parts[0]['start']:
            selected = [('concession', parts[0])]
        elif markers[0].start() == parts[1]['start']:
            selected = [('concession', parts[1])]
    elif tokens == ['only if'] and len(parts) == 1:
        prefix = text[:markers[0].start()]
        if prefix.strip() and not re.search(r'\b(?:not|never)\s*$', prefix, re.I):
            selected = [('condition', ed.span(text, markers[0].start(), len(text)))]
    # Reject syntactically empty antecedents even if the delimiters match.
    for _, span in selected:
        marker = MARKER.match(span['text'])
        if not marker or not span['text'][marker.end():].strip(' .!?'):
            return result
    if selected:
        result['status'] = 'surface_syntax_only'
        result['scopes'] = [{'kind': kind, 'span': deepcopy(span)} for kind, span in selected]
    return result


def audit(statement, attachments):
    """Use source offsets and retain the full proposition; never delete qualifiers."""
    result = parse(statement['span']['text'])
    base = statement['span']['start']
    for scope in result['scopes']:
        scope['span']['start'] += base; scope['span']['end'] += base
    conflicts = []
    for attachment in attachments:
        if attachment['kind'] not in ('condition', 'concession') or attachment['origin'] != 'comment':
            continue
        for scope in result['scopes']:
            a = attachment['span']; b = scope['span']
            if a['start'] < b['end'] and b['start'] < a['end'] and attachment['kind'] != scope['kind']:
                conflicts.append({'code': 'condition_concession_conflict',
                    'model_attachment': deepcopy(attachment), 'surface_scope': deepcopy(scope)})
    return {'syntax': result, 'conflicts': conflicts,
            'original_statement_span': deepcopy(statement['span']), 'semantic_approval': False}
