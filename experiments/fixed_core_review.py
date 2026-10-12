"""Offline assistant development ratings. Never a runtime approval input."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write


def summarize(plan, report, ratings, plan_hash, report_hash):
    require_live(plan['expires_at'])
    if ratings['plan_sha256'] != plan_hash or ratings['report_sha256'] != report_hash:
        raise ValueError('Rating identity mismatch')
    if any(ratings.get(k) is not False for k in ['runtime_input','independent_gold','blinded']):
        raise ValueError('Development evaluation metadata required')
    cards = report['membership']['cards']
    expected = {c['core']['id'] for c in cards}
    if set(ratings['cards']) != expected:
        raise ValueError('Card coverage mismatch')
    reviewed = []
    for card in cards:
        label = ratings['cards'][card['core']['id']]
        if len(label['relations']) != len(card['relations']):
            raise ValueError('Relation coverage mismatch')
        rows = []
        for relation, rating in zip(card['relations'], label['relations']):
            if rating['source_id'] != relation['source_id'] or rating['verdict'] not in {'supported','partial','unsupported','unclear'} or not rating['reason'].strip():
                raise ValueError('Invalid source-bound rating')
            rows.append({**relation, 'assistant':rating})
        accepted = [r for r in rows if r['state']=='model_supported']
        bad = [r for r in accepted if r['assistant']['verdict']!='supported']
        reviewed.append({'core_id':card['core']['id'], 'text':card['core']['text'],
                         'source_count':len(accepted), 'bad_accepted_bindings':len(bad),
                         'faithful_model_card':bool(accepted) and not bad, 'relations':rows})
    large = [c for c in reviewed if c['source_count']>=3]
    all_rows = [r for c in reviewed for r in c['relations']]
    checks = {'faithful_ge3_card':any(c['faithful_model_card'] for c in large),
              'no_bad_ge3_bindings':all(c['bad_accepted_bindings']==0 for c in large),
              'inflation_three_source_core_retained':ratings['controls']['inflation_three_source_core_retained'],
              'contradicting_work_source_not_joined_to_no_work_claim':ratings['controls']['contradicting_work_source_not_joined_to_no_work_claim'],
              'zero_errors':report['summary']['errors']==0, 'zero_deferrals':report['summary']['deferrals']==0}
    if any(type(v) is not bool for v in checks.values()) or not ratings['controls']['reason'].strip():
        raise ValueError('Explicit control assessment required')
    return {'runtime_input':False, 'independent_gold':False, 'blinded':False,
            'plan_sha256':plan_hash, 'report_sha256':report_hash,
            'summary':{'cards':len(cards), 'cards_ge3':len(large),
                       'faithful_ge3_cards':sum(c['faithful_model_card'] for c in large),
                       'faithful_model_cards_all_sizes':sum(c['faithful_model_card'] for c in reviewed),
                       'assistant_labels':dict(Counter(r['assistant']['verdict'] for r in all_rows)),
                       'model_supported':sum(r['state']=='model_supported' for r in all_rows),
                       'bad_model_supported':sum(c['bad_accepted_bindings'] for c in reviewed),
                       'faithful_relations_retained':sum(r['state']=='model_supported' and r['assistant']['verdict']=='supported' for r in all_rows),
                       'checks':checks, 'eligible_for_reserved_trial':all(checks.values()),
                       'decision':'reserved_trial_candidate' if all(checks.values()) else 'stop_same_family_iterations',
                       'quality_gate_passed':False, 'agents':[]},
            'controls':ratings['controls'], 'cards':reviewed}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--run-dir',type=Path,required=True)
    args=ap.parse_args();root=args.run_dir
    plan,report,ratings=[read_json(root/name) for name in ['plan.json','report.json','assistant-ratings.json']]
    review=summarize(plan,report,ratings,sha(root/'plan.json'),sha(root/'report.json'))
    write(root/'assistant-review.json',review)
    esc=lambda x:html.escape(str(x),quote=True)
    out=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>고정 주장 개발 평가</title>',
         '<style>body{font:16px/1.65 system-ui;max-width:1100px;margin:auto;padding:24px}article{border-top:1px solid #aaa}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}</style>',
         '<h1>고정 주장·독립 가입: assistant 개발 평가</h1><p>비블라인드 사후 평가이며 독립 gold/서비스 승인/런타임 입력이 아닙니다.</p>',
         '<pre>'+esc(json.dumps(review['summary'],ensure_ascii=False,indent=2))+'</pre>']
    source={s['source_id']:s['text'] for s in plan['sources']}
    for card in review['cards']:
        out+=['<article><h2>'+esc(card['text'])+'</h2>']
        for row in card['relations']:
            out+=['<h3>'+esc(row['source_id'])+'</h3><blockquote>'+esc(source[row['source_id']])+'</blockquote>',
                  '<p>모델: '+esc(row['state'])+' / assistant: '+esc(row['assistant']['verdict'])+'</p>',
                  '<p>'+esc(row['assistant']['reason'])+'</p>']
        out.append('</article>')
    with (root/'assistant-review.html').open('x',encoding='utf-8') as f:f.write('\n'.join(out+['</html>']))
    print(json.dumps(review['summary'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
