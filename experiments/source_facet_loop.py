"""Run one frozen facet revision on a source-bound development or confirmation plan."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.source_facets import classify, assemble, REVISIONS, SCHEMA
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive


def evaluate(records, expectations):
    rows = []
    for r in records:
        e = expectations[r['id']]; v = r['result']['output']; valid = not r['result']['errors']
        rows.append({'id': r['id'], 'valid': valid,
                     'type_match': valid and v['assertion_type'] in e['allowed_types'],
                     'polarity_match': valid and v['polarity'] in e['allowed_polarities'],
                     'topic_match': valid and v['topic_match'] == e['topic_match']})
    return {'sources': len(rows), 'contract_pass': sum(r['valid'] for r in rows),
            'type_matches': sum(r['type_match'] for r in rows),
            'topic_matches': sum(r['topic_match'] for r in rows),
            'polarity_matches': sum(r['polarity_match'] for r in rows),
            'joint_matches': sum(r['type_match'] and r['topic_match'] and r['polarity_match'] for r in rows), 'rows': rows,
            'independent_gold': False, 'human_approved': False}


def render(report):
    esc = lambda t: html.escape(str(t), quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>원문 보존형 주장 계열</title>',
             '<style>body{font:17px/1.7 system-ui;max-width:1000px;margin:30px auto;padding:20px}article{border:1px solid #aaa;padding:18px;margin:16px 0}blockquote{background:#eef4fa;padding:12px}pre{white-space:pre-wrap}</style>',
             '<h1>원문 보존형 주장 계열 — '+esc(report['split'])+'</h1>',
             '<p>로컬 모델 출력으로 만든 미승인 제안입니다. 제목은 코드의 계열명이고 전체 댓글이 동일한 문장을 주장한다는 뜻은 아닙니다. 이유·조건은 원문 카드 전체에 보존됩니다. 사람 승인/agent 생성이 아닙니다.</p>',
             '<pre>'+esc(json.dumps(report['evaluation'],ensure_ascii=False,indent=2))+'</pre>']
    by_id = {r['id']: r for r in report['records']}
    for group in report['assembly']['groups']:
        parts.append('<h2>'+esc(group['title'])+' · '+str(len(group['members']))+'개</h2><p>'+esc(group['status'])+'</p>')
        for card in group['source_cards']:
            parts.append('<article><h3>'+esc(card['member_id'])+'</h3><blockquote>'+esc(card['text'])+'</blockquote><pre>'+esc(by_id[card['member_id']]['result']['output'])+'</pre></article>')
    parts.append('<h2>미배정 — 삭제하지 않음</h2>')
    for u in report['assembly']['unassigned']:
        r = by_id[u['member_id']]
        parts.append('<article><h3>'+esc(r['id'])+' · '+esc(u['reason'])+'</h3><blockquote>'+esc(r['source'])+'</blockquote><pre>'+esc(r['result']['output'])+'</pre></article>')
    return '\n'.join(parts+['</html>'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('snapshot'); p.add_argument('plan'); p.add_argument('--split', choices=['development','confirmation'], required=True)
    p.add_argument('--revision', choices=list(REVISIONS), required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model-label', required=True); p.add_argument('--model-revision', required=True); p.add_argument('--runtime', required=True)
    args = p.parse_args(); plan = read_json(args.plan); loaded = load_snapshot(args.snapshot)
    if loaded.sha256 != plan['snapshot_sha256']: raise ValueError('Snapshot changed')
    expiry = loaded.snapshot.usage.expires_at
    if not expiry or datetime.fromisoformat(expiry.replace('Z','+00:00')) <= datetime.now(timezone.utc): raise ValueError('Snapshot expired')
    by_id = {c.comment_id: c.text_original for c in loaded.snapshot.comments}
    selected = plan[args.split]
    dev_ids = {c['source_comment_id'] for c in plan['development']}
    test_ids = {c['source_comment_id'] for c in plan['confirmation']}
    if dev_ids & test_ids: raise ValueError('Split overlap')
    if not 1 <= len(selected) <= 24 or len({c['id'] for c in selected}) != len(selected): raise ValueError('Invalid selection')
    if len({c['source_comment_id'] for c in selected}) != len(selected): raise ValueError('Duplicate source')
    for c in selected:
        if c['source'] != by_id[c['source_comment_id']]: raise ValueError('Source changed')
    checkpoints = [Path(str(args.output)+f'.{i:02}.json') for i in range(len(selected))]
    if any(os.path.lexists(path) for path in [args.output,Path(str(args.output)+'.html'),Path(str(args.output)+'.manifest.json'),*checkpoints]): p.error('Output exists')
    report = {'artifact_kind': 'source-facet-loop-0.1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'snapshot_sha256': loaded.sha256, 'plan_sha256': sha(args.plan), 'expires_at': expiry,
              'split': args.split, 'revision': args.revision, 'system_prompt': REVISIONS[args.revision],
              'prompt_sha256': hashlib.sha256(REVISIONS[args.revision].encode()).hexdigest(), 'generation_schema': SCHEMA,
              'implementation_sha256': sha(Path(__file__).parents[1]/'src/commentscope/factory/source_facets.py'),
              'model': args.model_label, 'model_revision': args.model_revision, 'runtime': args.runtime,
              'metadata_source': 'operator_supplied_not_attested', 'request_settings': {'temperature':0,'seed':407,'max_tokens':3000},
              'human_approved': False, 'independent_gold': False, 'accepted_perspectives': 0, 'records': []}
    write_json_exclusive(str(args.output)+'.manifest.json', report)
    for c, checkpoint in zip(selected, checkpoints):
        # Expectations and other comments are never provided to the classifier.
        record = {k:c[k] for k in ['id','source_comment_id','source']}
        record['result'] = classify(c['source'], args.revision)
        write_json_exclusive(checkpoint, {**report,'records':[record],'checkpoint_only':True})
        report['records'].append(record)
        print(json.dumps({'completed':c['id'],'output':record['result']['output'],'errors':record['result']['errors']}),flush=True)
    report['assembly'] = assemble(report['records'])
    report['evaluation'] = evaluate(report['records'],{c['id']:c for c in selected})
    write_json_exclusive(args.output, report)
    with Path(str(args.output)+'.html').open('x',encoding='utf-8') as stream: stream.write(render(report))
    print(json.dumps(report['evaluation']),flush=True)


if __name__ == '__main__': main()
