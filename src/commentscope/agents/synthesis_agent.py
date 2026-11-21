"""Compile a derived perspective from agreed claims without inference."""
from commentscope.agents.debate_contracts import VERSION, unique_rows
from commentscope.factory.automatic_contract import digest
from commentscope.factory.fact_checks import live


def compile_agent(analysis, session_id, participants, points, report, shared):
    if (report['protocol'] != VERSION or report['outcome'] != 'consensus_ready'
            or not report['agent_id'] or not shared):
        raise ValueError('No validated shared claims to compile')
    conditions = report['conditions']
    votes = {(v['proposal_id'], v['agent_id']): v for v in report['ratifications']
             if v['draft_sha256'] == report['draft_sha256'] and v['verified'] and v['decision'] == 'accept'}
    for claim in shared:
        pid = claim['claim_id']
        if (pid not in report['shared_claim_ids'] or claim['origin'] == 'original_comment'
                or claim['direct_comment_support_count'] != 0 or claim['member_source_count'] != 0
                or not set(claim['condition_ids']) <= conditions.keys()
                or not claim['premise_point_ids'] or not set(claim['premise_point_ids']) <= points.keys()
                or claim['accepting_agent_ids'] != participants
                or any((pid, aid) not in votes for aid in participants)):
            raise ValueError('Shared claim is detached from the sealed agreement')
    refs = unique_rows([ref for row in shared for ref in row['_references']])
    documents = {doc['id']: doc for doc in analysis.bundle['documents']}
    expiry = min(live(t) for t in [analysis.bundle['expires_at'],
                 *(documents[ref['document_id']]['expires_at'] for ref in refs)])
    for sid in report['root_source_ids']:
        analysis.source(sid)
    agent = {
        'agent_id': report['agent_id'], 'revision': 1, 'kind': 'derived_consensus',
        'protocol': VERSION, 'synthesis_id': report['synthesis_id'], 'session_id': session_id,
        'analysis_revision': analysis.revision, 'report_sha256': digest(report),
        'parent_refs': [{'agent_id': aid, 'analysis_revision': analysis.revision} for aid in participants],
        'accepted_claims': shared, 'conditions': conditions,
        'disagreements': [dict(d, points=[{k: points[pid][k] for k in ('point_id','text','agent_id','origin')}
                                         for pid in d['point_ids']]) for d in report['disagreements']],
        'references': refs, 'root_source_ids': report['root_source_ids'],
        'root_source_count': report['root_source_count'], 'direct_comment_support_count': 0,
        'expires_at': expiry.isoformat(),
    }
    return {**agent, 'artifact_sha256': digest(agent)}
