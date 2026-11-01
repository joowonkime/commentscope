"""Lossless semantic view for argument audits, without storage digests.

Addresses exist only inside a single request. Original records and the binding
keep their full identities; prose is never searched or replaced for addresses.
"""
from copy import deepcopy

VERSION = 'source-argument-audit-addresses-20261102-v1'
INSTRUCTIONS = '''
TASKS selects what to judge: TARGET is a unit address in that source's UNITS,
or all_source_units_and_candidate_links for coverage. C1.. are candidate
addresses, N1.. identify source nodes and E1.. ownership edges within a source.
An identical ownership_family means the ground belongs to that same position;
different families must not donate reasons to each other. requires uses the
source-local local_id; core_requires_for uses candidate addresses.
For a unit task judge that TARGET's declarations, using other units as context.
For coverage judge all units, candidate scopes, language and completeness.
Normative statements and their evaluative grounds do not need empirical proof
to preserve an author's meaning. First-person endorsement can express the same
policy stance as a demand; language differences alone do not change the stance.
An unlinked additional position is allowed; it is not an invented core reason.
basis briefly identifies the source evidence or specific mismatch supporting
the verdict. Do not rewrite the proposal or provide deliberation.
'''


def project(sources, tasks):
    """Copy all semantic declarations; shorten only typed identity fields."""
    result = deepcopy(sources)
    candidate_ids = sorted({c['id'] for s in result for c in s['CANDIDATES']})
    candidates = {cid: f'C{i}' for i, cid in enumerate(candidate_ids, 1)}
    targets = {}
    for source in result:
        sid = source['ORIGINAL']['source_id']
        source['ORIGINAL'].pop('source_sha256', None)
        nodes = {}; edges = {}
        for i, unit in enumerate(source['UNITS'], 1):
            targets[(sid, unit['id'])] = f'U{i}'
            unit['id'] = f'U{i}'
            unit.pop('source_sha256', None)
            unit.pop('source_id', None)
            for key in ('source_node_id', 'ownership_family'):
                if unit.get(key) is not None:
                    nodes.setdefault(unit[key], f'N{len(nodes)+1}')
                    unit[key] = nodes[unit[key]]
            if unit.get('ownership_edge_id') is not None:
                edge = unit['ownership_edge_id']
                edges.setdefault(edge, f'E{len(edges)+1}')
                unit['ownership_edge_id'] = edges[edge]
            unit['candidate_ids'] = [candidates[cid] for cid in unit['candidate_ids']]
            if 'candidate_roles' in unit:
                unit['candidate_roles'] = {candidates[cid]: role
                                           for cid, role in unit['candidate_roles'].items()}
            unit['core_requires_for'] = [candidates[cid] for cid in unit['core_requires_for']]
        for candidate in source['CANDIDATES']:
            candidate['id'] = candidates[candidate['id']]
    wire_tasks = [{'task_id': f'T{i}', 'source_id': t['source_id'], 'kind': t['kind'],
                   'TARGET': targets[(t['source_id'], t['task_id'])] if t['kind'] == 'unit'
                   else 'all_source_units_and_candidate_links'}
                  for i, t in enumerate(tasks, 1)]
    return result, wire_tasks
