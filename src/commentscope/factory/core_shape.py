"""Shared literal core boundaries, never an approval of source support."""
from commentscope.factory import explicit_discourse as discourse


def holds(graph):
    discourse.validate(graph)
    reasons = []
    if graph['holds']:
        reasons.append('core_syntax_unresolved')
    if any(edge['relation'] != 'necessary_condition' for edge in graph['edges']):
        reasons.append('compound_core_requires_separate_interpretation')
    return reasons


def candidate_holds(candidate):
    return holds(discourse.parse({'id': candidate['id'], 'text': candidate['text'], 'parent': None}))
