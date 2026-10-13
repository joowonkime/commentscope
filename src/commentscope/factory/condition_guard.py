"""A conservative lexical veto, NOT an entailment classifier.

Recognized English condition clauses must survive verbatim (case/whitespace
normalized). Paraphrases, extra conditions and unrelated/quoted conditions can
be over-rejected. Other languages and unrecognized constructions are unchecked.
No rule can approve a relation: an unchanged verdict still needs the model.
This is an experimental, known-failure-informed policy, not a quality claim.
"""
import re
import unicodedata

from commentscope.factory.scoped_discovery import verdict

VERSION = 'verbatim-condition-veto-0.1'
MARKER = re.compile(r'\b(?:on condition that|provided that|as long as|only when|assuming that|unless|if)\b', re.I)
END = re.compile(r'[,.;!?\n\r]')


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def clauses(text):
    """Keep exact source offsets; do not claim these are semantic parses."""
    found = []
    for match in MARKER.finditer(text):
        boundary = END.search(text, match.end())
        end = boundary.start() if boundary else len(text)
        found.append({'start': match.start(), 'end': end,
                      'text': text[match.start():end]})
    return found


def check(source, target):
    if not isinstance(source, str) or not isinstance(target, str):
        raise ValueError('Condition guard needs full source and target strings')
    original = clauses(source)
    target_clauses = {normalize(c['text']) for c in clauses(target)}
    missing = [c for c in original if normalize(c['text']) not in target_clauses]
    return {'version': VERSION, 'veto': bool(missing), 'missing': missing,
            'recognized_source_conditions': len(original), 'semantic_approval': False}


def effective(result, source, claim, policy=None):
    raw = verdict(result)
    if policy is None:
        return raw
    if policy != VERSION:
        raise ValueError('Unknown condition guard policy')
    audit = check(source, claim['text'])
    return 'unclear' if raw == 'supported' and audit['veto'] else raw


def from_row(result, row, policy=None):
    # Legacy unguarded records need no newly introduced source fields.
    return verdict(result) if policy is None else effective(result, row['text'], row['claim'], policy)
