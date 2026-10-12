"""Local, script-free results viewer. Rendering makes no model calls."""
import argparse
import html
from pathlib import Path

from commentscope.factory.claim_clusters import read_json, sha


def completed(directory):
    manifest = read_json(directory/'completed.json')
    if manifest['plan_sha256'] != sha(directory/'plan.json') or manifest['report_sha256'] != sha(directory/'report.json'):
        raise ValueError('Completed report binding changed')
    return read_json(directory/'plan.json'), read_json(directory/'report.json'), manifest


def render(fact_plan, fact_report, nli_report, answer_plan, answer_report, rounds):
    esc = lambda value: html.escape(str(value), quote=True)
    nli = {r['id']: r for r in nli_report['variants']['nli_only']['rows']}
    llm = {r['id']: r for r in fact_report['rows']}
    scores = {(r['question_id'], r['candidate_id']): r for r in answer_report['scores']}
    out = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           '<title>CommentScope MVP 부품 검증 결과</title>',
           '<style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:24px;color:#17212b}h1,h2{line-height:1.3}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #bbc5cf;vertical-align:top;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}.notice{background:#fff4d6;padding:16px;border-left:4px solid #a65e00}article{border:1px solid #bbc5cf;margin:16px 0;padding:16px}.good{color:#146c43}.bad{color:#a51d2d}</style>',
           '<h1>CommentScope MVP 부품 검증 결과</h1>',
           '<p class="notice">자동 MVP 전체 완료 화면이 아닙니다. 사실 검사는 실제 Kela 문서30사례와 합성 충돌10사례, 답변 검사는 직접 작성한 관점2개를 사용했습니다. 실제 댓글에서 자동 생성·검증된 에이전트는 아직0개입니다. 기대 판정은 assistant 개발 참조이며 독립 gold가 아닙니다.</p>',
           '<h2>사실 판정 비교</h2><table><tr><th>구성</th><th>지원 보존</th><th>비지원 오승인</th><th>개발 기준</th></tr>']
    for name, report, key in [('8B 생성형 판정', fact_report, 'fact_decision_development_gate_passed'),
                              ('로컬 NLI', nli_report['variants']['nli_only'], 'development_gate_passed'),
                              ('두 모델 판정 일치', nli_report['variants']['unanimous_llm_nli'], 'development_gate_passed')]:
        out.append('<tr><td>'+esc(name)+'</td><td>'+esc(report['supported_kept'])+'/10</td><td>'+esc(report['unsupported_false_support'])+'/30</td><td>'+('통과' if report[key] else '미달')+'</td></tr>')
    out += ['</table><p>동일40건으로 비교했습니다. threshold와 표본은 결과 확인 후 변경하지 않았습니다. 통과는 이 부품의 다음 통합 시험 조건이며 서비스 정확도 인증이 아닙니다.</p>',
            '<details><summary>40건 전체 판정과 자료 종류</summary><table><tr><th>검사 주장</th><th>참조</th><th>8B</th><th>NLI</th></tr>']
    for row in fact_plan['rows']:
        out.append('<tr><td>'+esc(row['claim']['text'])+'<br><small>'+esc(row['source_cohort'])+'</small></td><td>'+esc(row['expected'])+'</td><td>'+esc(llm[row['id']]['actual'])+'</td><td>'+esc(nli[row['id']]['actual'])+'</td></tr>')
    out += ['</table></details><h2>선택형 답변과 비교 지연</h2>',
            '<p>실제 로컬 모델이 허용 주장 ID만 선택하고, 프로그램이 저장된 주장과 인용을 그대로 표시합니다. 아래 두 관점은 합성 시험 입력이며 사용자 댓글을 대변하지 않습니다.</p><ul>']
    for cohort, label in [('answerable', '답변 가능'), ('unanswerable', '근거 부족 시 보류')]:
        count = answer_report['counts'][cohort]
        out.append('<li>'+label+': '+esc(count['passed'])+'/'+esc(count['total'])+'</li>')
    out += ['<li>2관점 비교20회 P95: '+esc(round(answer_report['comparison_p95_seconds'], 2))+'초</li></ul>',
            '<p>서버 준비 후 측정한 합성 입력 비교입니다. 실제 agent 지연이나 영상1000댓글의 첫 분석 시간을 뜻하지 않습니다.</p>']
    for row, round_ in zip(answer_plan['rows'], rounds, strict=True):
        out += ['<article><h3>'+esc(row['id'])+' · '+esc(row['text'])+'</h3><p>'+esc(round(round_['seconds'], 2))+'초</p>']
        for cid in ['P1', 'P2']:
            turn = round_['turns'][cid]
            passed = scores[(row['id'], cid)]['passed']
            out += ['<h4>'+esc(cid)+' · <span class="'+('good' if passed else 'bad')+'">'+('기대와 일치' if passed else '미달')+'</span></h4>',
                    '<p>'+esc(turn['status'])+' / '+esc(turn['answerability'])+' / '+esc(turn['limitation'])+'</p>']
            for point in turn['points']:
                out += ['<blockquote>'+esc(point['text'])+'</blockquote><p>'+esc(point['kind'])+' · 댓글 지지 '+esc(point['member_source_count'])+'개 · '+esc(point['epistemic_status'])+'</p>']
        out += ['</article>']
    return '\n'.join(out+['</html>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fact-dir', type=Path, required=True)
    parser.add_argument('--nli-dir', type=Path, required=True)
    parser.add_argument('--answer-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fact_plan, fact_report, _ = completed(args.fact_dir)
    _, nli_report, _ = completed(args.nli_dir)
    answer_plan, answer_report, manifest = completed(args.answer_dir)
    rounds = []
    for row in answer_plan['rows']:
        path = args.answer_dir/(row['id']+'.json')
        if manifest['rounds'][row['id']] != sha(path): raise ValueError('Question result changed')
        rounds.append(read_json(path))
    page = render(fact_plan, fact_report, nli_report, answer_plan, answer_report, rounds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream: stream.write(page)
    print({'output': str(args.output), 'new_model_calls': 0})


if __name__ == '__main__': main()
