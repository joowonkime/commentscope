"""Corpus-denominated opinion counts, independent of agent eligibility.

This is an accounting boundary, NOT a semantic classifier. Missing retrieval
hits are unassessed, partial support is not conditional support, and two agents
never prove that 80% of perspectives have been discovered.
"""
from collections import Counter
from copy import deepcopy

from commentscope.factory.automatic_contract import digest
from commentscope.factory.fact_checks import live
from commentscope.ingestion import normalize_snapshot

VERSION = 'corpus-opinion-map-0.1'
RELATIONS = ('supported', 'conditional', 'not_supported', 'uncertain', 'unassessed')


def build(snapshot, perspectives, assessments):
    live(snapshot.usage.expires_at)
    if len(snapshot.comments) > 1000:
        raise ValueError('MVP snapshot cap exceeded')
    originals = {c.comment_id: c.text_original for c in snapshot.comments}
    normalized = normalize_snapshot(snapshot)
    aliases = {c.comment_id: c.duplicate_of or c.comment_id for c in normalized if c.text_analysis}
    population = set(aliases.values())
    lookup = {}
    for p in perspectives:
        if (set(p) != {'id', 'claim', 'upstream_agent_state'}
                or not isinstance(p['id'], str) or not p['id'].strip() or p['id'] in lookup
                or not isinstance(p['claim'], dict) or not isinstance(p['claim'].get('text'), str)
                or not p['claim']['text'].strip()
                or not isinstance(p['upstream_agent_state'], str) or not p['upstream_agent_state'].strip()):
            raise ValueError('Unique source-bound perspective descriptions required')
        lookup[p['id']] = p
    records = {}; by_perspective = {pid: {} for pid in lookup}
    for row in assessments:
        if (set(row) != {'perspective_id', 'source_id', 'claim_sha256', 'source_sha256', 'relation', 'evidence_ref'}
                or row['perspective_id'] not in lookup or row['source_id'] not in aliases
                or row['relation'] not in RELATIONS
                or not isinstance(row['evidence_ref'], str) or not row['evidence_ref'].strip()):
            raise ValueError('Unknown or malformed source relationship')
        pid = row['perspective_id']; sid = row['source_id']; canonical = aliases[sid]
        if (row['claim_sha256'] != digest(lookup[pid]['claim'])
                or row['source_sha256'] != digest(originals[sid])):
            raise ValueError('Source or target binding changed')
        key = (pid, canonical)
        if key in records and records[key]['relation'] != row['relation']:
            raise ValueError('Conflicting canonical verdicts require explicit reconciliation')
        records.setdefault(key, {'perspective_id': pid, 'canonical_source_id': canonical,
                                 'relation': row['relation'], 'evidence_refs': set()})
        records[key]['evidence_refs'].add(row['evidence_ref'])
        by_perspective[pid][canonical] = row['relation']
    output = []; linked = set(); assessed = set(); fully_assessed = set(population) if lookup else set()
    for pid, p in lookup.items():
        rows = by_perspective[pid]
        counts = Counter(rows.values())
        counts['unassessed'] += len(population) - len(rows)
        members = sorted(sid for sid, relation in rows.items() if relation == 'supported')
        measured = {sid for sid, relation in rows.items() if relation != 'unassessed'}
        linked.update(members); assessed.update(measured); fully_assessed.intersection_update(measured)
        output.append({**deepcopy(p), 'counts': {r: counts[r] for r in RELATIONS},
                       'supported_canonical_ids': members,
                       'canonical_denominator': len(population),
                       'assessment_complete': counts['unassessed'] == 0,
                       'minimum_support_met': len(members) >= 3,
                       'agent_approved_by_map': False})
    return {'artifact_kind': VERSION, 'expires_at': snapshot.usage.expires_at,
            'perspectives': output,
            'assessments': [{**r, 'evidence_refs': sorted(r['evidence_refs'])} for _, r in sorted(records.items())],
            'coverage': {'raw_comments': len(originals), 'canonical_nonempty_comments': len(population),
                         'duplicate_aliases': sum(sid != canonical for sid, canonical in aliases.items()),
                         'empty_comments': len(originals)-len(aliases),
                         'discovered_candidate_perspectives': len(lookup),
                         'sources_assessed_for_any_perspective': len(assessed),
                         'sources_assessed_for_all_discovered_perspectives': len(fully_assessed),
                         'sources_with_supported_assignment': len(linked),
                         'sources_without_supported_assignment': len(population-linked),
                         'supported_assignment_rate': len(linked)/len(population) if population else None,
                         'perspective_recall': None,
                         'perspective_recall_status': 'requires_frozen_reference_perspectives'},
            'count_semantics': 'canonical_comment_counts_under_supplied_verdicts_not_people_or_truth',
            'quality_gate_passed': False,
            'limitations': ['Missing pairs are unassessed, not rejected.',
                            'A source can support several perspectives; counts are not additive.',
                            'Full assignment to discovered candidates does not prove discovery completeness.',
                            'Agent deferral never removes a perspective from this map.']}
