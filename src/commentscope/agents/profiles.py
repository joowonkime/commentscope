"""Build development-only agent profiles from explicitly reviewed source families."""
from datetime import datetime, timezone

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.source_facets import assemble, validate
from commentscope.ingestion import load_snapshot, normalize_snapshot

VERSION = 'development-perspective-bundle-0.1'
LIMITS = [
    'This is an assistant-reviewed assertion family, not an approved common proposition.',
    'Represent a source-backed perspective, not real authors or a population consensus.',
    'Do not treat a prediction as necessity or endorsement; keep possibility, negation and conditions.',
    'Each reason, condition, quantity and time scope belongs only to its cited source.',
    'Other agents, user questions and previous answers are not evidence.',
    'For missing facts, acknowledge the limit instead of using outside knowledge.'
]


def require_live(expiry):
    if not expiry or datetime.fromisoformat(expiry.replace('Z', '+00:00')) <= datetime.now(timezone.utc):
        raise ValueError('Dataset expired; refresh authorization/data before running agents')


def build_bundle(snapshot_path, reviewed_path, *, allow_unapproved=False):
    if not allow_unapproved:
        raise ValueError('This input is unapproved. Explicit --allow-unapproved is required for development only')
    loaded = load_snapshot(snapshot_path); snapshot = loaded.snapshot
    require_live(snapshot.usage.expires_at)
    review = read_json(reviewed_path)
    if (review.get('artifact_kind') != 'assistant-reviewed-source-facets-0.1'
            or review.get('snapshot_sha256') != loaded.sha256 or review.get('expires_at') != snapshot.usage.expires_at
            or review.get('reviewer') != 'conversation_assistant' or review.get('human_approved') is not False
            or review.get('accepted_perspectives') != 0):
        raise ValueError('Unexpected reviewed input provenance/status')
    records = review['reviewed_records']
    by_id = {r['id']: r for r in records}; sources = {c.comment_id:c for c in snapshot.comments}
    aliases = {c.comment_id:c.duplicate_of for c in normalize_snapshot(snapshot)}
    if len(by_id) != len(records): raise ValueError('Duplicate member IDs')
    for r in records:
        source = sources.get(r['source_comment_id'])
        if source is None or r['source'] != source.text_original or aliases[source.comment_id] is not None:
            raise ValueError('Source text changed, missing, or duplicate alias')
        if (r['result'].get('origin') != 'assistant_review' or r['result'].get('human_approved') is not False
                or r['result']['errors'] or validate(r['result']['output'], r['source'])):
            raise ValueError('Reviewed record not structurally valid')
        for key in ['reason_ko','reading_ko','cautions_ko']:
            if not isinstance(r['review'].get(key),str) or not r['review'][key].strip():
                raise ValueError('Missing review interpretation or cautions')
    assembly = assemble(records)
    if assembly != review['assembly']: raise ValueError('Reviewed grouping changed')
    agents = []; non_agents = []
    for group in assembly['groups']:
        if group['status'] != 'proposal_needs_semantic_review':
            non_agents.append({'title':group['title'],'reason':'rare','member_ids':group['members']}); continue
        cards = []
        for mid in group['members']:
            r = by_id[mid]; source = sources[r['source_comment_id']]
            parent = sources.get(source.parent_id)
            cards.append({'evidence_id':mid,'source_comment_id':source.comment_id,
                          'original_text':source.text_original,'source_url':source.source_url,
                          'reviewer_reading_ko':r['review']['reading_ko'],'cautions_ko':r['review']['cautions_ko'],
                          'interpretation_origin':'conversation_assistant_not_literal_translation',
                          'parent_context':{'comment_id':source.parent_id,'status':source.parent_status,
                                            'text':parent.text_original if parent else None,'may_cite_as_support':False}})
        agents.append({'agent_id':f'A{len(agents)+1:03d}','title':group['title'],'assertion_family':group['kind'],
                       'polarity':group['polarity'],'status':'development_only_not_approved',
                       'evidence':cards,'constraints':LIMITS,'human_approved':False})
    for u in assembly['unassigned']:
        non_agents.append({'title':u['member_id'],'reason':u['reason'],'member_ids':[u['member_id']]})
    if not agents: raise ValueError('No reviewed family reaches three unique sources')
    return {'artifact_kind':VERSION,'snapshot_sha256':loaded.sha256,'reviewed_sha256':sha(reviewed_path),
            'expires_at':snapshot.usage.expires_at,'agents':agents,'non_agents':non_agents,
            'dataset':{'video':snapshot.to_dict()['video'],'captured_at':snapshot.captured_at,
                       'sample_size':len(snapshot.comments),'reviewed_sources':len(records),
                       'sampling':snapshot.to_dict()['sampling']},
            'human_approved':False,'accepted_perspectives':0,
            'limitations':['Assistant review is not independent gold','Not a production PerspectiveSpec',
                           'Claims of group coherence and reviewer interpretations remain revisable']}


def load_bundle(snapshot_path, reviewed_path, bundle_path, *, allow_unapproved=False):
    bundle = read_json(bundle_path)
    expected = build_bundle(snapshot_path,reviewed_path,allow_unapproved=allow_unapproved)
    if bundle != expected: raise ValueError('Bundle changed; rebuild a new source-bound artifact')
    return bundle
