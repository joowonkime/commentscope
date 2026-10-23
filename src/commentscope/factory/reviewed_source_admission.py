"""Bind an exact complete-source review before a source becomes a counted vote.

Review judgments are external validation artifacts, never generation inputs.
This gate cannot rewrite source/Agent content or certify final runtime behavior.
"""
from copy import deepcopy
from commentscope.factory.automatic_contract import digest

VERSION='review-before-source-admission-20261023-v1'
KINDS=('memberships','declarations','source-fact-closure','source-status')
REVIEW_FIELDS={'source_id','candidate_id','source_sha256','draft_sha256','files_sha256',
               'runtime_input','human_approved','verdict'}

def complete_review(review):
    return (isinstance(review,dict) and REVIEW_FIELDS<=set(review)
        and isinstance(review['files_sha256'],dict) and len(review['files_sha256'])==4
        and review['runtime_input'] is False and review['human_approved'] is False
        and review['verdict'] in ('pass','fail','uncertain'))

def packet(accepted,artifacts,files_sha256):
    if set(artifacts)!=set(KINDS) or len(files_sha256)!=4:
        raise ValueError('All4 immutable source artifacts required')
    source=artifacts['declarations']['source'];status=artifacts['source-status']
    closure=artifacts['source-fact-closure'];sid=accepted['source_id'];cid=accepted['candidate_id']
    if (source['id']!=sid or status['source_id']!=sid or status['candidate_id']!=cid
            or status['state']!='model_closed_pending_semantic_review'
            or digest(closure['draft'])!=accepted['draft_sha256']
            or accepted['record']['source']!=source
            or accepted['membership']!=artifacts['memberships']
            or accepted['record']['extraction_record']!=artifacts['declarations']):
        raise ValueError('Review packet must bind this exact complete source closure')
    return {'artifact_kind':VERSION+'-packet','source_id':sid,'candidate_id':cid,
        'accepted_sha256':digest(accepted),'source_sha256':digest(source),
        'draft_sha256':digest(closure['draft']),'files_sha256':deepcopy(files_sha256),
        'runtime_input':False,'human_approved':False}

def bind(accepted,packet,review):
    if (packet['artifact_kind']!=VERSION+'-packet' or packet['accepted_sha256']!=digest(accepted)
            or packet['source_id']!=accepted['source_id'] or packet['candidate_id']!=accepted['candidate_id']
            or packet['draft_sha256']!=accepted['draft_sha256']):
        raise ValueError('Source admission review packet changed')
    if review is None:
        verdict='unreviewed'
    else:
        if not complete_review(review):raise ValueError('Incomplete exact source review cannot count')
        for key in ('source_id','candidate_id','source_sha256','draft_sha256','files_sha256'):
            if review[key]!=packet[key]:raise ValueError('Review belongs to another source/core/draft or artifacts')
        if review['runtime_input'] is not False or review['human_approved'] is not False:
            raise ValueError('Source review must not become model input or final human approval')
        verdict=review['verdict']
        if verdict not in ('pass','fail','uncertain'):raise ValueError('Unknown direct source review verdict')
    return {'artifact_kind':VERSION,'source_id':accepted['source_id'],'candidate_id':accepted['candidate_id'],
        'packet_sha256':digest(packet),'review_sha256':digest(review),'verdict':verdict,
        'countable':verdict=='pass','runtime_input':False,'final_agent_approval':False}
