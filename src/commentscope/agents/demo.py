"""Build/query source-bound development agents and export a comparison report."""
import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from commentscope.agents.profiles import build_bundle, load_bundle, require_live
from commentscope.agents.runtime import AgentSession, prompt_metadata, schema, AUDIT_SCHEMA
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive


def citation_html(card):
    esc=lambda v:html.escape(str(v),quote=True)
    parts=['<details class="citation"><summary>근거 '+esc(card['evidence_id'])+' · 원문 보기</summary>']
    if card.get('support_spans'):
        parts.append('<p>자동 추출 주장 (원문 아님): '+esc(card['allowed_claim'])+'</p>')
        parts.extend('<blockquote>'+esc(p['text'])+'</blockquote>' for p in card['support_spans'])
        parts.append('<details><summary>댓글 전체 문맥 — 미배정 주장은 근거 아님</summary><blockquote>'+esc(card['original_text'])+'</blockquote></details>')
    else:
        parts += ['<blockquote>'+esc(card['original_text'])+'</blockquote>',
                  '<p><strong>검수자 해석 (직역 아님):</strong> '+esc(card['reviewer_reading_ko'])+'</p>']
    parts.append('<p><strong>보존할 차이:</strong> '+esc(card['cautions_ko'])+'</p>')
    url=card.get('source_url') or ''; parsed=urlparse(url)
    if parsed.scheme=='https' and parsed.hostname in ['youtube.com','www.youtube.com','youtu.be']:
        parts.append('<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">YouTube 출처</a>')
    parent=card['parent_context']
    if parent['text'] is not None:
        parts.append('<p>부모 댓글 — 문맥 전용, 이 에이전트의 주장 근거 아님</p><blockquote>'+esc(parent['text'])+'</blockquote>')
    elif parent['comment_id']:
        parts.append('<p>부모 댓글 문맥: '+esc(parent['status'])+'</p>')
    return '\n'.join(parts+['</details>'])


def render(report):
    esc=lambda v:html.escape(str(v),quote=True)
    bundle=report['bundle']; profiles={a['agent_id']:a for a in bundle['agents']}
    parts=['<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CommentScope · 관점 에이전트 비교</title>',
        '<style>body{font:17px/1.65 system-ui;background:#f3f6fb;color:#18243c;max-width:1250px;margin:24px auto;padding:20px}h1,h2,h3{line-height:1.4}.banner{background:#fff0cc;padding:18px;border-radius:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:18px}article,section{background:white;border:1px solid #d7dfec;border-radius:12px;padding:20px;margin:18px 0}article{margin:0}blockquote{background:#edf3fb;padding:12px;margin:10px 0;font-size:15px}.citation{border-left:3px solid #5483b7;padding:12px;margin:12px 0}summary{cursor:pointer}small,.muted{color:#5a6880}pre{white-space:pre-wrap;overflow-wrap:anywhere}nav a{display:inline-block;padding:8px}a{color:#175baa}.status{font-size:14px;color:#765400}</style></head><body>',
        '<h1>CommentScope · 관점에서 질문하기</h1>',
        '<p class="banner"><strong>연구용 에이전트 비교</strong><br>'+('수동 검수 입력 없이 자동 생성한 잠정 관점입니다.' if bundle.get('human_handling') is False else '검수 지원 묶음에서 생성한 미승인 에이전트입니다.')+' 답변은 같은 로컬 모델의 별도 요청으로 검사하며 독립 검증은 아닙니다. 검사 통과도 의미 정확성을 보장하지 않습니다. 보류된 초안은 답변으로 표시하지 않습니다.</p>',
        '<p>댓글 → 근거가 연결된 묶음 → 프로필 → 독립 응답 → 근거 검사 → 비교·출처 확인</p>',
        '<div class="grid">']
    for agent in bundle['agents']:
        parts.append('<article><h2>'+esc(agent['agent_id'])+' · '+esc(agent['title'])+'</h2><p>자기 근거 '+str(len(agent['evidence']))+'개만 접근 · 대화 상태 분리</p><details><summary>관점 범위와 전체 근거</summary><ul>')
        parts.extend('<li>'+esc(v)+'</li>' for v in agent['constraints'])
        parts.append('</ul>'); parts.extend(citation_html(c) for c in agent['evidence']); parts.append('</details></article>')
    parts.append('</div><nav>')
    parts.extend('<a href="#q'+str(i)+'">질문 '+str(i)+'</a>' for i in range(1,len(report['rounds'])+1)); parts.append('</nav>')
    for i,round_ in enumerate(report['rounds'],1):
        parts.append('<section id="q'+str(i)+'"><h2>질문 '+str(i)+'. '+esc(round_['question'])+'</h2><div class="grid">')
        for turn in round_['answers']:
            agent=profiles[turn['agent_id']]
            parts.append('<article><h3>'+esc(agent['title'])+'</h3>')
            if turn['status']=='model_audit_passed_development_only':
                parts.append('<p class="status">근거 검사 통과한 개발용 답변 · 사람 승인/독립 검증 아님</p>')
                for point in turn['points']:
                    parts.append('<p>'+esc(point['text'])+'</p>'+citation_html(point['citation']))
                if turn['answerability']=='partial':
                    parts.append('<p class="muted">부분 답변: 이 관점의 댓글로 뒷받침되는 부분만 제시했습니다. 모델이 작성한 미검사 설명은 최종 답변에 포함하지 않습니다.</p>')
            else:
                parts.append('<p>답변 보류: 이 관점의 근거만으로 검사된 답변을 제공하지 못했습니다.</p><small>사유: '+esc(turn['reason'])+'</small>')
            parts.append('<p class="muted">생성 시도 '+str(len(turn['attempts']))+'회 · 검사 요청 '+str(sum(len(a['audit']) for a in turn['attempts']))+'회</p></article>')
        parts.append('</div></section>')
    parts.append('<section><h2>에이전트로 만들지 않은 항목</h2><p>희소·복합·기타·범위 밖 주장은 삭제하거나 주요 관점으로 승격하지 않았습니다.</p><ul>')
    for item in bundle['non_agents']:
        parts.append('<li>'+esc(item['title'])+' · '+esc(item['reason'])+' · '+esc(', '.join(item['member_ids']))+'</li>')
    parts.append('</ul><details><summary>데이터 범위·재현 정보</summary><pre>'+esc(json.dumps(bundle['dataset'],ensure_ascii=False,indent=2))+'</pre><p>만료: '+esc(bundle['expires_at'])+'</p><pre>'+esc(json.dumps(report['runtime'],ensure_ascii=False,indent=2))+'</pre></details></section>')
    parts.append('<p>현재는 저장된 질문·답변 비교 화면입니다. 새 질문은 README의 ask 명령으로 실행합니다. 웹 채팅 서버나 에이전트 간 토론은 아직 구현하지 않았습니다. 원시 초안·검사 기록은 비공개 JSON에 보존됩니다.</p></body></html>')
    return '\n'.join(parts)


