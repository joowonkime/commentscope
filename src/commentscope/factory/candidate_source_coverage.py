"""Candidate-scoped projections of already bound source observations.

Never edits a source/audit receipt or promotes raw support to semantic approval.
The caller validates the complete audit set with source_arguments.audit_verdicts
before using this projection. Unknown source failures retain legacy rejection.
"""
from commentscope.factory import argument_dependencies as deps, argument_observations as obs
from commentscope.factory import owned_arguments as owned
from commentscope.factory.automatic_contract import digest

VERSION = 'candidate-source-coverage-20261110-v1'
POLICY = 'candidate_verified_subset'
SCOPABLE = {'supported_candidate_without_owned_position', 'position_alignment_uncertain'}


def project(record, candidate_id, cores, audits):
    extraction = record.get('extraction_record', {})
    holds = set(extraction.get('hold_reasons', ()))
    if (extraction.get('artifact_kind') != owned.VERSION or holds - SCOPABLE
            or record['status'] != 'complete' and not holds):
        return None
    address = 'AC' + digest(record)
    found = [(a, i) for a in audits for i, task in enumerate(a['tasks'])
             if task['kind'] == 'coverage' and task['task_id'] == address]
    if len(found) != 1 or found[0][0].get('protocol') != obs.TYPED_CHAT:
        return None
    audit, index = found[0]
    row = next(r for r in audit['response']['observations'] if r['task_id'] == 'T' + str(index + 1))
    guards = []
    if row['source_coverage'] != 'complete':
        guards.append('member_completeness_not_verified')
    if row['actual_source_language'] == 'uncertain' or row['actual_source_language'] != record['source_language']:
        guards.append('source_language_unverified')
    if record['dependency_status'] != 'complete':
        guards.append('member_dependencies_unresolved')
    if not any(candidate_id in u['candidate_ids'] and u['role'] == 'core_restatement'
               and u['authorship'] == 'asserted_or_endorsed' for u in record['units']):
        guards.append('candidate_owned_position_unverified')
    candidate = next(c['candidate'] for c in cores if c['candidate']['id'] == candidate_id)
    if any(a['candidate_sha256'] == digest(candidate) and a['relation'] == 'uncertain'
           for a in extraction['alignments']):
        guards.append('candidate_position_alignment_uncertain')
    checks = [c for c in audit['dependency_checks'] if c['task']['source_id'] == record['source']['id']]
    guards.extend(deps.guards(record, cores, checks, typed=True, candidate_id=candidate_id)['coverage'])
    return {'artifact_kind': VERSION, 'source_id': record['source']['id'], 'candidate_id': candidate_id,
            'record_sha256': digest(record), 'audit_sha256': digest(audit),
            'aggregate_source_status': record['status'], 'aggregate_hold_reasons': sorted(holds),
            'guards': sorted(set(guards)), 'semantic_approval': False}
