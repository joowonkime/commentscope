"""Private, script-free inspection of the bounded reasoning source gate."""
import argparse
import html
import json
from pathlib import Path
from commentscope.factory.claim_clusters import read_json
from commentscope.factory.scoped_discovery import verdict
from experiments.membership_checkpoint import checkpoint


def render(directory):
    status=checkpoint(directory);plan=read_json(directory/'plan.json')
    refs=read_json(Path(plan['reference_source'])/'references.json')
    esc=lambda x:html.escape(str(x),quote=True)
    title=('이번 구성은 기준 미달' if status['cannot_pass'] else
           '원문 관계 개발 기준 통과' if status['development_gate_passed'] else '원문 관계 검증 미완료')
    parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           '<title>CommentScope 추론 모드 검증 결과</title><style>body{font:16px/1.7 system-ui;max-width:1050px;margin:24px auto;padding:20px;color:#172c34}pre{white-space:pre-wrap;overflow-wrap:anywhere}.notice{background:#fff3cd;padding:16px}article{border-top:1px solid #ccc;padding:18px 0}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px;text-align:left}</style>',
           '<h1>추론 모드 원문 충실성 검증</h1><p class="notice">'+esc(title)+
           '. 자동 MVP 완료나 실제 에이전트 품질 승인이 아닙니다. 댓글 원문이 포함된 로컬 연구용 파일이므로 공개하지 마세요.</p>',
           '<p>동결된 평가100건 · 정상 지지21건 · assistant 개발 참조이며 독립 gold가 아닙니다. 참조는 모델 입력에 전달하지 않았습니다.</p>',
           '<table><tr><th>지표</th><th>결과</th></tr>']
    metrics=[('평가 관측',str(status['observed_evaluation'])+'/100'),
             ('지지 승인 관측',status['accepted_observed']),('올바른 승인 관측',status['true_accepted_observed']),
             ('오승인 관측',len(status['false_accepted_observed'])),('정상 지지 손실 관측',len(status['missed_positive_observed'])),
             ('정밀도 최선 상한',f"{status['precision_best_possible']:.1%}"),
             ('정상 보존율 최선 상한',f"{status['retention_best_possible']:.1%}")]
    parts += ['<tr><td>'+esc(k)+'</td><td>'+esc(v)+'</td></tr>' for k,v in metrics]
    parts += ['</table><p>기준: 승인 정밀도95% 이상, 정상 보존80% 이상. 미실행은 정상 거절이 아니며 부분 결과로 합격할 수 없습니다.</p>',
              '<p>256token 제한 추론, 전체 응답512tokens, full GPU/context4096. 같은 조건의 off 비교는 별도 실행이며 이 화면의 결과로 대체하지 않습니다.</p>',
              '<h2>고정100건 원문 대조</h2>']
    rows={r['id']:r for r in plan['rows']}
    for rid in plan['evaluation_ids']:
        row=rows[rid];path=directory/(rid+'.json')
        result=read_json(path)['result'] if path.exists() else None
        actual=verdict(result) if result else 'unexecuted'
        reason=result['output'].get('reason','') if result and isinstance(result['output'],dict) else ''
        parts += ['<article><h3>'+esc(rid)+' · '+esc(row['candidate_id'])+'</h3>',
                  '<p>검사한 주장: '+esc(row['claim']['text'])+'</p>',
                  '<p>사전 참조: '+esc(refs['labels'][rid])+' · 모델 판정: '+esc(actual)+'</p>',
                  '<p>참조 이유: '+esc(refs['reasons'][rid])+'</p>',
                  '<p>모델 최종 설명: '+esc(reason)+'</p>',
                  '<details><summary>댓글 원문 전체</summary><pre>'+esc(row['text'])+'</pre></details></article>']
    return '\n'.join(parts+['</html>'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();page=render(a.directory);a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as stream:stream.write(page)
    print({'output':str(a.output),'new_model_calls':0},flush=True)
