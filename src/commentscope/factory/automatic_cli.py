"""Build or query automatic agents without a manually reviewed input file."""
import argparse
from datetime import datetime, timezone
import html
import importlib.util
import json
from pathlib import Path

from commentscope.agents.profiles import require_live
from commentscope.agents.runtime import AgentSession, prompt_metadata
from commentscope.factory.automatic import Config, run, build_bundle, load_bundle
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive

REASONS = {
    'insufficient_neighbors_unverified': '유사 후보 부족 — 소수 관점인지 검색 누락인지는 미검증',
    'gate_budget_exhausted': '의미 검사 예산 소진',
    'no_accepted_group': '자동 기준을 통과한 묶음에 배정되지 않음',
    'unclear_mode': '주장 표현 유형 불확실',
    'extraction_failed': '추출 또는 출력 형식 검사 실패',
    'context_budget_exceeded': '원문·문맥 길이 상한 초과',
    'segmentation_limit': '원문 구간 수 상한 초과',
    'non_substantive': '모델이 실질적인 주장 없음으로 분류',
    'uncertain': '모델이 해석 불확실로 분류',
}


def render(report, bundle):
    esc = lambda value: html.escape(str(value), quote=True)
    counts = report['summary']
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>CommentScope 자동 에이전트 생성 결과</title>',
             '<style>body{font:16px/1.6 system-ui;max-width:1050px;margin:30px auto;padding:16px}article{border:1px solid #bbb;padding:18px;margin:16px 0}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#555}</style>',
             '<h1>댓글에서 자동 생성한 관점 에이전트</h1>',
             '<p>수동 검수 입력 없이 생성했습니다. 모델의 잠정 판정이며 독립 평가·의미 정확성 보장이 아닙니다. 에이전트 수는 고정하지 않습니다.</p>',
             '<h2>처리 범위와 미배정</h2>',
             '<p>입력 댓글 '+str(counts['source_count'])+'개 · 중복 제외 '+str(counts['canonical_sources'])+'개 중 '
             +str(counts['selected_sources'])+'개 선택 · 주장 후보 '+str(counts['claims'])+'개</p>',
             '<p><strong>잠정 에이전트 '+str(len(bundle['agents']))+'개</strong> · 반영된 원문 '+str(counts['covered_unique_sources'])
             +'개 (선택 표본의 '+format(counts['coverage_of_selected']*100, '.1f')+'%) · 미배정 주장 '+str(counts['unassigned_claims'])+'개</p>',
             '<p>의미 검사 '+str(counts['gate_decisions'])+'건 · 예산 소진 '+('있음' if counts['gate_budget_exhausted'] else '없음')+'</p>',
             '<details><summary>전체 처리 집계와 실패 상태</summary><pre>'+esc(json.dumps(counts, ensure_ascii=False, indent=2))+'</pre></details>']
    if not bundle['agents']:
        parts.append('<p>현재 설정에서 충분히 지지되는 관점을 확보하지 못했습니다. 사람의 승인을 기다리는 상태가 아니라 자동 보류 결과입니다.</p>')
    for agent in bundle['agents']:
        parts.append('<article><h2>'+esc(agent['agent_id'])+' · '+esc(agent['title'])+'</h2><p>서로 다른 원문 '+str(len(agent['evidence']))+'개</p>')
        for card in agent['evidence']:
            parts.append('<details><summary>'+esc(card['evidence_id'])+' · 배정 주장과 원문</summary><p>자동 추출한 주장 (원문 아님): '+esc(card['allowed_claim'])+'</p>')
            for span in card['support_spans']:
                parts.append('<blockquote>'+esc(span['text'])+'</blockquote>')
            parts.append('<details><summary>댓글 전체 문맥 (다른 주장을 근거로 승격하지 않음)</summary><pre>'+esc(card['original_text'])+'</pre></details></details>')
        parts.append('</article>')
    parts.append('<h2>에이전트로 만들지 않은 항목</h2>')
    sources = {r['source_comment_id']: r for r in report['records']}
    units = {u['claim_id']: u for u in report['units']}
    for item in bundle['non_agents']:
        unit = units.get(item['title'])
        parts.append('<details><summary>'+esc(item['title'])+' · '+esc(REASONS.get(item['reason'], item['reason']))+'</summary>')
        if unit:
            parts.append('<p>'+esc(unit['statement'])+'</p>')
            parts.extend('<blockquote>'+esc(p['text'])+'</blockquote>' for p in unit['spans'])
        elif item['title'] in sources:
            parts.append('<p>원문은 snapshot의 해당 source ID로 보존됩니다.</p>')
        parts.append('</details>')
    parts.append('<p>원문과 모델 출력이 포함된 비공개 연구 산출물입니다. 공개 GitHub에 올리지 마세요.</p></html>')
    return '\n'.join(parts)


