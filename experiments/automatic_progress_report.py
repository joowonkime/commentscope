"""Script-free private inspection of proposals and the fixed source gate."""
import argparse
import html
import json
from pathlib import Path
from commentscope.factory.claim_clusters import read_json
from commentscope.factory.scoped_discovery import verdict
from commentscope.storage import write_json_exclusive as write


def render(source,nli_directory,openjev_directory=None):
    plan=read_json(source/'plan.json');ref=read_json(source/'references.json')
    stop=read_json(source/'early-stopped.json')
    nli={r['id']:r['state'] for r in read_json(nli_directory/'result.json')['results']}
    jev={}
    if openjev_directory and (openjev_directory/'completed.json').exists():
        jev={r['id']:r['relation'] if not r['errors'] else 'error' for r in read_json(openjev_directory/'result.json')['results']}
    esc=lambda x:html.escape(str(x),quote=True)
    parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           '<title>CommentScope 자동 관점 생성 검증</title><style>body{font:16px/1.7 system-ui;max-width:1050px;margin:32px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #bbb;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #bbb;padding:20px 0}.bad{color:#a21d24}.notice{background:#fff3cd;padding:20px}</style>',
           '<h1>자동 관점 생성 검증</h1><p class="notice">자동 MVP 미완료. 실제 댓글에서 생성한 후보의 원문 충실성 검사입니다. 실패 결과를 제외하거나 합격 기준을 낮추지 않았습니다. 원문은 로컬 연구용이며 이 HTML을 공개 저장소에 올리지 마세요.</p>',
           '<h2>현재 결론</h2><p>8B 단독의 승인 정밀도 상한은 '+esc(f"{stop['llm_precision_best_possible']:.1%}")+
           ', DeBERTa와의 교집합 정상 보존율 상한은 '+esc(f"{stop['intersection_retention_best_possible']:.1%}")+
           '입니다. 각각 95%와 80% 기준을 통과할 수 없어 같은 구성의 남은 호출을 중단했습니다.</p>',
           '<p>고정 평가100건: assistant-supported21 / partial20 / unsupported59. 모델 실행 전 작성한 비블라인드 개발 참조이며 독립 gold가 아닙니다. runtime에는 전달하지 않습니다.</p>',
           '<p>LLM 관측68건에는 환경 중단으로 응답이 없던 오류1건이 포함됩니다. 미실행32건을 정상 거절이나 완료로 계산하지 않았습니다. 정상 참조21건을 모두 보존하는 최선의 경우도 위 상한을 넘지 못합니다.</p>',
           '<h2>형식 검증과 의미 검증은 다릅니다</h2><p>로컬 비교·후속 질문·원문 조회 화면과 입력 adapter는 구현됐지만, 원문 지지·유형·필수 전제의 의미 품질을 통과한 실제 에이전트는 아직 승인하지 않았습니다. 부품 테스트 성공을 MVP 완료로 대체하지 않습니다.</p>',
           '<h2>고정100건 판정표</h2><table><thead><tr><th>관계</th><th>사전 참조</th><th>8B</th><th>DeBERTa</th><th>OpenJev</th></tr></thead><tbody>']
    rows={r['id']:r for r in plan['rows']}
    saved={}
    for rid in plan['evaluation_ids']:
        path=source/(rid+'.json')
        item=read_json(path)['result'] if path.exists() else None
        saved[rid]=item;actual=verdict(item) if item else 'unexecuted'
        bad=actual=='supported' and ref['labels'][rid]!='supported'
        parts.append('<tr'+(' class="bad"' if bad else '')+'><td><a href="#'+rid+'">'+rid+'</a></td><td>'+esc(ref['labels'][rid])+'</td><td>'+esc(actual)+'</td><td>'+esc(nli[rid])+'</td><td>'+esc(jev.get(rid,'미완료'))+'</td></tr>')
    parts.append('</tbody></table><h2>원문과 판단 근거</h2>')
    for rid in plan['evaluation_ids']:
        row=rows[rid];record=saved[rid]
        parts.extend(['<article id="'+rid+'"><h3>'+rid+' · '+esc(row['candidate_id'])+'</h3>',
                      '<p>검사한 주장: '+esc(row['claim']['text'])+'</p>',
                      '<p>사전 판정: '+esc(ref['labels'][rid])+' — '+esc(ref['reasons'][rid])+'</p>',
                      '<details><summary>댓글 원문 전체</summary><pre>'+esc(row['text'])+'</pre></details>',
                      '<details><summary>모델 결과</summary><pre>'+esc(json.dumps(record,ensure_ascii=False,indent=2))+'</pre></details></article>'])
    return '\n'.join(parts+['</html>'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--source',type=Path,default=Path('runs/atomic-membership-20261013'))
    p.add_argument('--nli',type=Path,default=Path('runs/atomic-membership-nli-20261013'))
    p.add_argument('--openjev',type=Path,default=Path('runs/atomic-openjev-20261013'))
    a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as handle:handle.write(render(a.source,a.nli,a.openjev))
    print({'output':str(a.output),'new_model_calls':0},flush=True)
