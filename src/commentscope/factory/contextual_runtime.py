"""Replayable boundary for literal, self-contained contextual Agent cores.

Dependency declarations remain fallible and require semantic review. This
adapter never rewrites a referent or promotes context into asserted evidence.
"""
from copy import deepcopy

from commentscope.factory import minimal_claims as mc, contextual_dependencies as cd
from commentscope.factory import explicit_discourse as ed

VERSION = 'literal-contextual-runtime-20261017-v1'


def bind(candidate, dependency):
    mc.validate_candidate(candidate); cd.validate(dependency)
    bundle = candidate.get('meaning_context')
    if bundle != dependency['bundle']:
        raise ValueError('Runtime interpretation must bind the exact candidate context')
    guards = []
    if not dependency['ready']: guards.append('interpretation_unresolved')
    if dependency['links']: guards.append('external_interpretation_dependency')
    inv = bundle['scope_inventory']
    if inv['references'] or inv['answer_condition'] or inv['heading'] or bundle['setting_node_ids']:
        guards.append('literal_core_not_self_contained')
    graph = ed.parse(bundle['source']); nodes = {n['id']: n for n in graph['nodes']}
    assertion = bundle['assertion']
    for edge in bundle['owned_edges']:
        ground = nodes[edge['ground_id']]['span']
        if edge['relation'] == 'necessary_condition' and not (
                assertion['start'] <= ground['start'] and ground['end'] <= assertion['end']):
            guards.append('necessary_condition_outside_literal_core')
    return {'artifact_kind': VERSION, 'candidate': deepcopy(candidate),
            'dependency': deepcopy(dependency), 'text': candidate['text'],
            'interpretation_scope': {'world': dependency['output']['world']},
            'hold_reasons': sorted(set(guards)), 'ready': not guards,
            'semantic_approval': False}


def validate(record, candidate=None):
    if bind(record['candidate'], record['dependency']) != record:
        raise ValueError('Contextual runtime binding changed')
    if candidate is not None and candidate != record['candidate']:
        raise ValueError('Runtime candidate changed')
    return record


def validate_core(record, candidate_id, claim):
    validate(record)
    if (not record['ready'] or record['candidate']['id'] != candidate_id
            or claim['text'] != record['text'] or claim['id'] != candidate_id+':C'):
        raise ValueError('Contextual runtime core changed or is not self-contained')
    if claim['kind'] == 'fact' and record['interpretation_scope']['world'] != 'actual':
        raise ValueError('Nonactual factual scope is not supported by the fact verifier')
    return record
