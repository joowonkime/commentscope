"""Apply explicit assistant review without rewriting raw model results or approving agents."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import html
import os
from pathlib import Path

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.source_facets import assemble, validate
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive


def apply_review(records, review):
    if review.get('reviewer') != 'conversation_assistant' or review.get('human_approved') is not False:
        raise ValueError('Review origin must be explicit; no human approval')
    entries = review['entries']
    if len({e['id'] for e in entries}) != len(entries) or {e['id'] for e in entries} != {r['id'] for r in records}:
        raise ValueError('Review must cover all and only input sources exactly once')
    by_id = {e['id']: e for e in entries}; result = []
    for record in records:
        entry = by_id[record['id']]
        if not all(isinstance(entry.get(k), str) and entry[k].strip() for k in ['reason_ko','reading_ko','cautions_ko']):
            raise ValueError('Review rationale and faithful reading required')
        r = deepcopy(record); r['model_result'] = deepcopy(r['result']); r['review'] = deepcopy(entry)
        action = entry['decision']
        if action == 'confirm':
            if record['result']['errors'] or validate(record['result']['output'],record['source']):
                raise ValueError('Cannot confirm invalid output')
            if 'corrected' in entry: raise ValueError('Confirm cannot silently alter labels')
            output = deepcopy(record['result']['output'])
        elif action == 'correct':
            correction = entry['corrected']
            if set(correction) != {'topic_match','assertion_type','polarity'}:
                raise ValueError('Review only changes explicit label fields')
            output = {**correction,'assertion_quote':record['source']}
        elif action == 'abstain':
            output = {'topic_match':False,'assertion_type':'unclear','polarity':'unclear','assertion_quote':None}
        else:
            raise ValueError('Unknown review action')
        if validate(output,record['source']): raise ValueError('Invalid reviewed output')
        r['result'] = {'output':output,'errors':[],'raw':None,'origin':'assistant_review',
                       'human_approved':False,'semantic_status':'assistant_reviewed_not_independent_gold'}
        result.append(r)
    return result


def render(report):
    esc = lambda value: html.escape(str(value),quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>검수 루프 결과</title>',
        '<style>body{font:17px/1.7 system-ui;background:#f7f9fc;color:#172338;max-width:1050px;margin:30px auto;padding:20px}article,section{background:white;border:1px solid #d4deea;border-radius:10px;padding:18px;margin:16px 0}.note{background:#fff1d6;padding:16px}blockquote{background:#eef4fa;padding:14px;margin:10px 0}summary{cursor:pointer}small{color:#52627b}</style>',
        '<h1>내가 검수·수정한 주장 묶음</h1>',
        '<p class="note">로컬 모델 단독 성공이 아닙니다. 대화 assistant가 모든 원문을 읽고 판정을 확인·수정했습니다. 원래 모델 결과는 별도 보존됩니다. 사람 승인/독립 정답/논문용 성능 검증/에이전트 생성은 아직 아닙니다.</p>',
        '<p>'+esc(report['summary_ko'])+'</p>',
        '<p>묶음 제목은 공통된 주장 계열입니다. 댓글마다 다른 이유·조건·확신의 정도까지 같다는 뜻은 아닙니다. 원문 카드를 개별 근거로 보존합니다.</p>']
    records = {r['id']:r for r in report['reviewed_records']}
    def card(mid):
        r = records[mid]; e = r['review']; before = r['model_result']['output']; after = r['result']['output']
        return ('<article><h3>'+esc(mid)+' · '+esc(e['reading_ko'])+'</h3><p><strong>보존할 차이:</strong> '+esc(e['cautions_ko'])+
                '</p><details><summary>원문과 판정 근거</summary><blockquote>'+esc(r['source'])+'</blockquote><p>'+esc(e['reason_ko'])+
                '</p><p>모델: '+esc(before)+'<br>검수: '+esc(after)+'<br>처리: '+esc(e['decision'])+'</p></details></article>')
    for group in report['assembly']['groups']:
        parts.append('<section><h2>'+esc(group['title'])+' · '+str(len(group['members']))+'개</h2><p>'+
                     ('3개 미만 — 희소 주장으로 보존' if group['status']=='rare_preserved' else '검수된 묶음 제안 — 에이전트 승인은 아님')+'</p>')
        parts.extend(card(mid) for mid in group['members']); parts.append('</section>')
    parts.append('<section><h2>현재 묶음에서 보류한 댓글</h2><p>복합 주장·개인적 희망/목표·역사 설명·범위 밖 댓글입니다. 무의미하다는 판단이 아니며 장차 주장 분해가 필요할 수 있습니다.</p>')
    parts.extend(card(u['member_id']) for u in report['assembly']['unassigned']); parts.append('</section>')
    parts.append('<h2>실험 기록</h2><ul>')
    for note in report['experiment_notes_ko']: parts.append('<li>'+esc(note)+'</li>')
    parts.append('</ul><p>실제 댓글이 포함되어 공개 GitHub에 올리지 않습니다. 원문 보관 만료: '+esc(report['expires_at'])+'</p></html>')
    return '\n'.join(parts)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('snapshot'); p.add_argument('review'); p.add_argument('inputs',nargs='+')
    p.add_argument('--output',type=Path,required=True); args=p.parse_args()
    review=read_json(args.review); loaded=load_snapshot(args.snapshot); reports=[read_json(path) for path in args.inputs]
    expiry=loaded.snapshot.usage.expires_at
    if not expiry or datetime.fromisoformat(expiry.replace('Z','+00:00'))<=datetime.now(timezone.utc): raise ValueError('Snapshot expired')
    if review['input_sha256']!=[sha(path) for path in args.inputs]: raise ValueError('Review input binding changed')
    source_map={c.comment_id:c.text_original for c in loaded.snapshot.comments}; records=[]
    for report in reports:
        if report['snapshot_sha256']!=loaded.sha256 or report['expires_at']!=expiry: raise ValueError('Input provenance changed')
        for r in report['records']:
            if source_map.get(r['source_comment_id'])!=r['source']: raise ValueError('Source text changed')
        records.extend(report['records'])
    if len({r['id'] for r in records})!=len(records) or len({r['source_comment_id'] for r in records})!=len(records): raise ValueError('Duplicate source/member')
    if any(os.path.lexists(path) for path in [args.output,Path(str(args.output)+'.html')]): p.error('Output exists')
    reviewed=apply_review(records,review)
    report={'artifact_kind':'assistant-reviewed-source-facets-0.1','snapshot_sha256':loaded.sha256,'expires_at':expiry,
            'input_sha256':review['input_sha256'],'review_sha256':sha(args.review),'reviewer':review['reviewer'],
            'reviewed_records':reviewed,'assembly':assemble(reviewed),'model_evaluations':[r['evaluation'] for r in reports],
            'summary_ko':review['summary_ko'],'experiment_notes_ko':review['experiment_notes_ko'],
            'human_approved':False,'independent_gold':False,'accepted_perspectives':0}
    write_json_exclusive(args.output,report)
    with Path(str(args.output)+'.html').open('x',encoding='utf-8') as stream: stream.write(render(report))
    print(report['summary_ko'])


if __name__=='__main__': main()
