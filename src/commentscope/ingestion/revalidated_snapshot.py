"""Bind an unchanged fixed evaluation scope to fresh official-API receipts.

No collection, labels, inference, original-file mutation, or missing-row repair.
"""
from datetime import datetime,timedelta,timezone
from pathlib import Path

from commentscope.ingestion.loader import load_snapshot
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources
from commentscope.factory import fact_checks

VERSION='registered-scope-revalidation-0.1'


def bind(path,original,original_sha256,scope_ids):
    path=Path(path);value=read_json(path)
    if (value.get('version')!=VERSION or value.get('registered_snapshot_sha256')!=original_sha256
            or not isinstance(value.get('receipt_sha256'),dict) or not value['receipt_sha256']):
        raise ValueError('Registered snapshot and complete receipt manifest required')
    snapshot_file=Path(value['snapshot_file']);loaded=load_snapshot(snapshot_file);fresh=loaded.snapshot
    if loaded.sha256!=value['snapshot_sha256']:raise ValueError('Revalidated snapshot changed')
    inputs={str(path):sha(path),str(snapshot_file):loaded.sha256};requested=set();returned={};times=[];videos=[]
    for name,expected in value['receipt_sha256'].items():
        receipt=Path(name)
        if not receipt.resolve().is_relative_to(Path('runs').resolve()) or sha(receipt)!=expected:
            raise ValueError('Immutable private API receipts required')
        inputs[str(receipt)]=expected;row=read_json(receipt)
        if 'requested_ids' not in row:
            videos.extend(row['items']);continue
        ids=row['requested_ids']
        if len(ids)!=len(set(ids)) or requested&set(ids):raise ValueError('Duplicate receipt request IDs')
        requested.update(ids);times.append(datetime.fromisoformat(row['captured_at']))
        seen=set()
        for item in row['response']['items']:
            cid=item['id']
            if cid not in ids or cid in seen or cid in returned:raise ValueError('Foreign or duplicate API source')
            seen.add(cid);returned[cid]=item['snippet']
    if (requested!={c.comment_id for c in original.comments} or not times
            or set(returned)!={c.comment_id for c in fresh.comments}):
        raise ValueError('Receipt inventory differs from registered/fresh snapshots')
    for c in fresh.comments:
        r=returned[c.comment_id]
        if (c.text_original!=r['textDisplay'] or c.parent_id!=r.get('parentId')
                or c.likes!=r['likeCount'] or c.published_at!=r['publishedAt'] or c.replies_status!='unknown'):
            raise ValueError('Current source fields must match their actual receipt')
    if (len(videos)!=1 or videos[0]['id']!=original.video.video_id or fresh.video.video_id!=original.video.video_id
            or videos[0]['snippet']['title']!=fresh.video.title):raise ValueError('Video receipt changed')
    start=datetime.fromisoformat(fresh.captured_at);expiry=fact_checks.live(fresh.usage.expires_at)
    if (any(t.utcoffset() is None or t>datetime.now(timezone.utc)+timedelta(seconds=60) for t in times)
            or start!=min(times) or not start<expiry<=start+timedelta(days=30)):
        raise ValueError('Fresh capture and bounded retention required')
    before=sources(original,include_video_context=True);after=sources(fresh,include_video_context=True)
    if not scope_ids or len(scope_ids)!=len(set(scope_ids)) or any(s not in before or after.get(s)!=before[s] for s in scope_ids):
        raise ValueError('Every fixed source, parent and video context must remain identical')
    return fresh,snapshot_file,inputs,{'file':str(path),'sha256':sha(path),
        'snapshot_file':str(snapshot_file),'snapshot_sha256':loaded.sha256}