def main():
    parser=argparse.ArgumentParser(description=__doc__); commands=parser.add_subparsers(dest='command',required=True)
    for name in ['build','ask']:
        p=commands.add_parser(name); p.add_argument('snapshot'); p.add_argument('reviewed')
        if name=='ask':
            p.add_argument('bundle'); p.add_argument('--question',action='append',required=True)
            p.add_argument('--model-label',required=True); p.add_argument('--model-revision',required=True); p.add_argument('--runtime',required=True)
        p.add_argument('--allow-unapproved',action='store_true'); p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if os.path.lexists(args.output): parser.error('Output exists; choose a new path')
    if args.command=='build':
        bundle=build_bundle(args.snapshot,args.reviewed,allow_unapproved=args.allow_unapproved)
        write_json_exclusive(args.output,bundle)
        print(json.dumps({'development_agents':len(bundle['agents']),'accepted_perspectives':0,'output':str(args.output)})); return
    if not 1<=len(args.question)<=6 or any(not q.strip() or len(q)>1000 for q in args.question): parser.error('Use 1..6 questions, each 1..1000 characters')
    bundle=load_bundle(args.snapshot,args.reviewed,args.bundle,allow_unapproved=args.allow_unapproved)
    checkpoints=[Path(str(args.output)+f'.q{i:02}-{a["agent_id"]}.json') for i in range(1,len(args.question)+1) for a in bundle['agents']]
    extra=[Path(str(args.output)+'.html'),Path(str(args.output)+'.manifest.json'),*checkpoints]
    if any(os.path.lexists(path) for path in extra): parser.error('Output/checkpoint exists; choose new paths')
    sessions=[AgentSession(agent) for agent in bundle['agents']]
    report={'artifact_kind':'development-agent-comparison-0.1','created_at':datetime.now(timezone.utc).isoformat(),
            'bundle_sha256':sha(args.bundle),'bundle':bundle,'expires_at':bundle['expires_at'],
            'runtime':{'model':args.model_label,'model_revision':args.model_revision,'runtime':args.runtime,
                       'metadata_source':'operator_supplied_not_attested','temperature':0,'seed':407,'max_tokens':1200,
                       'max_generation_attempts':2,'max_session_questions':6},
            'prompts':prompt_metadata(),'code_sha256':sha(Path(__file__).with_name('runtime.py')),
            'generation_schemas':{a['agent_id']:schema([c['evidence_id'] for c in a['evidence']]) for a in bundle['agents']},
            'auditor_schema':AUDIT_SCHEMA,'generation_contract':'answerability-branches-0.2',
            'human_approved':False,'accepted_perspectives':0,'rounds':[]}
    write_json_exclusive(str(args.output)+'.manifest.json',{**report,'questions':args.question})
    for i,question in enumerate(args.question,1):
        require_live(bundle['expires_at']); round_={'question':question,'answers':[]}
        for session in sessions:
            turn=session.ask(question); round_['answers'].append(turn)
            checkpoint=Path(str(args.output)+f'.q{i:02}-{session.profile["agent_id"]}.json')
            write_json_exclusive(checkpoint,{'bundle_sha256':report['bundle_sha256'],'expires_at':bundle['expires_at'],'turn':turn})
            print(json.dumps({'question':i,'agent':turn['agent_id'],'status':turn['status'],'attempts':len(turn['attempts'])}),flush=True)
        report['rounds'].append(round_)
    report['summary']={'agents':len(sessions),'questions':len(args.question),
                       'model_audit_passed':sum(t['status']=='model_audit_passed_development_only' for r in report['rounds'] for t in r['answers']),
                       'abstained':sum(t['status']=='abstain' for r in report['rounds'] for t in r['answers']),
                       'accepted_perspectives':0}
    write_json_exclusive(args.output,report)
    with Path(str(args.output)+'.html').open('x',encoding='utf-8') as stream: stream.write(render(report))
    print(json.dumps(report['summary']),flush=True)


if __name__=='__main__': main()
