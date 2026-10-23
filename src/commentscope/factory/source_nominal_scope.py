"""Literal subject addresses and bounded nominal-ellipsis candidates.

This records surface syntax, never replaces an assertion or proves coreference.
A single bare head after an addressed discourse operator may inherit a modifier
from one uniquely matching subject in that target. Semantic comparison still
has to assess this explicit proposal. Ambiguous candidates remain unresolved.
There are no source IDs, topic words, evaluation labels or model calls here.
"""
from copy import deepcopy
import re

from commentscope.factory import contextual_dependencies as cd, explicit_discourse as ed
from commentscope.factory import source_discourse_acts as acts, source_attribution as attribution
from commentscope.factory.automatic_contract import digest

VERSION = 'source-nominal-scope-20261017-v1'
FINITE = re.compile(r'\b(?:should|must|may|might|could|would|will|can|shall|is|are|was|were)\b', re.I)
WORDS = re.compile(r"[^\W\d_]+(?:[-’'][^\W\d_]+)*", re.UNICODE)
CLAUSAL = re.compile(r'\b(?:if|when|unless|because|although|though|that|which|who|while|whether)\b', re.I)
NON_NOMINAL_HEAD = re.compile(r'\b(?:to|of|for|from|by|with|in|on|at|about|as|than|through|and|or|having|being)\b', re.I)
QUANTIFIERS = re.compile(r'^(?:all|any|every|each|no|some|most|many|few|both|neither|either|only)\b', re.I)
PRONOUNS = {'i', 'we', 'you', 'he', 'she', 'it', 'they', 'this', 'that', 'these', 'those'}


def _subject(text, part, origin):
    """One whole pre-finite prefix, not arbitrary token windows or a POS claim."""
    if text[part['start']:part['end']] != part['text']:
        raise ValueError('Original nominal source span required')
    matches = list(FINITE.finditer(part['text']))
    if len(matches) != 1:
        return None
    stop = part['start'] + matches[0].start()
    prefix = ed.span(text, part['start'], stop)
    words = list(WORDS.finditer(prefix['text']))
    if (not words or CLAUSAL.search(prefix['text']) or
            ' '.join(w.group() for w in words) != ' '.join(prefix['text'].split())):
        return None
    last = words[-1]
    head = None
    if not NON_NOMINAL_HEAD.search(prefix['text']) and prefix['text'].lower() not in PRONOUNS:
        head = ed.span(text, prefix['start'] + last.start(), prefix['start'] + last.end())
    return {'origin': origin, 'subject': prefix,
            'predicate': ed.span(text, stop, part['end']), 'head': head,
            'bare_head': len(words) == 1 and head is not None,
            'quantified': bool(QUANTIFIERS.search(prefix['text']))}


def _context_subjects(scope, context):
    bundle = scope['bundle']; source = bundle['source']; origin = context['origin']
    if origin == 'source': text = source['text']
    elif origin == 'parent' and source['parent']: text = source['parent']['text']
    else: return [], ['nominal_context_origin_unavailable']
    part = context['span']
    if text[part['start']:part['end']] != part['text']:
        raise ValueError('Nominal antecedent is not its bound source text')
    quotes, issues = ed.quotation_ranges(text)
    quotes = [q for q in quotes if part['start'] <= q['start'] and q['end'] <= part['end']]
    if issues: return [], ['nominal_quotation_boundary_unresolved']
    # Use complete maximal quotations. Nested quotations cannot silently choose
    # an inner speaker, and multiple quoted subjects remain multiple candidates.
    if any(a != b and a['start'] <= b['start'] and b['end'] <= a['end'] for a in quotes for b in quotes):
        return [], ['nested_nominal_quotation_unresolved']
    parts = [ed.span(text, q['start'] + 1, q['end'] - 1) for q in quotes]
    if not quotes:
        reports = list(attribution.REPORT.finditer(part['text']))
        if reports:
            if len(reports) != 1 or reports[0].group().lower() not in {
                    'say', 'says', 'said', 'claim', 'claims', 'claimed', 'argue', 'argues', 'argued'}:
                return [], ['nominal_reporting_boundary_unresolved']
            start = part['start'] + reports[0].end()
            tail = ed.span(text, start, part['end'])
            match = re.match(r'that\s+', tail['text'], re.I)
            if match: tail = ed.span(text, tail['start'] + match.end(), tail['end'])
            parts = [tail]
        else: parts = [part]
    rows = [_subject(text, p, origin) for p in parts]
    return [row for row in rows if row], []


def record(scope):
    cd.validate(scope); bundle = scope['bundle']; source = bundle['source']
    discourse = acts.structure(bundle)
    own = discourse['following_own_utterance'] if discourse else bundle['assertion']
    parsed = _subject(source['text'], own, 'source') if own else None
    candidates = []; inherited = None; guards = []
    if parsed and parsed['bare_head'] and discourse:
        targets = [link['context'] for link in scope['links']
                   if link['requirement']['role'] == 'discourse_target' and link['context']]
        if len(targets) != 1:
            guards.append('nominal_discourse_target_unresolved')
        else:
            rows, issues = _context_subjects(scope, targets[0]); guards.extend(issues)
            candidates = [r for r in rows if r['head'] and
                          r['head']['text'].casefold() == parsed['head']['text'].casefold()]
            if len(candidates) != 1:
                guards.append('nominal_antecedent_not_unique')
            elif candidates[0]['quantified']:
                guards.append('nominal_antecedent_quantifier_scope_unresolved')
            else: inherited = candidates[0]
    return {'artifact_kind': VERSION, 'scope_sha256': digest(scope),
            'own_utterance': deepcopy(own), 'own_subject': parsed,
            'antecedent_candidates': candidates, 'inherited_subject_proposal': inherited,
            'guards': sorted(set(guards)), 'model_calls': 0,
            'assertion_rewritten': False, 'semantic_coreference_verified': False}


def packet(scope):
    """Put nominal operands before predicates; keep whole-policy dependencies."""
    row = record(scope); old = cd.packet(scope); own = row['own_subject']
    inherited = row['inherited_subject_proposal']
    selected = inherited or own
    result = {'subject': selected['subject']['text'] if selected else None,
              'surface_subject': own['subject']['text'] if own else None,
              'nominal_inheritance': 'unique_surface_head_proposal' if inherited else 'none',
              'predicate_context': own['predicate']['text'] if own else None,
              'world': old['world'], 'guards': row['guards'],
              'other_dependencies': [d for d in old['dependencies'] if d['role'] != 'discourse_target']}
    # Unsupported subject grammar is never silently treated as resolved. Retain
    # the complete comparison packet for independent semantic assessment.
    if own is None: result['unparsed_position'] = old
    if inherited:
        result['surface_head'] = own['head']['text']
        result['antecedent_subject'] = inherited['subject']['text']
        result['inheritance_requires_semantic_assessment'] = True
    return result


def exact_direct_retention(left, right):
    """Only literal direct operands; inherited links still need assessment."""
    a, b = record(left), record(right)
    if any(r['guards'] or not r['own_subject'] or not r['own_subject']['head'] or
           r['inherited_subject_proposal'] for r in (a, b)):
        return False
    # Complete predicate/dependency retention avoids approving other objects,
    # restrictions or different whole-policy referents from subject equality.
    return left['ready'] and right['ready'] and packet(left) == packet(right)
