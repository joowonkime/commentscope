'use strict';
// Source/model strings are rendered exclusively through textContent, never HTML.
const $ = id => document.getElementById(id);
let token = null, state = null, polling = null, lastRoundCount = -1, pending = null;
const errors = {
  inference_busy: '다른 질문을 처리 중입니다. 완료 후 다시 보내주세요.',
  question_limit: '이 대화의 질문 한도에 도달했습니다. 기록을 저장한 뒤 새 대화를 시작하세요.',
  invalid_question: '질문을 1~1,000자 이내로 입력해주세요.',
  session_missing: '세션을 찾을 수 없습니다. 페이지를 새로 열어주세요.',
  session_expired: '대화가 1시간 동안 사용되지 않아 만료됐습니다. 페이지를 새로 열어주세요.',
  dataset_expired: '댓글 사용 기한이 만료됐습니다. 데이터를 갱신하기 전에는 사용할 수 없습니다.',
  source_validation_failed: '원문·검수 파일이 변경됐거나 유효하지 않습니다. 서버 입력을 확인해주세요.',
  no_agents: '자동 생성 기준을 통과한 관점이 없습니다. 처리 범위와 미배정 결과를 확인하세요.',
  session_capacity: '열린 세션이 너무 많습니다. 기존 탭을 사용하거나 잠시 후 다시 시도하세요.',
  local_server_error: '로컬 서버 또는 기록 저장 오류입니다. 서버와 저장 경로를 확인해주세요.',
  round_failed_check_local_inputs_or_storage: '질문 처리를 완료하지 못했습니다. 원문 파일·사용 기한·저장 공간을 확인해주세요. 불완전한 답변은 표시하지 않았습니다.'
};
function el(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
async function api(path, body) {
  const headers = {}; if (token) headers['X-Session-Token'] = token;
  const options = {headers, cache: 'no-store'};
  if (body !== undefined) { options.method = 'POST'; headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
  const res = await fetch(path, options);
  if (!res.ok) { const data = await res.json(); const e = new Error(errors[data.error] || `요청 실패 (${res.status})`); e.code = data.error; throw e; }
  return res;
}
function citation(card) {
  const d = el('details', undefined, 'citation'); d.append(el('summary', `근거 ${card.evidence_id} · 원문 확인`));
  if (card.support_spans) {
    d.append(el('p', `자동 추출 주장 (원문 아님): ${card.allowed_claim}`));
    for (const span of card.support_spans) d.append(el('blockquote', span.text));
    const context = el('details'); context.append(el('summary', '댓글 전체 문맥 — 미배정 주장은 근거 아님'), el('blockquote', card.original_text)); d.append(context);
  } else d.append(el('blockquote', card.original_text), el('p', `검수자 해석 (직역 아님): ${card.reviewer_reading_ko}`));
  d.append(el('p', `보존할 차이: ${card.cautions_ko}`));
  try { const url = new URL(card.source_url); if (url.protocol === 'https:' && ['youtube.com', 'www.youtube.com', 'youtu.be'].includes(url.hostname)) { const a = el('a', 'YouTube 출처 ↗'); a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; d.append(a); } } catch (_) { /* No source link. */ }
  const p = card.parent_context;
  if (p.text !== null) d.append(el('p', '부모 댓글 — 문맥 전용, 이 에이전트의 주장 근거 아님'), el('blockquote', p.text));
  else if (p.comment_id) d.append(el('p', `부모 댓글 문맥: ${p.status}`));
  return d;
}
function renderProfiles() {
  $('profiles').replaceChildren();
  const automatic = state.bundle.human_handling === false;
  if (!state.bundle.agents.length) $('profiles').append(el('p', '자동 기준을 통과한 관점이 없습니다. 수동 승인을 기다리는 상태가 아니라 자동 보류 결과입니다.', 'empty'));
  for (const agent of state.bundle.agents) {
    const card = el('article', undefined, 'profile');
    card.append(el('p', agent.agent_id, 'eyebrow'), el('h3', agent.title), el('p', `근거 댓글 ${agent.evidence.length}개 · 독립 대화 상태`, 'hint'));
    const detail = el('details'); detail.append(el('summary', '관점 범위와 전체 근거'));
    const list = el('ul'); for (const c of agent.constraints) list.append(el('li', c)); detail.append(list);
    for (const source of agent.evidence) detail.append(citation(source));
    card.append(detail); $('profiles').append(card);
  }
  $('scope').textContent = `${automatic ? '자동 생성 잠정 관점' : '검수 지원 개발용'} ${state.bundle.agents.length}개 · 독립 품질 검증 전`;
  const meta = $('metadata'); meta.replaceChildren();
  meta.append(el('p', `수집 표본 ${state.bundle.dataset.sample_size}개 중 ${automatic ? '자동 처리 ' + state.bundle.dataset.processed_sources : '검수 ' + state.bundle.dataset.reviewed_sources}개. 전체 댓글을 모두 가져온 결과나 대표성 있는 표본이 아닙니다.`));
  meta.append(el('p', `댓글 사용 기한: ${state.bundle.expires_at}`));
  const list = el('ul'); for (const n of state.bundle.non_agents) list.append(el('li', `${n.title} · ${n.reason} · ${n.member_ids.join(', ')}`)); meta.append(list);
  meta.append(el('pre', JSON.stringify({dataset:state.bundle.dataset, runtime:state.runtime}, null, 2)));
}
const reasonLabels = {not_in_evidence:'이 관점의 댓글에 필요한 정보가 없습니다.', generation_or_contract_error:'모델 연결·생성 또는 출력 형식 문제입니다. 로컬 모델 서버 상태를 확인하세요.', audit_rejected_or_failed:'원문 검사에서 거절되거나 검사에 실패했습니다. 검사기의 과도한 거절일 수도 있습니다.', no_supported_answer:'검사된 답변을 확보하지 못했습니다.'};
function renderRounds() {
  if (lastRoundCount === state.rounds.length) return;
  lastRoundCount = state.rounds.length;
  const root = $('rounds'); root.replaceChildren();
  if (!state.rounds.length) { root.append(el('div', '질문을 보내면 관점별 답변과 인용 원문이 여기에 나란히 표시됩니다.', 'empty')); return; }
  state.rounds.forEach((round, i) => {
    const section = el('article', undefined, 'round'); section.append(el('p', `QUESTION ${String(i+1).padStart(2, '0')}`, 'eyebrow'), el('h3', round.question));
    const grid = el('div', undefined, 'grid');
    for (const turn of round.answers) {
      const ok = turn.status === 'model_audit_passed_development_only';
      const card = el('section', undefined, `answer${ok ? '' : ' abstain'}`);
      card.append(el('h3', state.bundle.agents.find(a => a.agent_id === turn.agent_id).title));
      card.append(el('p', ok ? '모델 근거 검사 통과 · 사람 승인 아님' : '답변 보류', 'status'));
      if (ok) { for (const point of turn.points) { const p = el('div', undefined, 'point'); p.append(el('p', point.text), citation(point.citation)); card.append(p); } if (turn.answerability === 'partial') card.append(el('p', '부분 답변: 이 관점의 댓글로 뒷받침되는 부분만 제시했습니다.', 'hint')); }
      else card.append(el('p', reasonLabels[turn.reason] || '근거가 확인된 답변을 제공하지 못했습니다.'));
      card.append(el('p', `생성 ${turn.generation_attempts}회 · 근거 검사 ${turn.audit_requests}회`, 'hint'));
      grid.append(card);
    }
    section.append(grid); root.append(section);
  });
}
function update(next, initial = false) {
  state = next;
  if (initial) { lastRoundCount = -1; renderProfiles(); }
  renderRounds();
  const job = state.job, running = job.status === 'running';
  $('ask').disabled = !state.can_ask; $('reset').disabled = running;
  $('export-html').disabled = $('export-json').disabled = running || !state.rounds.length;
  $('remaining').textContent = `남은 질문 ${state.remaining_questions} / 6`;
  $('progress').textContent = running ? `${job.agent_id || '세션'} · ${{starting:'질문 준비',generating:'답변 생성',auditing:'인용 원문 검사'}[job.stage] || job.stage} 중 · 모델 요청 ${job.model_calls}회 (속도에 따라 수 분 걸릴 수 있습니다)` : !state.can_ask && state.remaining_questions ? '다른 세션에서 모델을 사용 중입니다.' : job.status === 'done' ? '비교가 완료됐습니다. 근거 원문을 펼쳐 확인하세요.' : '질문을 입력해주세요.';
  if (job.status === 'error') showError(errors[job.error] || '처리 오류');
  if (pending && job.request_id === pending.request_id) { pending = null; $('question').value = ''; $('counter').textContent = '0 / 1000'; }
  clearTimeout(polling);
  if (!state.bundle.agents.length) $('progress').textContent = errors.no_agents;
  if (running || state.bundle.agents.length && !state.can_ask && state.remaining_questions) polling = setTimeout(refresh, 1000);
}
async function refresh() {
  try { update(await (await api('/api/state')).json()); $('reconnect').hidden = true; }
  catch (e) { $('ask').disabled = true; showError(e.message); $('reconnect').hidden = false; }
}
$('question').addEventListener('input', () => { $('counter').textContent = `${$('question').value.length} / 1000`; });
document.querySelectorAll('[data-question]').forEach(b => b.addEventListener('click', () => { $('question').value = b.dataset.question; $('question').dispatchEvent(new Event('input')); $('question').focus(); }));
$('question-form').addEventListener('submit', async e => {
  e.preventDefault(); showError(''); $('ask').disabled = true;
  const question = $('question').value;
  if (!pending || pending.question !== question) pending = {question, request_id: crypto.randomUUID()};
  try { update(await (await api('/api/ask', pending)).json()); }
  catch (err) { showError(err.message); $('reconnect').hidden = false; await refresh(); }
});
$('reconnect').addEventListener('click', async () => { showError(''); if (!token) await start(); else await refresh(); });
$('reset').addEventListener('click', async () => {
  if (!confirm('새 대화를 시작할까요? 필요한 결과는 먼저 저장하세요. 로컬 연구 기록 파일은 삭제되지 않습니다.')) return;
  try { const next = await (await api('/api/reset', {})).json(); token = next.token; pending = null; showError(''); update(next, true); }
  catch (e) { showError(e.message); }
});
for (const kind of ['html', 'json']) $('export-' + kind).addEventListener('click', async () => {
  try { const res = await api('/api/export.' + kind); const url = URL.createObjectURL(await res.blob()); const a = el('a'); a.href = url; a.download = `commentscope-private-${new Date().toISOString().replaceAll(':','-')}.${kind}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 10000); }
  catch (e) { showError(e.message); }
});
async function start() { try { const next = await (await api('/api/session', {})).json(); token = next.token; update(next, true); $('reconnect').hidden = true; } catch (e) { showError(e.message); $('reconnect').hidden = false; } }
start();
