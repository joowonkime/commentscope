'use strict';
let token = '', polling = false;
const $ = id => document.getElementById(id);
const kindLabel = {fact:'사실 주장',value:'가치·선호',prediction:'예측·가정'};
const evidenceLabel = {evidence_supported_provisional:'자료에서 지지됨 (잠정 판정)',
  attributed_value_not_verified_fact:'댓글의 가치 판단 · 사실 인증 아님',
  attributed_prediction_not_verified_fact:'댓글의 예측 · 사실 인증 아님'};
const jobLabel = {idle:'준비됨',running:'응답 생성 중',done:'완료',error:'실행 오류'};
const answerLabel = {answered:'답변',abstain:'근거 부족으로 보류',error:'실행 오류'};
function node(tag, text) { const n = document.createElement(tag); n.textContent = String(text); return n; }
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Content-Type': 'application/json', 'X-Session-Token': token},
    body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store'});
  const value = await response.json(); if (!response.ok) throw new Error(value.error); return value;
}
function fail(error) { $('status').textContent = '작업 실패: ' + error.message; }
function render(state, inventory = false) {
  $('status').textContent = `상태: ${jobLabel[state.job] || '확인 필요'} · 남은 질문 ${state.remaining_questions} · 근거가 없으면 답변 보류`;
  $('submit').disabled = !state.can_ask;
  if (inventory) {
    $('profiles').replaceChildren();
    for (const p of state.profiles) {
      const article = node('article', ''), check = document.createElement('input');
      article.className = 'profile';
      check.type = 'checkbox'; check.value = p.candidate_id; check.checked = state.selected.includes(p.candidate_id);
      const label = node('label', p.candidate_id + ' · 검사한 원문 중 핵심 지지 ' + p.model_core_support_count + '개 (모델 판정)');
      label.prepend(check); article.append(label);
      const entries = p.prompt_entries.slice().sort((a,b) => Number(b.claim_id===p.core_claim_id)-Number(a.claim_id===p.core_claim_id));
      for (const entry of entries) article.append(node('p', (entry.claim_id===p.core_claim_id?'핵심: ':'관련 근거: ')+entry.text+' ['+(kindLabel[entry.kind] || '유형 확인 필요')+']'));
      $('profiles').append(article);
    }
    $('deferred').replaceChildren(...state.deferred.map(p => node('p', p.candidate_id + ': ' + p.reason)));
  }
  $('rounds').replaceChildren();
  for (const r of state.rounds) {
    const section = node('section', ''); section.className = 'round'; section.append(node('h3', r.question));
    const answers = node('div', ''); answers.className = 'grid'; section.append(answers);
    for (const answer of r.answers) {
      const card = node('article', ''); card.append(node('h4', answer.candidate_id + ' · ' + (answerLabel[answer.status] || '상태 확인 필요')));
      card.className = 'answer';
      if (!answer.points.length) card.append(node('p', '허용된 근거에 답이 없어 보류합니다.'));
      for (const entry of [...answer.points, ...answer.required_premises]) {
        card.append(node('p', entry.text), node('small', `${evidenceLabel[entry.epistemic_status] || '근거 상태 확인 필요'} · 이 주장 지지 ${entry.member_source_count}개`));
        for (const [index,cite] of entry.citations.comment_evidence.entries()) {
          const b = node('button', '원문 ' + (index+1)); b.title = cite.source_id;
          b.type = 'button'; b.onclick = () => api('/api/source', {source_id: cite.source_id})
            .then(s => {
              let text = (s.id || cite.source_id)+'\n'+s.text;
              if (s.PARENT_CONTEXT_ONLY) text += '\n\n부모 댓글 · 문맥 참고\n'+s.PARENT_CONTEXT_ONLY.id+'\n'+s.PARENT_CONTEXT_ONLY.text;
              $('source').textContent = text;
            }).catch(fail); card.append(b);
        }
        for (const cite of entry.citations.verification_evidence) {
          const link = node('a', cite.title); const u = new URL(cite.url);
          if (u.protocol === 'https:') { link.href = u.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link); }
        }
      }
      answers.append(card);
    }
    $('rounds').append(section);
  }
  if (state.job === 'running' && !polling) { polling = true; setTimeout(poll, 750); }
}
async function poll() {
  polling = false;
  try { render(await api('/api/state')); } catch (error) { fail(error); }
}
async function create(ids) {
  const body = {initial_opinion: $('initial-opinion').value};
  if (ids) body.ids = ids;
  const state = await api('/api/session', body); token = state.token; render(state, true);
}
$('select').onclick = () => {
  const ids = Array.from($('profiles').querySelectorAll('input:checked')).map(x => x.value);
  if (ids.length > 2) return fail(new Error('관점은 최대 2개 선택하세요.'));
  create(ids).catch(fail);
};
$('ask').onsubmit = async event => {
  event.preventDefault(); $('submit').disabled = true;
  try { render(await api('/api/ask', {question: $('question').value, request_id: crypto.randomUUID()})); }
  catch (error) { fail(error); }
};
create().catch(fail);
