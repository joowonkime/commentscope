'use strict';
let token = '', polling = false;
const $ = id => document.getElementById(id);
function node(tag, text) { const n = document.createElement(tag); n.textContent = String(text); return n; }
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Content-Type': 'application/json', 'X-Session-Token': token},
    body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store'});
  const value = await response.json(); if (!response.ok) throw new Error(value.error); return value;
}
function fail(error) { $('status').textContent = '작업 실패: ' + error.message; }
function render(state, inventory = false) {
  $('status').textContent = `상태: ${state.job} · 남은 질문 ${state.remaining_questions} · 근거가 없으면 답변 보류`;
  $('submit').disabled = !state.can_ask;
  if (inventory) {
    $('profiles').replaceChildren();
    for (const p of state.profiles) {
      const article = node('article', ''), check = document.createElement('input');
      check.type = 'checkbox'; check.value = p.candidate_id; check.checked = state.selected.includes(p.candidate_id);
      const label = node('label', p.candidate_id + ' · 원문 지지 ' + p.model_core_support_count + '개 (모델 판정)');
      label.prepend(check); article.append(label);
      for (const entry of p.prompt_entries) article.append(node('p', entry.text + ' [' + entry.kind + ']'));
      $('profiles').append(article);
    }
    $('deferred').replaceChildren(...state.deferred.map(p => node('p', p.candidate_id + ': ' + p.reason)));
  }
  $('rounds').replaceChildren();
  for (const r of state.rounds) {
    const section = node('section', ''); section.append(node('h3', r.question));
    for (const answer of r.answers) {
      const card = node('article', ''); card.append(node('h4', answer.candidate_id + ' · ' + answer.status));
      if (!answer.points.length) card.append(node('p', '허용된 근거에 답이 없어 보류합니다.'));
      for (const entry of [...answer.points, ...answer.required_premises]) {
        card.append(node('p', entry.text), node('small', `${entry.epistemic_status} · 이 주장 지지 ${entry.member_source_count}개`));
        for (const cite of entry.citations.comment_evidence) {
          const b = node('button', '원문 ' + cite.source_id);
          b.type = 'button'; b.onclick = () => api('/api/source', {source_id: cite.source_id})
            .then(s => { $('source').textContent = s.text; }).catch(fail); card.append(b);
        }
        for (const cite of entry.citations.verification_evidence) {
          const link = node('a', cite.title); const u = new URL(cite.url);
          if (u.protocol === 'https:') { link.href = u.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link); }
        }
      }
      section.append(card);
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
  const state = await api('/api/session', ids ? {ids} : {}); token = state.token; render(state, true);
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
