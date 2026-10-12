"""Render hash-bound offline assistant ratings; never invokes a model or approves agents."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments.matched_factory_probe import verify

VERDICTS={'supported','partial','unsupported','unclear'}


def evaluate(report, ratings):
    """One rating per citation; metrics deduplicate same source within a statement."""
    cards={c['id']:c for v in ['V0','V1'] for c in report[v]['cards']}
    if set(cards)!=set(ratings):raise ValueError('Review must cover every generated card exactly')
    evaluated={}
    for cid,card in cards.items():
        r=ratings[cid]
        if set(r)!={'common','details','note'} or not isinstance(r['note'],str) or not r['note'].strip():
            raise ValueError('Invalid rating envelope')
        if not isinstance(r['details'],list) or len(r['details'])!=len(card['details']):
            raise ValueError('Detail coverage mismatch')
        pairs=[]
        for index,(statement,labels) in enumerate(zip([card['common'],*card['details']],[r['common'],*r['details']])):
            if not isinstance(labels,list) or len(labels)!=len(statement['evidence']):raise ValueError('Citation coverage mismatch')
            seen={}
            for citation,label in zip(statement['evidence'],labels):
                if not isinstance(label,str) or label not in VERDICTS:raise ValueError('Unknown semantic label')
                sid=citation['source_comment_id']
                if sid in seen:
                    if seen[sid]!=label:raise ValueError('Inconsistent duplicate-source rating')
                    continue
                seen[sid]=label
                pairs.append({'statement_index':index,'source_id':sid,'statement':statement['text'],'verdict':label})
        evaluated[cid]={'id':cid,'source_count':card['candidate_source_count'],'note':r['note'],'pairs':pairs,
                        'all_bindings_faithful':bool(pairs) and all(p['verdict']=='supported' for p in pairs)}
    summary={}
    for variant in ['V0','V1','V2']:
        ids=[c['id'] for c in report[variant]['cards']]
        rows=[evaluated[cid] for cid in ids]
        pairs=[p for r in rows for p in r['pairs']]
        good=[r for r in rows if r['all_bindings_faithful']]
        big=[r for r in rows if r['source_count']>=3]
        def stats(items):
            counts=dict(Counter(p['verdict'] for p in items))
            return {'count':len(items),'verdicts':counts,
                    'supported_fraction':None if not items else counts.get('supported',0)/len(items)}
        summary[variant]={'cards':len(rows),'cards_ge3':len(big),'all_bindings_faithful_cards':len(good),
            'all_bindings_faithful_cards_ge3':sum(r['source_count']>=3 for r in good),
            'common_bindings':stats([p for p in pairs if p['statement_index']==0]),
            'detail_bindings':stats([p for p in pairs if p['statement_index']>0]),
            'faithful_card_coverage_ge3':len({sid for c in report[variant]['cards'] if c['candidate_source_count']>=3
                and evaluated[c['id']]['all_bindings_faithful'] for sid in c['source_ids']}),
            'note':'Assistant source-fidelity readings, not independent gold, relevance approval, or factual validation.'}
    positive=negative=positive_kept=negative_accepted=0
    for row in report['V2']['records']:
        review={(p['statement_index'],p['source_id']):p for p in evaluated[row['card_id']]['pairs']}
        unique={}
        for pair in row['pairs']:
            key=(pair['statement_index'],pair['source_id'])
            unique[key]=pair
        if set(unique)!=set(review):raise ValueError('Audit/review binding mismatch')
        for key,pair in unique.items():
            good=review[key]['verdict']=='supported'; accepted=not pair['errors'] and pair['verdict']=='supported'
            positive+=good;negative+=not good;positive_kept+=good and accepted;negative_accepted+=not good and accepted
    keep={c['id'] for c in report['V2']['cards']}
    fully_good={cid for cid in [c['id'] for c in report['V1']['cards']] if evaluated[cid]['all_bindings_faithful']}
    return {'variants':summary,'audit':{'assistant_supported_bindings':positive,'model_kept_supported_bindings':positive_kept,
            'assistant_non_supported_or_unclear_bindings':negative,'model_false_supported_bindings':negative_accepted,
            'faithful_cards_kept':len(fully_good&keep),'faithful_cards_before':len(fully_good),
            'nonfaithful_cards_kept':len(keep-fully_good),
            'note':'Counts per card/statement/canonical source, not unique global inference requests.'},
            'cards':evaluated,'quality_gate_passed':False,'agents':[]}


def render(report, review, calibration_notes):
    esc=lambda s:html.escape(str(s),quote=True)
    counts={v:s['all_bindings_faithful_cards_ge3'] for v,s in review['variants'].items()}
    out=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>실제 비교와 assistant 원문 검토</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:24px}article{border-top:1px solid #aaa;margin:20px 0}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}blockquote{background:#f2f5fa;padding:12px}</style>',
         '<h1>실제64개 관점 카드 비교</h1><p>assistant의 비블라인드 개발 평가입니다. 사용자 개별 승인·독립 gold·서비스 품질 인증이 아닙니다. 원문이 그 내용을 말했는지 평가하며 사실 여부는 검증하지 않습니다.</p>',
         '<p>assistant 검토상 충실한3-source 이상 카드: '+esc(counts)+'. 자동 agent 승격 없이 실패 위치를 기록합니다. 작은 카드의 충실성과 제품 관련성도 별개입니다.</p>',
         '<p><a href="overview.html">모델 출력 전체 보기</a></p>',
         '<h2>실행 비용</h2><pre>'+esc(json.dumps(report['summary'],ensure_ascii=False,indent=2))+'</pre>',
         '<h2>가입·상세 근거 검토</h2><pre>'+esc(json.dumps({k:review[k] for k in ['variants','audit']},ensure_ascii=False,indent=2))+'</pre>']
    kept={c['id'] for c in report['V2']['cards']}
    for variant in ['V0','V1']:
        out.append('<h2>'+variant+'</h2>')
        for card in report[variant]['cards']:
            r=review['cards'][card['id']]
            out+=['<article id="'+esc(card['id'])+'"><h3>'+esc(card['id'])+' · distinct source '+str(r['source_count'])+'</h3>',
                  '<p>'+esc(r['note'])+'</p>']
            if variant=='V1':out.append('<p>V2 카드 유지: '+str(card['id'] in kept)+'</p>')
            for index,statement in enumerate([card['common'],*card['details']]):
                labels={p['source_id']:p['verdict'] for p in r['pairs'] if p['statement_index']==index}
                out.append('<h4>'+esc('common' if index==0 else statement['kind'])+': '+esc(statement['text'])+'</h4>')
                seen=set()
                for citation in statement['evidence']:
                    sid=citation['source_comment_id']
                    if sid in seen:continue
                    seen.add(sid)
                    out.append('<blockquote>'+esc(labels[sid])+' · '+esc(sid)+'\n'+esc(citation['quote'])+'</blockquote>')
            out.append('</article>')
    out.append('<h2>사전 선택12개 원문의 추출 진단</h2><p>별도 정답 정확도가 아니라 기존 정책 경계에 대한 사례 검토입니다.</p>')
    for note in calibration_notes:out.append('<p><strong>'+esc(note['id'])+'</strong> '+esc(note['note'])+'</p>')
    return '\n'.join(out+['</html>'])


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--run-dir',type=Path,required=True)
    args=ap.parse_args();root=args.run_dir
    verify(root);plan=read_json(root/'plan.json');require_live(plan['expires_at'])
    ratings=read_json(root/'assistant-ratings.json')
    if ratings['report_sha256']!=sha(root/'report.json') or ratings['plan_sha256']!=sha(root/'plan.json'):
        raise ValueError('Review inputs changed')
    if ratings['independent_gold'] is not False or ratings['runtime_input'] is not False:
        raise ValueError('Review must remain offline development interpretation')
    report=read_json(root/'report.json');review=evaluate(report,ratings['cards'])
    review.update({'reviewer':'conversation_assistant','blinded':False,'independent_gold':False,'runtime_input':False,
        'ratings_sha256':sha(root/'assistant-ratings.json'),'report_sha256':sha(root/'report.json'),
        'renderer_sha256':sha(__file__)})
    write(root/'assistant-review.json',review)
    with (root/'assistant-review.html').open('x',encoding='utf-8') as f:f.write(render(report,review,ratings['calibration_notes']))
    print(json.dumps({k:review[k] for k in ['variants','audit']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