def publish_text(path, text):
    # Exclusive creation, including protection against existing symlinks.
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build')
    build.add_argument('snapshot'); build.add_argument('--run-dir', type=Path, required=True)
    build.add_argument('--limit', type=int, default=1000)
    build.add_argument('--neighbors', type=int, default=8)
    build.add_argument('--min-similarity', type=float, default=0.55)
    build.add_argument('--max-gate-calls', type=int, default=2000)
    ask = commands.add_parser('ask')
    ask.add_argument('snapshot'); ask.add_argument('report'); ask.add_argument('bundle')
    ask.add_argument('--question', required=True); ask.add_argument('--output', type=Path, required=True)
    for command in [build, ask]:
        for name in ['model-label', 'model-revision', 'runtime']:
            command.add_argument('--'+name, required=True)
    args = parser.parse_args()
    metadata = {'model': args.model_label, 'model_revision': args.model_revision, 'runtime': args.runtime,
                'metadata_source': 'operator_supplied_not_attested'}
    if args.command == 'build':
        missing = [name for name in ['numpy', 'torch', 'sentence_transformers'] if importlib.util.find_spec(name) is None]
        if missing:
            parser.error('Missing clustering dependencies: '+', '.join(missing)+". Install this project with the [clustering] extra before model calls.")
        report_path = args.run_dir / 'report.json'
        bundle_path = args.run_dir / 'agents.json'
        html_path = args.run_dir / 'overview.html'
        if any(p.exists() or p.is_symlink() for p in [report_path, bundle_path, html_path]):
            parser.error('Completed output exists; choose a new run directory. Interrupted runs without final output can resume.')
        config = Config(limit=args.limit, neighbors=args.neighbors, min_similarity=args.min_similarity,
                        max_gate_calls=args.max_gate_calls)
        report = run(args.snapshot, args.run_dir, config, metadata=metadata,
                     progress=lambda p: print(json.dumps(p), flush=True))
        bundle = build_bundle(args.snapshot, report)
        require_live(bundle['expires_at'])
        write_json_exclusive(report_path, report)
        write_json_exclusive(bundle_path, bundle)
        publish_text(html_path, render(report, bundle))
        print(json.dumps({'summary': report['summary'], 'overview': str(html_path)}, ensure_ascii=False))
        return
    if args.output.exists() or args.output.is_symlink():
        parser.error('Output exists')
    if not args.question.strip() or len(args.question) > 1000:
        parser.error('Question must be 1..1000 characters')
    bundle = load_bundle(args.snapshot, args.report, args.bundle)
    result = {'artifact_kind': 'automatic-agent-question-0.1', 'bundle_sha256': sha(args.bundle),
              'created_at': datetime.now(timezone.utc).isoformat(), 'question': args.question,
              'metadata': metadata, 'prompts': prompt_metadata(), 'human_handling': False, 'answers': []}
    for agent in bundle['agents']:
        require_live(bundle['expires_at'])
        answer = AgentSession(agent).ask(args.question)
        write_json_exclusive(str(args.output)+'.'+agent['agent_id']+'.json', answer)
        result['answers'].append(answer)
        print(json.dumps({'agent': agent['agent_id'], 'status': answer['status']}), flush=True)
    require_live(bundle['expires_at'])
    # Recheck input binding after potentially long model execution before publishing the combined answer.
    if load_bundle(args.snapshot, args.report, args.bundle) != bundle:
        raise ValueError('Input changed during question execution')
    write_json_exclusive(args.output, result)
    print(json.dumps({'agents': len(bundle['agents']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
