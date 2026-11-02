"""Lossless semantic view for argument audits, without storage digests.

Addresses exist only inside a single request. Original records and the binding
keep their full identities; prose is never searched or replaced for addresses.
"""
from copy import deepcopy

VERSION = 'source-argument-audit-addresses-20261102-v1'
SUBJECT_SCOPED = 'source-argument-audit-subjects-20261102-v2'
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
SUBJECT_INSTRUCTIONS = '''
Judge each TASK's specific declaration. For a unit task TARGET is the complete
unit to audit, OWNER_POSITION is its fixed source position, and LINKED_CANDIDATES
contains only relationships actually claimed by TARGET, each with link_role.
Empty LINKED_CANDIDATES asserts no candidate relationship. An unlinked original
position need not restate any candidate. Its grounds still belong to its own
OWNER_POSITION, not to another core mentioned elsewhere in the original.
Check the declared role: a reason is an offered ground for its owner; a concession
is accepted despite support and need not restate or justify the candidate.
core_restatement denotes a source position; only its explicit candidate links
claim a relationship to a candidate core. Do not invent links for unselected units.
A reported unit declared not_asserted is faithful when the original reports it;
do not require the author to endorse the quotation. Incorrect attribution fails.
Different languages do not require a source unit to be a literal translation of
its linked candidate. Judge the declared relationship and meaning. source_language
describes ORIGINAL only. Check kind, scope and dependencies, not external truth.
SOURCES keeps the complete original and ALL source units for ownership context.
Unit tasks judge TARGET's declarations, not unrelated declarations in other units.
Coverage tasks still check ALL units, candidate kind/scope, language, dependencies
and completeness, using that task's full CANDIDATES. No omitted major content is
approved by a correct individual unit. A wrong declaration remains unsupported.
basis briefly cites source evidence or the specific mismatch. Do not rewrite or
provide deliberation. All addresses are local to this request and source.
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


def subjects(sources, tasks):
    """Attach the target's actual owner/links; coverage retains all core checks."""
    sources, tasks = deepcopy(sources), deepcopy(tasks)
    lookup = {s['ORIGINAL']['source_id']: s for s in sources}
    candidates = {sid: {c['id']: c for c in s.pop('CANDIDATES')}
                  for sid, s in lookup.items()}
    for task in tasks:
        sid = task['source_id']; source = lookup[sid]
        if task['kind'] == 'coverage':
            task['CANDIDATES'] = list(candidates[sid].values())
            continue
        target = next(u for u in source['UNITS'] if u['id'] == task['TARGET'])
        owner = next((u for u in source['UNITS']
                      if target.get('ownership_family') is not None
                      and u.get('source_node_id') == target['ownership_family']), None)
        task.update(TARGET=deepcopy(target), OWNER_POSITION=deepcopy(owner),
                    LINKED_CANDIDATES=[{**candidates[sid][cid],
                        'link_role': target.get('candidate_roles', {}).get(cid, target['role'])}
                        for cid in target['candidate_ids']],
                    audit_subject=('reported_original_unit' if target.get('authorship') == 'not_asserted'
                        else 'unlinked_original_position' if target['role'] == 'core_restatement' and not target['candidate_ids']
                        else 'source_owned_unit'))
    return sources, tasks
