"""Verify the approved data-only 999 renewal; no collection or inference."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import json
import unicodedata
from urllib.parse import urlencode

from commentscope.factory import acceptance,comment_utilization as utilization
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.factory.framed_corpus import sources
from commentscope.ingestion import load_snapshot,revalidated_snapshot

VERSION='registered-cohort-refresh-20261110-v1'


def private(path):
    value=Path(path).resolve()
    if not any(value.is_relative_to(Path(root).resolve()) for root in ('runs','data')):
        raise ValueError('Private cohort input required')


def latest_fill(base,receipts,selection):
    """Replay time-order selection without inspecting eligibility or sentiment."""
    normalize=lambda text:' '.join(unicodedata.normalize('NFC',text).split())
    ids={c.comment_id for c in base.comments}
    seen={(normalize(c.text_original),c.parent_id) for c in base.comments}
    selected=[];rank=0;previous_token=None;previous_at=None
    start=datetime.fromisoformat(selection['frozen_at'])
    if start.utcoffset() is None:raise ValueError('Timezone-aware selection freeze required')
    for row in receipts:
        query=row['query'];at=datetime.fromisoformat(row['retrieved_at'])
        if (at.utcoffset() is None or at<start or previous_at is not None and at<previous_at
                or at>datetime.now(timezone.utc)+timedelta(seconds=60)
                or query.get('videoId')!=base.video.video_id or query.get('order')!='time'
                or query.get('textFormat')!='plainText' or query.get('pageToken')!=previous_token):
            raise ValueError('Ordered official same-video receipt required')
        previous_at=at;previous_token=row['response'].get('nextPageToken')
        for thread in row['response']['items']:
            rank+=1
            if thread['snippet']['videoId']!=base.video.video_id:raise ValueError('Foreign video receipt')
            item=thread['snippet']['topLevelComment'];snippet=item['snippet']
            if snippet.get('parentId') is not None:raise ValueError('Root selection cannot import a reply')
            cid=item['id'];text=snippet['textOriginal'];key=(normalize(text),None)
            if cid in ids or not key[0] or key in seen:continue
            selected.append({'comment_id':cid,'text_original':text,'parent_id':None,'parent_status':'root',
                'replies_status':'unknown','published_at':snippet['publishedAt'],
                'language':{'tag':'und','confidence':None,'method':'unknown'},
                'source_url':'https://www.youtube.com/watch?'+urlencode({'v':base.video.video_id,'lc':cid}),
                'sampling_origins':[{'method':'youtube:time-refresh','rank':rank}],'likes':snippet['likeCount']})
            ids.add(cid);seen.add(key)
            if len(selected)==2:return selected
    raise ValueError('Two mechanically selected replacements required')


def bind(path):
    private(path);path=Path(path);value=read_json(path);inputs={str(path):sha(path)}
    if (value.get('version')!=VERSION or value.get('quality_profile_sha256')!=acceptance.R5_DIGEST
            or value.get('canonical_sources')!=999 or value.get('meaningful_sources')!=755
            or value.get('minimum_correct_utilization')!=453 or value.get('new_model_calls')!=0
            or not isinstance(value.get('approval'),dict) or not value['approval'].get('user_request','').strip()
            or value['approval'].get('old_results_preserved') is not True):
        raise ValueError('Approved data-only renewal with unchanged r5 criteria required')

    def file(field):
        name=value[field+'_file']
        if field=='old_meaning_reference':
            # The registered historical reference may itself be a symlink to
            # the original private checkout. Permit only that exact reference.
            registered=read_json('runs/design-freeze-20261016/samples.json')['meaning_reference']
            if Path(name).resolve()!=Path(registered).resolve():raise ValueError('Foreign historical reference')
        else:private(name)
        if sha(name)!=value[field+'_sha256']:raise ValueError('Cohort input changed: '+field)
        inputs[name]=sha(name);return Path(name)

    original_file=file('original_snapshot');original=load_snapshot(original_file)
    base_binding=file('base_scope_refresh');raw_base=read_json(base_binding)
    base_loaded=load_snapshot(raw_base['snapshot_file']);retained=sorted(sources(base_loaded.snapshot))
    base,base_file,extra,base_proof=revalidated_snapshot.bind(base_binding,original.snapshot,original.sha256,retained)
    inputs.update(extra)
    if len(base.comments)!=998 or len(retained)!=997:raise ValueError('Exact revalidated baseline required')
    selection_file=file('selection_plan');selection=read_json(selection_file)
    if (selection.get('base_snapshot_sha256')!=sha(base_file)
            or selection.get('target_raw')!=1000 or selection.get('target_canonical')!=999
            or selection.get('old_755_reference_preserved') is not True):
        raise ValueError('Frozen replacement selection differs from baseline')
    manifest=value.get('receipt_sha256')
    if not isinstance(manifest,dict) or not manifest:raise ValueError('Ordered receipt manifest required')
    receipts=[]
    for name,expected in sorted(manifest.items()):
        private(name)
        if sha(name)!=expected:raise ValueError('Replacement receipt changed')
        inputs[name]=expected;receipts.append(read_json(name))
    replacements=latest_fill(base,receipts,selection)
    snapshot_file=file('snapshot');loaded=load_snapshot(snapshot_file);snapshot=loaded.snapshot
    before=json.loads(json.dumps(base.to_dict()));after=json.loads(json.dumps(snapshot.to_dict()))
    if (snapshot.video!=base.video or snapshot.source_kind!=base.source_kind
            or snapshot.captured_at!=base.captured_at or snapshot.usage!=base.usage
            or after['comments']!=before['comments']+replacements
            or after['sampling']['method']!='registered-revalidated-latest-fill-v1'
            or len(snapshot.comments)!=1000 or len(sources(snapshot))!=999):
        raise ValueError('Current cohort, context, selection or bounded retention changed')
    old_reference_file=file('old_meaning_reference');old_reference=read_json(old_reference_file)
    samples_path=Path('runs/design-freeze-20261016/samples.json');samples=read_json(samples_path)
    if (old_reference_file.resolve()!=Path(samples['meaning_reference']).resolve()
            or sha(old_reference_file)!=samples['meaning_reference_sha256']
            or old_reference['snapshot_sha256']!=digest(original.snapshot.to_dict())):
        raise ValueError('Original frozen denominator reference changed')
    inputs[str(samples_path)]=sha(samples_path)
    reference_file=file('meaning_reference');reference=read_json(reference_file)
    utilization._validate_reference(snapshot,reference,digest(reference))
    original_rows={r['source_id']:r for r in old_reference['rows']}
    rows={r['source_id']:r for r in reference['rows']}
    if (set(rows)!=set(sources(snapshot)) or any(rows[sid]!=original_rows[sid] for sid in retained)
            or sum(r['eligibility']=='meaningful' for r in rows.values())!=755
            or any(r['eligibility']=='uncertain' for r in rows.values())):
        raise ValueError('Pre-output labels for unchanged sources and complete755 reference required')
    return snapshot,snapshot_file,inputs,{'file':str(path),'sha256':sha(path),
        'snapshot_file':str(snapshot_file),'snapshot_sha256':loaded.sha256,
        'meaning_reference_file':str(reference_file),'meaning_reference_sha256':sha(reference_file),
        'base_scope_refresh':base_proof,'data_revision':VERSION}
