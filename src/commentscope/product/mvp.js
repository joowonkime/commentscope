'use strict';
const $ = id => document.getElementById(id);
const state = {analysis:null, session:null, token:'', room:null, roomTimer:null, selected:new Set(), context:new Set(), reflectionJob:null, reflectionResult:null, saved:null, roomFilter:'all', openingPending:false};
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const requestId = () => crypto.randomUUID();
const savedSessionKey = 'commentscope-mvp-session';
const tabSessionKey = 'commentscope-mvp-active-tab';
const librarySessionsKey = 'commentscope-mvp-library-sessions';
const libraryDestinationKey = 'commentscope-mvp-library-destination';
const selectedAnalysisKey = 'commentscope-mvp-selected-analysis';
let libraryLoad = 0;
let currentViewEdited = false;
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)setText(n,text); if(cls)n.className=cls; return n; }
// Bind UI copy and registered presentation fields explicitly. Evidence and user text stay verbatim.
let interfaceLanguage = 'en';
let koreanInterface = {};
const textBindings = new WeakMap();
const attributeBindings = new WeakMap();
const languagePreference = 'commentscope-interface-language';

function msg(key, ...values) { return {key, values}; }
function joinText(parts, separator = ' · ') { return {parts, separator}; }
function formatText(value) {
  if (typeof value !== 'object' || value === null) return String(value ?? '');
  if (Object.hasOwn(value, 'original')) return value.translation?.[interfaceLanguage] ?? value.original;
  if (value.parts) return value.parts.map(formatText).join(value.separator);
  const pattern = interfaceLanguage === 'ko' ? (koreanInterface[value.key] ?? value.key) : value.key;
  return pattern.replace(/\{(\d+)\}/g, (_, index) => formatText(value.values[index]));
}
function uiTextNode(value) {
  const text = document.createTextNode(formatText(value));
  if (value && typeof value === 'object') textBindings.set(text, value);
  return text;
}
function setText(element, value) {
  if (value && typeof value === 'object') element.replaceChildren(uiTextNode(value));
  else element.textContent = value ?? '';
}
function setLabel(element, attribute, value) {
  let bindings = attributeBindings.get(element);
  if (!bindings) { bindings = new Map(); attributeBindings.set(element, bindings); }
  bindings.set(attribute, value);
  element.setAttribute(attribute, formatText(value));
}
function browserLanguage() {
  for (const tag of navigator.languages || [navigator.language]) {
    const language = tag.toLowerCase().split('-')[0];
    if (language === 'ko' || language === 'en') return language;
  }
  return 'en';
}
function refreshBoundText() {
  const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let item = walker.nextNode(); item; item = walker.nextNode()) {
    const text = textBindings.get(item);
    if (text) item.nodeValue = formatText(text);
    for (const [attribute, value] of attributeBindings.get(item) || []) item.setAttribute(attribute, formatText(value));
  }
}
function applyInterfaceLanguage(language) {
  const opening = $('opening-question');
  const useSuggested = opening.hasAttribute('data-suggested') && !opening.readOnly
    && opening.value === formatText(msg(defaultOpeningQuestion));
  interfaceLanguage = language;
  document.documentElement.lang = language;
  refreshBoundText();
  updatePerspectiveLanguageNote();
  for (const select of document.querySelectorAll('.interface-language')) select.value = language;
  if (useSuggested) opening.value = formatText(msg(defaultOpeningQuestion));
  if (state.session && $('room-search').value) renderRooms();
}
function installInterfaceLanguage() {
  koreanInterface = JSON.parse($('interface-copy').textContent);
  const selector = $('interface-language');
  for (const header of document.querySelectorAll('dialog > header, #chat-picker > header')) {
    const copy = selector.cloneNode(true);
    copy.removeAttribute('id');
    header.insertBefore(copy, header.lastElementChild);
  }
  // Only the initial, authored HTML participates in this lookup.
  const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
  for (let text = walker.nextNode(); text; text = walker.nextNode()) {
    if (text.parentElement.closest('script,style,select.interface-language')) continue;
    const literal = text.nodeValue, key = literal.trim();
    if (Object.hasOwn(koreanInterface, key)) {
      const start = literal.indexOf(key);
      textBindings.set(text, joinText([literal.slice(0, start), msg(key), literal.slice(start + key.length)], ''));
    }
  }
  for (const element of document.querySelectorAll('[aria-label],[placeholder],[title],[alt]')) {
    for (const name of ['aria-label', 'placeholder', 'title', 'alt']) {
      const key = element.getAttribute(name);
      if (key && Object.hasOwn(koreanInterface,key)) setLabel(element, name, msg(key));
    }
  }
  let language = browserLanguage();
  try {
    const saved = localStorage.getItem(languagePreference);
    if (saved === 'ko' || saved === 'en') language = saved;
  } catch {}
  applyInterfaceLanguage(language);
  for (const select of document.querySelectorAll('.interface-language')) {
    select.addEventListener('change', () => {
      applyInterfaceLanguage(select.value);
      try { localStorage.setItem(languagePreference, interfaceLanguage); } catch {}
    });
  }
  window.addEventListener('storage', event => {
    if (event.key === languagePreference) {
      applyInterfaceLanguage(['ko','en'].includes(event.newValue) ? event.newValue : browserLanguage());
    }
  });
}


function interfaceNotice(text) {
  return typeof text === 'string' && Object.hasOwn(koreanInterface,text) ? msg(text) : text;
}

// A field is bound to its registered analysis, claim/name ID and exact source wording.
const perspectiveFields = new WeakMap();
let translationCatalog, translationFrame;

function refreshTranslatedText() {
  if (translationFrame) return;
  translationFrame = requestAnimationFrame(() => {
    translationFrame = null;
    refreshBoundText();
    updatePerspectiveLanguageNote();
  });
}

function updatePerspectiveLanguageNote() {
  const note = $('perspective-language-note');
  const registered = state.analysis && perspectiveFields.get(state.analysis);
  const fields = registered ? [...registered.values()] : [];
  const missing = fields.some(field => field.missing && field.sourceLanguage !== interfaceLanguage);
  note.hidden = !missing && !fields.some(field => field.translation?.[interfaceLanguage]);
  if (note.hidden) return;
  setText(note, missing ? msg("Some perspective text is shown in its original language.")
    : msg("Perspectives are translated. Source comments open in their original language."));
}

function presentationCatalog() {
  translationCatalog ??= fetch('/mvp/perspective-translations.json').then(response => {
    if (!response.ok) throw new Error('Presentation catalog unavailable');
    return response.json();
  }).catch(error => {
    translationCatalog = undefined;
    throw error;
  });
  return translationCatalog;
}

async function resolvePerspectiveText(analysis, key, field) {
  try {
    const catalog = await presentationCatalog();
    const record = catalog[analysis.analysis_id];
    const entry = record?.fields?.[key];
    field.sourceLanguage = entry?.source_language ?? record?.source_language;
    const target = field.sourceLanguage === 'en' ? 'ko' : 'en';
    if (entry?.sha256 && typeof entry[target] === 'string' && entry[target].trim() && crypto.subtle) {
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(field.original));
      const digest = Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, '0')).join('');
      if (entry.sha256 === digest) field.translation = {[target]:entry[target]};
    }
  } catch { /* The registered source wording is always available. */ }
  field.missing = !field.translation;
  if (state.analysis === analysis) refreshTranslatedText();
}

function presentationText(key, original) {
  const analysis = state.analysis;
  if (!analysis?.analysis_id || !key || !original) return original;
  let fields = perspectiveFields.get(analysis);
  if (!fields) {
    fields = new Map();
    perspectiveFields.set(analysis, fields);
  }
  let field = fields.get(key);
  if (!field || field.original !== original) {
    field = {original};
    fields.set(key, field);
    void resolvePerspectiveText(analysis, key, field);
  }
  return field;
}

function perspectiveName(view) { return presentationText('name:' + view.id, view.display_name || view.text); }
function claimText(id, text) { return id ? presentationText('claim:' + id, text) : text; }
function referencedClaim(view, claim) {
  const original = claim.claim_id === view.core_claim_id ? view.text
    : view.grounds?.find(ground => ground.claim_id === claim.claim_id)?.text;
  return original === claim.text ? claimText(claim.claim_id, original) : claim.text;
}

function asset(name) { const img=node('img'); img.src='/mvp/assets/'+name+'.svg'; img.alt=''; return img; }
function status(text) { setText($('status'), interfaceNotice(text)); }
function errorText(code) { return ({revision_conflict:"The record changed. Review the latest version and try again.",opinion_revision_conflict:"Your opinion changed. Review it and try again.",analysis_revision_conflict:"Your opinion or analysis changed. Review the suggestions again or save your own reflection.",resource_busy:"A debate is already in progress. Open its record to follow it.",debate_not_ready:"This debate cannot restart in its current state.",capacity_hold:"The evidence exceeds the verification limit. Published turns are saved.",room_not_ready:"Wait for the current response or pause the conversation before asking.",budget_exhausted:"The AI budget has been reached. You can read existing conversations and save a reflection manually.",cycle_deadline:"The AI session has ended. You can still read and save manually.",unconfirmed_provider_call:"The operator is checking an interrupted AI call and its charge. You can read original comments and save a reflection while waiting.",reconcile_required:"The operator is reviewing an AI request. You can read original comments or write and save in Reflect.",source_expired:"The source evidence has expired.",session_capacity:"All review sessions are in use. Open a saved record in Library, or start again when a place opens.",session_expired:"This session has expired. Start a new one.",invalid_participants:"Choose at least one available perspective.",turn_limit:"This conversation has reached its turn limit.",context_capacity:"Select up to 24 related messages.",queue_capacity:"Other work is in progress. Try again shortly.",model_or_validation_failed:"The AI response could not be completed. Your input and previous records are saved."})[code] || "The request could not be completed. Check your input and previous records."; }
async function api(path, method='GET', body, token=state.token) {
  const headers={}; if(token)headers['X-Session-Token']=token;
  if(body!==undefined)headers['Content-Type']='application/json';
  const response=await fetch('/api/v1'+path,{method,headers,...(body===undefined?{}:{body:JSON.stringify(body)})});
  const value=await response.json();
  if(!response.ok){const e=new Error(errorText(value.error?.code||value.error)); e.code=value.error?.code||value.error; throw e;}
  return value;
}
function base(){return '/sessions/'+state.session.session_id;}

async function retryableWrite(slot, path, method, fields, prepareRevision) {
  const key = 'commentscope-mvp-pending-' + slot;
  const bytes = new TextEncoder().encode(JSON.stringify([method, path, fields]));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const fingerprint = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  const creatingSession = path === '/sessions';
  let attempt = readStored(sessionStorage, key);
  if (attempt?.fingerprint !== fingerprint || !attempt.requestId || (creatingSession && !attempt.token)
      || (prepareRevision && !Number.isInteger(attempt.expectedRevision))) {
    attempt = {fingerprint, requestId: requestId()};
    if (prepareRevision) {
      const revision = await prepareRevision();
      if (revision === null) return;
      attempt.expectedRevision = revision;
    }
    if (creatingSession) {
      const random = crypto.getRandomValues(new Uint8Array(32));
      attempt.token = btoa(String.fromCharCode(...random)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }
    sessionStorage.setItem(key, JSON.stringify(attempt));
  }
  const payload = {...fields, request_id: attempt.requestId};
  if (prepareRevision) payload.expected_revision = attempt.expectedRevision;
  let value;
  try {
    value = await api(path, method, payload, creatingSession ? attempt.token : state.token);
  } catch (error) {
    if (prepareRevision && ['revision_conflict','room_not_ready'].includes(error.code)
        && readStored(sessionStorage, key)?.requestId === attempt.requestId) sessionStorage.removeItem(key);
    if (error instanceof TypeError) throw new Error("The response could not be confirmed. Resend the same input to check the original request.");
    throw error;
  }
  if (creatingSession) state.token = attempt.token;
  if (readStored(sessionStorage, key)?.requestId === attempt.requestId) sessionStorage.removeItem(key);
  return value;
}
function indexOf(id){return state.analysis.perspectives.findIndex(p=>p.id===id);}
function perspective(id){return state.analysis.perspectives.find(p=>p.id===id);}
function label(id){if(state.room?.kind==='synthesis_chat'&&state.room.participant_ids?.includes(id))return msg("Consensus agent");const p=perspective(id);return p ? perspectiveName(p) : msg("Perspective");}
function avatar(id,small=false){const i=Math.max(0,indexOf(id)); return asset(small?'0385b':['4ea9b','5e642','baf01','d51bb','e77a2'][i%5]);}
function closeDialog(id){const dialog=$(id); if(dialog.open)dialog.close(); if(id==='comparison')dialog.hidden=true;}
function openDialog(id){const dialog=$(id); dialog.hidden=false; if(!dialog.open)dialog.showModal();}
function showStep(step){
  if(!state.session)return;
  if(step==='converse'&&!state.room){if(state.session.rooms.length){chooseRoom(state.session.rooms[0].room_id).catch(e=>status(e.message));return;}}
  if(step==='converse'&&!state.room)$('participant-panel').hidden=true;
  if(step==='converse'){$('empty-conversation').hidden=Boolean(state.room);$('chat-workspace').hidden=!state.room;}
  for(const id of ['comparison','source-dialog','perspective-dialog','new-chat-dialog'])closeDialog(id);
  for(const name of ['explore','converse','reflect'])$(name).hidden=name!==step;
  document.body.dataset.step=step;
  rememberConversation();
  document.querySelectorAll('button[data-step]').forEach(b=>{b.classList.toggle('active',b.dataset.step===step); if(b.dataset.step===step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
  if(step==='reflect')refreshReflection().catch(e=>status(e.message));
  if(step==='explore')startComparisons();
  else latestComparison++;
}
async function pollJob(value){
  const end=Date.now()+300000;
  while(Date.now()<end){
    const job=await api('/jobs/'+value.job_id);
    if(job.state==='succeeded')return job;
    if(!['queued','running'].includes(job.state)){
      const error=new Error(errorText(job.error?.code));error.code=job.error?.code;throw error;
    }
    await wait(600);
  }
  throw new Error("This job is still running. Check the conversation for progress.");
}
function setSession(session){
  if (state.session?.session_id !== session.session_id) currentViewEdited = false;
  state.session=session;
  $('initial-edit').value=session.initial_opinion.text;
  renderRooms();
  renderSaved();
}
async function refreshSession(){setSession(await api(base()));}
function renderAnalysis(){
  const a=state.analysis, video=a.video||{}, title=video.title||msg("This discussion"), vid=video.video_id||video.id;
  setText($('video-title'), title); setText($('sidebar-video-title'), title);
  const n=a.analyzed_comments, processedCount = msg(a.count_scope==='registered_sources' ? "{0} registered source comments" : "{0} comments processed", n);
  const other=a.composition?.find(entry=>entry.kind==='other');
  const summary=[msg("{0} perspectives",a.perspectives.length)];
  if(Number.isInteger(n))summary.push(processedCount);
  if(a.status!=='expired' && Number.isInteger(n) && Number.isInteger(other?.count) && other.count<=n){
    summary.push(msg("{0} linked as direct evidence",n-other.count));
  }
  if(a.canonical_population && a.canonical_population!==n)summary.push(msg("{0} comments in the collected set",a.canonical_population));
  setText($('analysis-summary'), joinText(summary));
  setText($('sidebar-video-meta'), Number.isInteger(n)?processedCount:'');
  setText($('analysis-state'), a.quality_gate_passed?'':msg("Development analysis · quality review pending"));
  setText($('video-description'), video.description||msg("Watch the source video, then write what you think."));
  $('sidebar-thumbnail').replaceChildren();
  $('video-frame').replaceChildren(node('p',msg("No source video is linked to this analysis."),'video-placeholder'));
  const videoLinks = ['original-video','before-video-link','sidebar-video'].map($);
  for (const link of videoLinks) { link.removeAttribute('href'); link.hidden = true; }
  if(typeof vid==='string'&&/^[A-Za-z0-9_-]{11}$/.test(vid)){
    const url = 'https://www.youtube.com/watch?v='+vid;
    for (const link of videoLinks) { link.href = url; link.hidden = false; }
    const thumbnails = 'https://i.ytimg.com/vi/'+vid+'/';
    const preview = node('img');
    preview.alt = '';
    preview.onerror = () => preview.remove();
    preview.onload = () => { if (preview.naturalWidth <= 120) preview.remove(); };
    preview.src = thumbnails+'mqdefault.jpg';
    $('sidebar-thumbnail').replaceChildren(preview);
    const play = node('button', undefined, 'video-play');
    play.type = 'button';
    setLabel(play,'aria-label',msg("Play source video: {0}",title));
    const poster = node('img');
    poster.alt = '';
    const fallback = () => {
      poster.onload = () => { if (poster.naturalWidth <= 120) poster.remove(); };
      poster.onerror = () => poster.remove();
      poster.src = thumbnails+'mqdefault.jpg';
    };
    poster.onerror = fallback;
    poster.onload = () => { if (poster.naturalWidth <= 120) fallback(); };
    poster.src = thumbnails+'maxresdefault.jpg';
    const icon = node('span','▶');
    icon.setAttribute('aria-hidden','true');
    play.append(poster, icon);
    play.onclick=()=>{const frame=node('iframe');frame.src='https://www.youtube-nocookie.com/embed/'+vid+'?autoplay=1';setLabel(frame,'title',title);frame.referrerPolicy='strict-origin-when-cross-origin';frame.allow='autoplay; encrypted-media; picture-in-picture';frame.allowFullscreen=true;$('video-frame').replaceChildren(frame);};
    $('video-frame').replaceChildren(play);
  }
  updatePerspectiveLanguageNote();
  renderComposition();
}
let opinionCatalog;
let activeOpinionSample;
let shareRank = 'opinions';
const shareNumber = new Intl.NumberFormat('en-US');
const countIsValid = n => Number.isSafeInteger(n) && n >= 0;

function renderComposition(){
  const analysis = state.analysis, select = $('share-view');
  const sameAnalysis = select.dataset.analysis === analysis.analysis_id;
  const previous = sameAnalysis ? select.value : '';
  if(!sameAnalysis)shareRank = 'opinions';
  select.dataset.analysis = analysis.analysis_id || '';
  const all = node('option',msg("All perspectives"));
  all.value = '';
  select.replaceChildren(all);
  for(const p of analysis.perspectives){
    const option = node('option', perspectiveName(p));
    option.value = p.id;
    select.add(option);
  }
  select.value = previous;
  if(select.selectedIndex < 0)select.selectedIndex = 0;
  select.disabled = !analysis.perspectives.length;
  activeOpinionSample = null;
  renderShares();
  if(analysis.status !== 'expired' && analysis.count_scope === 'processed_comments' && analysis.analysis_id){
    void loadOpinionSample(analysis);
  }
}
async function loadOpinionSample(analysis){
  if(!opinionCatalog){
    opinionCatalog = fetch('/mvp/opinion-samples.json').then(response => {
      if(!response.ok)throw new Error('Sample catalog unavailable');
      return response.json();
    }).catch(() => { opinionCatalog = null; return {}; });
  }
  const catalog = await opinionCatalog;
  if(state.analysis !== analysis)return;
  activeOpinionSample = checkedOpinionSample(analysis, catalog?.[analysis.analysis_id]);
  renderShares();
}
function checkedOpinionSample(analysis, sample){
  if(!sample || sample.population !== analysis.analyzed_comments || !sample.supports ||
      typeof sample.issue !== 'string' || !sample.issue.trim() || !['ai','human'].includes(sample.reviewer))return null;
  const {sample_size:size, positions, no_position:noPosition, unclear, unmatched, multiple} = sample;
  const counts = analysis.perspectives.map(p => sample.supports[p.id]);
  const matched = positions - unmatched;
  const extraLinks = counts.reduce((sum,n) => sum + n, 0) - matched;
  if(![size, positions, noPosition, unclear, unmatched, ...counts].every(countIsValid) ||
      !size || size > sample.population || positions + noPosition + unclear !== size || matched < 0 ||
      Object.keys(sample.supports).length !== counts.length || counts.some(n => n > matched) || extraLinks < 0)return null;
  if(multiple !== undefined && (!countIsValid(multiple) || multiple > matched || multiple > extraLinks ||
      extraLinks > multiple * Math.max(0, counts.length - 1)))return null;
  return sample;
}
function likeDistribution(analysis){
  if(analysis.status === 'expired' || !analysis.engagement?.available)return null;
  const entries = analysis.composition || [];
  const byGroup = new Map(entries.map(e => [e.perspective_id || e.kind, e.likes]));
  const keys = [...analysis.perspectives.map(p => p.id), 'multiple', 'other'];
  if(entries.length !== keys.length || !keys.every(key => countIsValid(byGroup.get(key))))return null;
  const total = entries.reduce((sum, e) => sum + e.likes, 0);
  return total === analysis.engagement.total_likes ? {byGroup, total, linked:total - byGroup.get('other')} : null;
}
function sharePercent(n, total){
  const percent = n * 100 / total;
  if(percent > 0 && percent < 0.1)return '<0.1%';
  if(percent < 100 && percent > 99.9)return '>99.9%';
  return shareNumber.format(Math.round(percent * 10) / 10) + '%';
}
function shareParts(total, outside, multiple, outsideLabel){
  const linked = total - outside;
  const parts = multiple === undefined ? [[msg("Any listed view"), linked, 'listed']] :
    [[msg("One view"), linked - multiple, 'listed'], [msg("Several views"), multiple, 'shared']];
  return [...parts, [outsideLabel, outside, 'other']];
}
function renderShareFigure(id, scope, total, parts, emptyMessage){
  const figure = $(id), plot = figure.querySelector('.share-plot');
  setText(figure.querySelector('.share-scope'), scope);
  plot.replaceChildren();
  if(!total){
    plot.append(node('p', emptyMessage, 'share-empty'));
    return;
  }
  const ns = 'http://www.w3.org/2000/svg', strip = document.createElementNS(ns, 'svg');
  strip.setAttribute('viewBox', '0 0 ' + total + ' 1');
  strip.setAttribute('preserveAspectRatio', 'none');
  strip.setAttribute('aria-hidden', 'true');
  const legend = node('ul', undefined, 'share-legend');
  let start = 0;
  for(const [name, count, key] of parts){
    const item = node('li'), label = node('span', undefined, 'share-key');
    label.append(node('i', undefined, 'share-dot tone-' + key), uiTextNode(name));
    item.append(label, node('span', shareNumber.format(count) + ' · ' + sharePercent(count, total), 'share-value'));
    legend.append(item);
    if(!count)continue;
    const rect = document.createElementNS(ns, 'rect');
    rect.setAttribute('x', String(start));
    rect.setAttribute('width', String(count));
    rect.setAttribute('height', '1');
    rect.setAttribute('class', 'tone-' + key);
    strip.append(rect);
    start += count;
  }
  plot.append(strip, legend);
}
function renderShares(){
  const analysis = state.analysis, sample = activeOpinionSample, likes = likeDistribution(analysis);
  renderShareRanking(analysis, sample, likes);
  renderCoverage(analysis, sample, likes);
}
function renderCoverage(analysis, sample, likes){
  const view = $('share-view').value;
  const issue = $('share-issue');
  issue.hidden = !sample;
  setText(issue, sample ? presentationText('issue', sample.issue) : '');
  setText($('share-method'), sample
    ? msg(sample.reviewer === 'ai'
      ? "AI review of {0} of the {1} processed comments. {2} stated no position on this issue and {3} were unclear."
      : "Human review of {0} of the {1} processed comments. {2} stated no position on this issue and {3} were unclear.",
      sample.sample_size, shareNumber.format(sample.population), sample.no_position, sample.unclear)
    : msg("No reviewed opinion sample is available for this analysis."));
  const opinions = sample?.positions, support = sample?.supports[view];
  const opinionScope = !sample ? '' : view && opinions
    ? msg("{0} / {1} comments support this view", support, opinions)
    : msg("{0} of {1} sampled comments stated a position", opinions, sample.sample_size);
  const opinionParts = !sample ? [] : view ?
    [[msg("Supports this view"), support, 'listed'], [msg("Other positions"), opinions - support, 'other']] :
    shareParts(opinions, sample.unmatched, sample.multiple, msg("Outside these views"));
  renderShareFigure('opinion-share', opinionScope, opinions, opinionParts, sample ?
    msg("No sampled comment stated a position on this issue.") : msg("No reviewed opinion sample is available for this analysis."));

  const total = likes?.total, likeCount = likes?.byGroup.get(view);
  const likeScope = !likes ? '' : view && total
    ? msg("{0} / {1} likes linked only to this view",shareNumber.format(likeCount),shareNumber.format(total))
    : msg(total === 1 ? "{0} like on {1} processed comments" : "{0} likes on {1} processed comments",
      shareNumber.format(total),shareNumber.format(analysis.analyzed_comments));
  const likeParts = !likes ? [] : view ?
    [[msg("Only this view"), likeCount, 'listed'], [msg("All other likes"), total - likeCount, 'other']] :
    shareParts(total, likes.byGroup.get('other'), likes.byGroup.get('multiple'), msg("Unlinked comments"));
  renderShareFigure('like-share', likeScope, total, likeParts, likes ?
    msg("No likes were recorded on the processed comments.") : msg("Like counts are unavailable for the full set of processed comments."));

  const coverage = [];
  if(opinions)coverage.push(msg("{0} of {1} sampled positions support none of these perspectives.",shareNumber.format(sample.unmatched),shareNumber.format(opinions)));
  if(total)coverage.push(msg("{0} of {1} recorded likes ({2}) are linked to perspectives. {3} are on unlinked comments.",
    shareNumber.format(likes.linked), shareNumber.format(total), sharePercent(likes.linked,total), shareNumber.format(likes.byGroup.get('other'))));
  setText($('share-coverage'), joinText(coverage,' '));
  $('share-coverage').hidden = !coverage.length;
}
function renderShareRanking(analysis, sample, likes){
  const table = $('share-table'), body = table.tBodies[0];
  body.replaceChildren();
  table.hidden = !analysis.perspectives.length;
  $('share-ranking').hidden = analysis.perspectives.length < 2;
  const opinions = sample?.positions, totalLikes = likes?.linked, sharedLikes = likes?.byGroup.get('multiple');
  const sortBy = totalLikes && (shareRank === 'likes' || !opinions) ? 'likes' : 'opinions';
  for(const [metric, column, total] of [['opinions','opinion-column',opinions],['likes','like-column',totalLikes]]){
    const active = Boolean(total && metric === sortBy);
    const button = $('rank-' + metric);
    button.disabled = !total;
    button.setAttribute('aria-pressed', String(active));
    $(column).setAttribute('aria-sort', active ? 'descending' : 'none');
  }
  setText($('opinion-base'), sample ? msg("of {0} sampled positions",shareNumber.format(opinions)) : msg("No reviewed sample"));
  setText($('like-base'), !likes ? msg("Counts unavailable") : !likes.total ? msg("No recorded likes") :
    !totalLikes ? msg("No linked likes") : msg("of {0} linked likes",shareNumber.format(totalLikes)));
  const ranked = analysis.perspectives.map(p => ({name:perspectiveName(p), opinions:sample?.supports[p.id], likes:likes?.byGroup.get(p.id)}));
  const secondary = sortBy === 'likes' ? 'opinions' : 'likes';
  ranked.sort((a,b) => (b[sortBy] ?? 0) - (a[sortBy] ?? 0) || (b[secondary] ?? 0) - (a[secondary] ?? 0));
  let peak = totalLikes ? 100 * sharedLikes / totalLikes : 0;
  for(const row of ranked){
    peak = Math.max(peak, opinions ? 100 * row.opinions / opinions : 0, totalLikes ? 100 * row.likes / totalLikes : 0);
  }
  const scale = peak ? [1, 2, 5, 10, 20, 25, 50, 75, 100].find(limit => limit >= peak) : 100;
  const scaleLabel = $('share-scale');
  scaleLabel.replaceChildren();
  if(opinions || totalLikes)scaleLabel.append(uiTextNode(msg("Bar scale")), ' ', node('span', '0–' + scale + '%'));
  for(const entry of ranked){
    const row = body.insertRow(), name = node('th', entry.name);
    name.scope = 'row';
    name.dir = 'auto';
    row.append(name);
    renderShareCell(row.insertCell(), entry.opinions, opinions, scale, 'comment');
    renderShareCell(row.insertCell(), entry.likes, totalLikes, scale, 'like');
  }
  const sharedCell = table.tFoot.rows[0].cells[2];
  sharedCell.replaceChildren();
  table.tFoot.hidden = !sharedLikes;
  if(sharedLikes)renderShareCell(sharedCell, sharedLikes, totalLikes, scale, 'like');
}
function renderShareCell(cell, count, denominator, scale, unit){
  const measure = node('div', undefined, 'share-measure');
  if(denominator){
    const bar = node('progress', undefined, 'share-bar');
    bar.max = scale;
    bar.value = 100 * count / denominator;
    bar.setAttribute('aria-hidden', 'true');
    measure.append(bar);
  }
  const value = node('span', undefined, 'share-amount');
  value.append(node('strong', denominator ? sharePercent(count, denominator) : '—'));
  if(count !== undefined){
    const phrase = unit === 'like'
      ? (count === 1 ? "{0} like" : "{0} likes")
      : (count === 1 ? "{0} comment" : "{0} comments");
    value.append(node('small',msg(phrase,shareNumber.format(count))));
  }
  measure.append(value);
  cell.append(measure);
}
for(const metric of ['opinions', 'likes']){
  $('rank-' + metric).addEventListener('click', () => {
    shareRank = metric;
    renderShareRanking(state.analysis, activeOpinionSample, likeDistribution(state.analysis));
  });
}
$('share-view').addEventListener('change', () => renderCoverage(state.analysis, activeOpinionSample, likeDistribution(state.analysis)));
function supportsDebate(count){return count>=2&&state.session.capabilities?.structured_debate;}
function updateSelection(){
  const count=state.selected.size;
  const mode=count===1?msg("Start a 1:1 conversation."):supportsDebate(count)?msg("Start an automatic debate."):msg("Start a group conversation.");
  setText($('selection-hint'), count?msg("{0} selected · {1}",count,mode):msg("Choose one perspective for a 1:1 conversation, or up to three for a group."));
  $('open-room').disabled=!count;
  for (const topic of $('perspectives').querySelectorAll('.perspective-topic')) {
    const selected = topic.querySelectorAll('.card-select input:checked').length;
    const note = topic.querySelector('.topic-selected');
    note.hidden = !selected;
    if (selected) setText(note, msg("{0} selected", selected));
  }
}

async function showPerspectiveTopics(analysis, cards, expanded) {
  if (!analysis.analysis_id || cards.size < 2) return;
  let catalog;
  try { catalog = await presentationCatalog(); } catch { return; }
  const container = $('perspectives');
  if (state.analysis !== analysis || cards.values().next().value.parentElement !== container) return;
  const topics = catalog?.[analysis.analysis_id]?.topics;
  if (!Array.isArray(topics) || !topics.every(t => t && typeof t.en === 'string'
      && typeof t.ko === 'string' && Array.isArray(t.members))) return;
  if (!topics.some(t => t.members.filter(id => cards.has(id)).length > 1)) return;

  const focused = container.contains(document.activeElement) ? document.activeElement : null;
  const remaining = new Map(cards);
  const list = document.createDocumentFragment();
  for (const topic of topics) {
    const members = topic.members.filter(id => remaining.has(id));
    if (!members.length) continue;
    const detail = node('details', undefined, 'perspective-topic');
    detail.dataset.topic = members[0];
    const summary = node('summary');
    const title = node('strong', {original:topic.en, translation:{ko:topic.ko}});
    const count = node('span', msg(members.length === 1 ? "{0} perspective" : "{0} perspectives", members.length));
    const selected = node('span', undefined, 'topic-selected');
    selected.hidden = true;
    summary.append(title, count, selected);
    const grid = node('div', undefined, 'cards');
    detail.open = expanded.has(members[0]) || members.some(id =>
      cards.get(id).contains(focused) || cards.get(id).querySelector('details[open]'));
    for (const id of members) {
      grid.append(cards.get(id));
      remaining.delete(id);
    }
    detail.append(summary, grid);
    list.append(detail);
  }
  if (remaining.size) {
    const grid = node('div', undefined, 'cards');
    grid.append(...remaining.values());
    list.append(grid);
  }
  container.replaceChildren(list);
  container.classList.add('topic-list');
  $('topic-intro').hidden = false;
  $('perspective-picker').after($('breakdown-title').closest('.breakdown'));
  updateSelection();
  if (focused) focused.focus({preventScroll:true});
}

function renderPerspectives(){
  const container = $('perspectives'), analysis = state.analysis;
  const expanded = new Set(container.dataset.analysis === analysis.analysis_id
    ? [...container.querySelectorAll('.perspective-topic[open]')].map(topic => topic.dataset.topic) : []);
  container.dataset.analysis = analysis.analysis_id || '';
  container.classList.remove('topic-list');
  $('topic-intro').hidden = true;
  $('perspective-language-note').after($('breakdown-title').closest('.breakdown'));
  container.replaceChildren();
  const cards = new Map();
  if(!state.analysis.perspectives.length){
    $('perspectives').append(node('p',msg("No perspective has verified sources yet. You can write your own view in Reflect."),'muted'));
  }
  for(const p of state.analysis.perspectives){
    const card=node('article',undefined,'card accent-'+indexOf(p.id)%5);card.classList.toggle('selected',state.selected.has(p.id));
    const top=node('header'),choice=node('label',undefined,'card-select'),check=node('input');check.type='checkbox';check.checked=state.selected.has(p.id);setLabel(check,'aria-label',msg("Select {0}",label(p.id)));
    check.onchange=()=>{if(check.checked){if(state.selected.size>=3){check.checked=false;status(msg("Choose up to three perspectives per conversation."));return;}state.selected.add(p.id);}else state.selected.delete(p.id);card.classList.toggle('selected',check.checked);updateSelection();};
    choice.append(check,node('span','✓'));top.append(avatar(p.id),choice);
    const title=node('div',undefined,'card-title'),count=node('span',msg(p.source_count===1?"{0} direct source comment":"{0} direct source comments",p.source_count),'source-badge');title.append(node('strong',label(p.id)),node('small',msg("A viewpoint from the comments")));top.append(title);
    if(p.admission_policy)card.append(node('small',msg("This stance appears in the comments. Its source count describes the evidence for this card.")));
    card.append(top,count,node('p',msg("STANCE"),'card-section-label'),node('p',claimText(p.core_claim_id, p.text),'card-stance'));
    const grounds=p.grounds||[];
    if(grounds.length){
      card.append(node('p',msg("REASONS & CONDITIONS IN THE SOURCES"),'card-section-label'));
      for(const g of grounds){
        const row=node('p',undefined,'card-ground');
        row.append(node('span',g.role==='essential_condition'?joinText([msg("Condition:"),' '],''):g.role==='concession'?joinText([msg("Qualification:"),' '],''):''),
          node('span',claimText(g.claim_id, g.text)),node('small',joinText([' · ',msg(g.source_count===1?"{0} source":"{0} sources",g.source_count)],''),'ground-count'));
        card.append(row);
      }
    }
    const compare=node('button',msg("Compare with my view"),'secondary compare-button');compare.type='button';compare.onclick=async()=>{compare.disabled=true;try{await compareWith(p.id);}catch(e){status(e.message);}finally{compare.disabled=false;}};
    card.addEventListener('click',event=>{
      if(!card.contains(event.target.closest('button,a,input,label,details')) && !window.getSelection()?.toString())compare.click();
    });
    card.dataset.perspective=p.id;
    card.id='perspective-card-'+p.id;
    const relations=node('div',undefined,'card-relations');relations.setAttribute('aria-live','polite');renderRelations(relations,p.id);
    card.append(relations,compare,sourceDisclosure(p));container.append(card);
    cards.set(p.id,card);
  }
  updateSelection();
  updateComparisonProgress();
  void showPerspectiveTopics(analysis, cards, expanded);
}
const relationNames={agreement:msg("Agreement"),difference:msg("Difference"),additional_condition:msg("Additional condition"),unclear:msg("Unclear")};
let comparisonRun, activeComparisons=0, latestComparison=0;
const comparisonLimit=3;
function isCurrentComparison(run){
  return !!run && run.sessionId===state.session?.session_id && run.revision===state.session?.initial_opinion.revision;
}
function currentComparisons(){
  if(!isCurrentComparison(comparisonRun)){
    for(const entry of comparisonRun?.queue||[])entry.resolve(null);
    comparisonRun={sessionId:state.session.session_id,revision:state.session.initial_opinion.revision,queue:[],entries:new Map()};
  }
  return comparisonRun;
}
function updateComparisonProgress(){
  const ids=state.analysis.perspectives.map(p=>p.id);
  const run=isCurrentComparison(comparisonRun)?comparisonRun:null;
  const done=ids.filter(id=>state.session.comparisons?.[id] || run?.entries.get(id)?.phase==='done').length;
  const failed=ids.filter(id=>run?.entries.get(id)?.phase==='failed').length;
  const message=ids.length && state.session.initial_opinion.text.trim()
    ? joinText([msg("{0} / {1} perspectives compared",done,ids.length), ...(failed ? [msg("{0} unavailable",failed)] : [])]) : '';
  if($('compare-progress').textContent!==formatText(message))setText($('compare-progress'), message);
  $('compare-all').hidden=!failed;
}
function refreshComparisonCard(id){
  const card=$('perspective-card-'+id);
  if(card)renderRelations(card.querySelector('.card-relations'),id);
}
function enqueueComparison(run,id,priority=false){
  let entry=run.entries.get(id);
  if(!entry || entry.phase==='failed'){
    entry={id,phase:'queued'};
    entry.promise=new Promise(resolve=>{entry.resolve=resolve;});
    run.entries.set(id,entry);
    run.queue.push(entry);
    refreshComparisonCard(id);
  }
  if(priority && entry.phase==='queued'){
    run.queue.splice(run.queue.indexOf(entry),1);run.queue.unshift(entry);
  }
  return entry;
}
function startComparisons(retry=false){
  if(document.body.dataset.step!=='explore')return;
  const run=currentComparisons();
  if(!state.session.initial_opinion.text.trim()){updateComparisonProgress();return;}
  for(const p of state.analysis.perspectives){
    const entry=run.entries.get(p.id);
    if(!state.session.comparisons?.[p.id] && (!entry || (retry && entry.phase==='failed')))enqueueComparison(run,p.id);
  }
  pumpComparisons();
  updateComparisonProgress();
}
function pumpComparisons(){
  const run=comparisonRun;
  if(!isCurrentComparison(run) || document.body.dataset.step!=='explore')return;
  while(activeComparisons<comparisonLimit && run.queue.length){
    const entry=run.queue.shift();
    entry.phase='running';activeComparisons++;
    refreshComparisonCard(entry.id);
    void processComparison(run,entry);
  }
}
async function processComparison(run,entry){
  let job;
  try{
    const saved=state.session.comparisons?.[entry.id];
    const accepted=saved || await api('/sessions/'+run.sessionId+'/comparisons','POST',{
      perspective_id:entry.id,initial_revision:run.revision,request_id:requestId()});
    job=await pollJob(accepted);
    if(job.stale){
      const error=new Error(errorText('opinion_revision_conflict'));error.code='opinion_revision_conflict';throw error;
    }
    if(isCurrentComparison(run)){
      state.session.comparisons??={};
      entry.summary={job_id:job.job_id,available:job.result.available,
        relations:[...new Set((job.result.items||[]).map(i=>i.relation))]};
      state.session.comparisons[entry.id]=entry.summary;
      entry.phase='done';
    }
  }catch(error){
    entry.phase='failed';entry.error=error;
    if(['budget_exhausted','cycle_deadline','reconcile_required','unconfirmed_provider_call','opinion_revision_conflict'].includes(error.code)){
      for(const waiting of run.queue.splice(0)){
        waiting.phase='failed';waiting.error=error;waiting.resolve(null);
        if(isCurrentComparison(run))refreshComparisonCard(waiting.id);
      }
    }
  }finally{
    activeComparisons--;
    entry.resolve(entry.phase==='done'?job:null);
    if(isCurrentComparison(run)){
      refreshComparisonCard(entry.id);
      updateComparisonProgress();
    }
    pumpComparisons();
  }
}
function renderRelations(container,id){
  container.replaceChildren();
  const entry=isCurrentComparison(comparisonRun)?comparisonRun.entries.get(id):null;
  const result=state.session.comparisons?.[id] || entry?.summary;
  container.dataset.state=result?'done':entry?.phase||'idle';
  if(!result?.relations.length){
    const labels={queued:msg("Waiting to compare"),running:msg("Comparing with your view…"),failed:msg("Comparison unavailable · retry this card")};
    const message=result?msg("No clear relationship found"):labels[entry?.phase]||(state.session.initial_opinion.text.trim()?msg("Not compared yet"):msg("Add your view to compare"));
    container.append(node('small',message,'muted'));return;
  }
  for(const relation of result.relations)container.append(node('span',relationNames[relation],'relation-chip mark-'+relation));
}
function sourceDisclosure(p){
  const details=node('details',undefined,'source-disclosure');
  details.append(node('summary',msg("Source comments")));
  const stance=node('div',undefined,'card-sources');stance.append(node('p',claimText(p.core_claim_id, p.text)));
  commentSourceButtons(stance,p.source_ids||[],msg("Stance source"));details.append(stance);
  for(const ground of p.grounds||[]){
    const row=node('div',undefined,'card-ground-sources');row.append(node('p',claimText(ground.claim_id, ground.text)));
    commentSourceButtons(row,ground.source_ids||[],msg("Reason source"));details.append(row);
  }
  return details;
}
async function source(id, resource=base()){try{const value=await api(resource+'/sources/'+encodeURIComponent(id));setText($('source'), value.PARENT_CONTEXT_ONLY ? joinText([value.text,'\n\n',msg("Parent comment for context"),'\n',value.PARENT_CONTEXT_ONLY.text],'') : value.text);openDialog('source-dialog');}catch(e){status(e.message);}}
function sourceButtons(container,point,seen=new Set()){
  commentSourceButtons(container,[...new Set((point.citations?.comment_evidence||[]).map(e=>e.source_id))]);
  for(const evidence of point.citations?.external_evidence||[]){
    let url;
    try{url=new URL(evidence.url);}catch{continue;}
    if(url.protocol!=='https:'||url.username||url.password||seen.has(url.href))continue;
    seen.add(url.href);
    const link=node('a',evidence.title||msg("External source"),'source-button');
    link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.title=evidence.text;
    container.append(link);
  }
}
function commentSourceButtons(container,sourceIds,caption=msg("Source")){
  for(const [index,sourceId] of sourceIds.entries()){
    const button=node('button',joinText([caption,index+1],' '),'source-button');
    button.type='button';
    button.onclick=()=>source(sourceId);
    container.append(button);
  }
}
// API span offsets are Unicode code points. Build text nodes, including for untrusted markup.
function highlighted(container,text,spans){
  const chars=[...text],bounds=new Set([0,chars.length]);
  const valid=spans.filter(s=>Number.isInteger(s.start)&&Number.isInteger(s.end)&&s.start>=0&&s.end<=chars.length&&s.end>s.start);
  valid.forEach(s=>{bounds.add(s.start);bounds.add(s.end);});const cuts=[...bounds].sort((a,b)=>a-b);container.replaceChildren();
  for(let i=1;i<cuts.length;i++){const start=cuts[i-1],end=cuts[i],keys=[...new Set(valid.filter(s=>s.start<=start&&s.end>=end).map(s=>s.category))],part=chars.slice(start,end).join('');container.append(keys.length?node('mark',part,'mark-'+(keys.length===1?keys[0]:'mixed')):document.createTextNode(part));}
}
async function compareWith(pid){
  const view=++latestComparison,session=state.session,run=currentComparisons();
  let job={result:{available:false,items:[]}};
  if(session.initial_opinion.text.trim()){
    status(msg("Comparing your view with this perspective."));
    const entry=enqueueComparison(run,pid,true);
    pumpComparisons();
    job=await entry.promise;
    if(!isCurrentComparison(run)||view!==latestComparison||document.body.dataset.step!=='explore')return;
    if(!job){status(entry.error?.message||msg("Open the comparison again with your current view."));return;}
  }
  const items=job.result.items||[];
  const p=perspective(pid);
  $('comparison').className='comparison-modal accent-'+indexOf(pid)%5;$('comparison-avatar').replaceChildren(avatar(pid));setText($('comparison-title'), label(pid));
  const coreRelations = [...new Set(items.filter(item=>item.perspective_claims.some(c=>c.claim_id===p.core_claim_id)).map(item=>item.relation))];
  const stance = claimText(p.core_claim_id, p.text);
  if(coreRelations.length) $('comparison-stance').replaceChildren(node('mark', stance, 'mark-' + (coreRelations.length === 1 ? coreRelations[0] : 'mixed')));
  else setText($('comparison-stance'), stance);
  $('comparison-items').replaceChildren();$('comparison-sources').replaceChildren(sourceDisclosure(p));
  highlighted($('comparison-initial'),session.initial_opinion.text,items.flatMap(i=>i.user_spans.map(s=>({...s,category:i.relation}))));
  if(!job.result.available)$('comparison-items').append(node('p',msg("Add your initial view to compare it with this perspective.")));
  else{
    for(const item of items){
      const row=node('article',undefined,'comparison-item '+item.relation);
      row.append(node('h3',relationNames[item.relation]),node('p',item.explanation),node('blockquote',msg("Your view · {0}",item.user_spans.map(s=>s.text).join(' '))));
      for(const claim of item.perspective_claims){
        const quote=node('blockquote');quote.append(node('mark',referencedClaim(p,claim),'mark-'+item.relation));row.append(quote);sourceButtons(row,claim);
      }
      for(const premise of item.required_premises){row.append(node('p',referencedClaim(p,premise),'required-premise'));sourceButtons(row,premise);}
      if(item.consideration_question)row.append(node('p',item.consideration_question,'comparison-question'));
      $('comparison-items').append(row);
    }
    if(!items.length)$('comparison-items').append(node('p',msg("No clear similarity or difference could be established from the two views.")));
  }
  openDialog('comparison');status('');
}
$('compare-all').onclick=()=>startComparisons(true);
const roomStates={
  idle:msg("Ready to start"),running:msg("Running"),pausing:msg("Pausing"),paused:msg("Paused"),awaiting_user:msg("Waiting for a question"),
  opening:msg("Opening statement"),replying:msg("Responding to other perspectives"),synthesizing:msg("Reviewing consensus"),compiling:msg("Preparing the conclusion"),
  completed:msg("Completed"),completed_no_consensus:msg("No consensus"),completed_no_proposal:msg("No shared proposal"),
  verification_hold:msg("Verification on hold"),incomplete:msg("Incomplete response"),failed:msg("Run failed"),cancelled:msg("Cancelled"),
  closed:msg("Closed"),closing:msg("Closing"),error:msg("Some responses failed"),exhausted:msg("Limit reached"),needs_reconciliation:msg("Needs review")
};
const activeRoomStates=new Set(['running','opening','replying','synthesizing','compiling','pausing','closing']);
const lastRoomKey='commentscope-mvp-last-conversation';
const defaultOpeningQuestion=$('opening-question').defaultValue;

function roomName(room,index){
  if(room.kind==='synthesis_chat')return msg("Consensus agent chat {0}",index+1);
  if(room.kind==='structured_debate')return msg("Automatic debate {0}",index+1);
  return msg(room.mode==='group'?"Group conversation {0}":"1:1 conversation {0}",index+1);
}
function roomPath(room){
  return room.debate_id?'/debates/'+encodeURIComponent(room.debate_id):'/rooms/'+encodeURIComponent(room.room_id);
}
function setRoom(room){
  if(room?.room_id!==state.room?.room_id||room?.kind==='debate_draft'){
    $('question').value='';$('question-target').replaceChildren();
  }
  clearTimeout(state.roomTimer);
  state.room=room;
}
function rememberConversation(){
  const room=state.room;
  if(document.body.dataset.step==='converse'&&room?.room_id){
    sessionStorage.setItem(lastRoomKey,JSON.stringify({session_id:state.session.session_id,room_id:room.room_id}));
  }else sessionStorage.removeItem(lastRoomKey);
}
async function chooseRoom(id){
  const room=state.session.rooms.find(item=>item.room_id===id);
  if(!room)return;
  const stepBeforeLoad=document.body.dataset.step;
  setRoom(room);
  await refreshRoom();
  if(state.room?.room_id===id&&document.body.dataset.step===stepBeforeLoad)showStep('converse');
}
function renderRooms(){
  const select=$('rooms'),list=$('room-list');select.replaceChildren(node('option',msg("Choose a conversation")));select.firstChild.value='';list.replaceChildren();
  if(!state.session)return;
  const query=$('room-search').value.toLowerCase();
  state.session.rooms.forEach((room,i)=>{if(room.room_id===state.room?.room_id)room=state.room;const title=roomName(room,i),option=node('option',joinText([title,roomStates[room.state]||room.state]));option.value=room.room_id;select.append(option);
    if(state.roomFilter!=='all'&&room.mode!==state.roomFilter||!formatText(title).toLowerCase().includes(query))return;
    const button=node('button',undefined,'room-entry');button.type='button';button.classList.toggle('active',state.room?.room_id===room.room_id);button.append(node('strong',title),node('small',roomStates[room.state]||room.state));button.onclick=()=>chooseRoom(room.room_id).catch(e=>status(e.message));list.append(button);
  });
  if(!list.childNodes.length)list.append(node('p',msg("No conversations here yet."),'muted'));if(state.room?.room_id)select.value=state.room.room_id;
}
function renderMessages(start=0){
  if(!start)$('messages').replaceChildren();
  for(const m of state.room.messages.slice(start)){const box=node('article',undefined,'message '+m.author_kind);box.id='message-'+m.message_id;
    if(m.author_kind==='agent'){const icon=node('div',undefined,'message-avatar');icon.append(avatar(m.agent_id,true));box.append(icon);}
    const bubble=node('div',undefined,'bubble');
    const phase=({opening:msg("Opening statement"),reply:msg("Reply to another perspective")})[m.phase];
    const speaker=m.author_kind==='user'?msg("You"):label(m.agent_id);
    bubble.append(node('small',phase?joinText([speaker,phase]):speaker));
    if(m.reply_to_message_id){const reply=state.room.messages.find(x=>x.message_id===m.reply_to_message_id);if(reply?.author_kind==='agent')bubble.append(node('small',msg("Reply to an earlier turn by {0}",label(reply.agent_id))));}
    if(m.body)bubble.append(node('p',m.body));
    if(m.author_kind==='agent'&&!m.points?.length){
      const expired=m.evidence_scope==='expired';
      bubble.append(node('p',expired?msg("The evidence has expired."):m.limitation==='verification_hold'?msg("The answer to this question could not be verified."):msg("The sources do not provide enough evidence to answer this question.")));
      if(!expired&&m.evidence_scope==='seeded_provenance'){
        const original=perspective(m.agent_id);
        if(original?.source_ids?.length){
          const details=node('details',undefined,'source-disclosure');
          details.append(node('summary',msg("View this perspective’s original stance and sources")),node('p',claimText(original.core_claim_id,original.text)));
          commentSourceButtons(details,original.source_ids,msg("Stance source"));bubble.append(details);
        }
      }
    }
    const points=m.points||[];
    if(points.length){
      const evidence=node('details',undefined,'turn-evidence');
      evidence.append(node('summary',msg("Evidence and conditions")));
      const developed=points.filter(p=>p.origin==='ai_reasoning'||p.origin==='external_evidence');
      const stance=points.find(p=>p.declared_role==='core')||points[0];
      const support=points.find(p=>p!==stance&&['reason','essential_condition'].includes(p.declared_role));
      const primary=developed.length ? developed : [stance,...(support?[support]:[])];
      const seen=new Set();
      let previousOrigin;
      for(const point of primary){
        if(point.origin&&(previousOrigin!==point.origin||point===support)){
          const supportLabel=point.declared_role==='essential_condition'?msg("Condition in the source"):
            point.kind==='prediction'?msg("Expected effect in the source"):msg("Reason given in the source");
          const originLabel=point===support?supportLabel:point.origin==='ai_reasoning'?msg("Agent reasoning"):
            point.origin==='original_comment'?msg("Source position"):pointOrigin(point.origin);
          if(originLabel)bubble.append(node('small',originLabel,'answer-origin'));
        }
        previousOrigin=point.origin;
        const text=node('p',point.text,'answer-text');
        if(point.point_id)text.id='point-'+point.point_id;
        bubble.append(text);
      }
      if(!developed.length&&m.evidence_scope==='seeded_provenance'){
        bubble.append(node('small',msg("Only the source position is available for this question.")));
      }
      for(const point of points){
        const origin=pointOrigin(point.origin);
        if(origin)evidence.append(node('small',origin));
        if(!developed.includes(point)){
          const text=node('p',point.text);
          if(!primary.includes(point)&&point.point_id)text.id='point-'+point.point_id;
          evidence.append(text);
        }else if(developed.length>1){
          evidence.append(node('p',point.text));
        }
        if (m.evidence_scope === 'seeded_provenance' && point.origin === 'ai_reasoning' &&
            point.citations?.anchor_claim_ids?.length) {
          const aliases = [...new Set(point.text.match(/\bE[1-9]\d*\b/g) || [])];
          if (aliases.length) {
            const view = perspective(m.agent_id);
            const claims = new Map((view?.grounds || []).map(ground => [ground.claim_id, claimText(ground.claim_id, ground.text)]));
            if (view) claims.set(view.core_claim_id, claimText(view.core_claim_id, view.text));
            const details = node('details', undefined, 'source-disclosure');
            details.append(node('summary', msg("{0} · Referenced claims",aliases.join(', '))),
              node('p', msg("An E-number identifies a claim the agent referred to when writing its explanation.")));
            for (const id of new Set(point.citations.anchor_claim_ids)) {
              if (claims.has(id)) details.append(node('blockquote', claims.get(id)));
            }
            evidence.append(details);
          }
        }
        sourceButtons(evidence,point,seen);
        for(const target of point.target_edges||[]){
          appendPointLinks(evidence,[target.point_id],state.room,msg("Reply target · {0}",label(target.agent_id)));
        }
      }
      if(m.status==='abstain')bubble.append(node('small',msg("The sources support only a limited answer to this question.")));
      if(m.limitation==='verification_hold')evidence.append(node('small',msg("Only the verified parts of the explanation are shown.")));
      if(m.required_premises?.length){
        evidence.append(node('small',msg("Premises and conditions to consider")));
        for(const point of m.required_premises){evidence.append(node('p',point.text));sourceButtons(evidence,point,seen);}
      }
      bubble.append(evidence);
    }
    box.append(bubble);$('messages').append(box);
  }
}
function pointOrigin(origin){
  return ({original_comment:msg("Comment evidence"),ai_reasoning:msg("AI reasoning · generated by the agent"),
    external_evidence:msg("Claim based on an external source")})[origin];
}
function appendPointLinks(parent,pointIds,room,title){
  for(const pointId of new Set(pointIds)){
    const message=room.messages.find(m=>m.points?.some(point=>point.point_id===pointId));
    if(!message)continue;
    const link=node('button',title||msg("Supporting turn from {0}",label(message.agent_id)),'source-button');
    link.type='button';
    link.onclick=()=>{
      const point=$('point-'+pointId);
      if(!point)return;
      for(let parent=point.parentElement;parent;parent=parent.parentElement){
        if(parent.tagName==='DETAILS')parent.open=true;
      }
      point.scrollIntoView({block:'center'});
      point.setAttribute('tabindex','-1');point.focus({preventScroll:true});
    };
    parent.append(link);
  }
}
function renderConclusion(room){
  const panel=$('debate-conclusion');
  panel.replaceChildren();
  const result=room.conclusion;
  panel.hidden=!result;
  if(!result)return;
  const summaries={
    completed:msg("All participating perspectives accepted the shared claims below."),
    completed_no_consensus:msg("No claim was accepted by every perspective. The disagreements and replies are below."),
    completed_no_proposal:msg("The debate produced no shared proposal. Compare the perspectives in the transcript."),
    verification_hold:msg("The evidence or acceptance for a shared claim could not be verified. Verified turns are shown above."),
    incomplete:msg("Some responses did not fully address the question or a previous turn."),
    failed:msg("The debate did not finish. Published turns are saved."),
    exhausted:msg("The AI limit was reached. Published turns are saved."),
    needs_reconciliation:msg("The run needs review. Published turns are saved.")
  };
  panel.append(node('h2',msg("Debate conclusion · {0}",roomStates[result.status]||msg("Closed"))));
  panel.append(node('p',result.evidence_scope==='expired'?msg("The source evidence has expired."):
    summaries[result.status]||msg("Read the published turns from this debate.")));
  for(const claim of result.shared_claims||[]){
    const card=node('article',undefined,'debate-claim');
    card.append(node('h3',claim.text));
    const origin=pointOrigin(claim.origin);
    if(origin)card.append(node('p',origin,'muted'));
    const names=(claim.accepting_agent_ids||[]).map(label);
    if(names.length)card.append(node('p',msg("Accepted by · {0}",joinText(names,', ')),'muted'));
    const conditions=new Set((claim.condition_ids||[]).map(id=>result.conditions?.[id])
      .filter(Boolean).map(condition=>condition.scope?.conditions||condition.text));
    for(const condition of conditions)card.append(node('p',msg("Condition · {0}",condition)));
    const references=node('div',undefined,'debate-references');
    appendPointLinks(references,claim.premise_point_ids||[],room);
    sourceButtons(references,claim);
    const details=node('details',undefined,'turn-evidence');
    details.append(node('summary',msg("Evidence from these turns")),references);card.append(details);
    panel.append(card);
  }
  if(result.disagreements?.length){
    panel.append(node('h3',msg("Disagreements and conditional responses")));
    const list=node('ul');
    const relations={reject:msg("Rejected"),needs_condition:msg("Additional condition requested"),disagree:msg("Disagrees"),conditional:msg("Conditional response")};
    for(const item of result.disagreements){
      const row=node('li',joinText([label(item.agent_id),relations[item.relation]||msg("Disagreement")]));
      const references=node('div',undefined,'debate-references');
      appendPointLinks(references,item.point_ids||[],room);
      row.append(references);
      list.append(row);
    }
    panel.append(list);
  }
  if(result.unanswered?.length&&result.evidence_scope!=='expired'){
    panel.append(node('h3',msg("Still unanswered")));
    const list=node('ul');
    for(const row of result.unanswered){
      list.append(node('li',joinText([label(row.agent_id),row.targets.length?
        row.targets.map(target=>target.text).join(' / '):msg("Question not fully addressed")])));
    }
    panel.append(list);
  }
  if(room.synthesis_agent){
    const card=node('section',undefined,'synthesis-card');
    card.append(node('h3',msg("Consensus agent")),node('p',msg("Answers questions using the claims and conditions accepted by the participants.")));
    const references=node('div',undefined,'debate-references');
    const resource='/synthesis-agents/'+encodeURIComponent(room.synthesis_agent.agent_id);
    for(const [i,id] of (result.root_source_ids||[]).entries()){
      const read=node('button',msg("Original source {0}",i+1),'source-button');
      read.type='button';
      read.onclick=()=>source(id,resource);
      references.append(read);
    }
    if(references.childElementCount){
      const details=node('details',undefined,'turn-evidence');
      details.append(node('summary',msg("Original comments for the consensus agent")),references);card.append(details);
    }
    const ask=node('button',msg("Ask the consensus agent"),'primary');
    ask.type='button';
    ask.id='ask-synthesis-agent';
    ask.onclick=()=>openSynthesisChat(room,ask);
    card.append(ask);
    panel.append(card);
  } else if (result.evidence_scope !== 'expired' && ['incomplete','verification_hold','completed_no_consensus','completed_no_proposal'].includes(result.status)) {
    const followup = node('button', msg("Ask these perspectives in a new chat"), 'secondary');
    followup.type = 'button';
    followup.id = 'discuss-with-participants';
    followup.onclick = () => showChatPicker(room.participant_ids);
    panel.append(followup);
  }
}
let renderedTranscript;
let renderedParticipants;
let pendingQuestionRoom=null;
let consensusProfile=null;

function loadConsensusProfile(room){
  const id=room.participant_ids[0], key=state.session.session_id+'/'+id;
  if(consensusProfile?.key===key)return consensusProfile.data;
  const record={key,data:null};consensusProfile=record;
  api('/synthesis-agents/'+encodeURIComponent(id)).then(agent=>{
    if(consensusProfile!==record)return;
    record.data=agent;
    if(state.room?.room_id===room.room_id){renderedParticipants=null;renderParticipants(state.room);}
  }).catch(()=>{});
  return null;
}

function roundProgress(room){
  const ids=room.participant_ids||[];
  if(room.kind==='structured_debate'){
    const completed=room.turn_count;
    return {completed,total:room.turn_limit,active_agent_id:['opening','replying'].includes(room.state)?ids[completed%ids.length]:null};
  }
  return room.round_progress||{};
}
function renderConversationProgress(room){
  const progress=$('turn-progress'),description=$('progress-description'),panel=$('conversation-progress');
  const {completed,total,active_agent_id}=roundProgress(room);
  const preparing=state.openingPending&&room.state==='idle'||Boolean(pendingQuestionRoom&&pendingQuestionRoom===room.room_id);
  const active=activeRoomStates.has(room.state);
  panel.hidden=!preparing&&!active;
  if(panel.hidden){progress.removeAttribute('value');return;}
  const speaking=!preparing&&total>0&&['running','opening','replying','pausing'].includes(room.state);
  let caption;
  if(speaking){
    progress.max=total;progress.value=completed;
    const count=msg("{0} of {1} turns published",completed,total);
    caption=active_agent_id?joinText([msg("{0} is preparing a reply",label(active_agent_id)),count]):count;
  }else{
    progress.removeAttribute('value');
    caption=preparing?msg("Preparing your question…"):room.state==='synthesizing'?msg("Checking which ideas everyone accepts…"):
      room.state==='compiling'?msg("Preparing the consensus agent…"):roomStates[room.state];
  }
  if(description.textContent!==formatText(caption))setText(description,caption);
}
function renderParticipants(room){
  const panel=$('participant-panel'),list=$('participant-list');
  const ids=room.participant_ids||[],active=roundProgress(room).active_agent_id;
  panel.hidden=!ids.length;
  const key=JSON.stringify([state.session.session_id,room.room_id,ids,active,room.last_seq,
    state.analysis.status,room.messages.find(m=>m.author_kind==='agent')?.evidence_scope,state.session.initial_opinion.revision]);
  if(key===renderedParticipants)return;
  renderedParticipants=key;
  const open=new Set([...list.querySelectorAll('details[open]')].map(e=>e.dataset.speaker));
  list.replaceChildren();
  for(const id of ids){
    const card=node('article',undefined,'participant-card'),p=perspective(id);
    const latest=room.messages.findLast(m=>m.agent_id===id);
    const expired=state.analysis.status==='expired'||latest?.evidence_scope==='expired';
    const pending=active&&(!latest||room.state==='replying'&&latest.phase!=='reply'||
      room.state==='running'&&latest.round_id!==room.messages.findLast(m=>m.author_kind==='user')?.round_id);
    card.append(node('strong',label(id)),node('small',active===id?msg("Speaking"):latest&&!pending?msg("Published"):msg("Waiting to speak")));
    if(p&&!expired){
      card.append(node('small',msg("Starting position")),node('p',claimText(p.core_claim_id,p.text)));
    }else if(room.kind==='synthesis_chat'&&!expired){
      const agent=loadConsensusProfile(room);
      if(agent&&Date.parse(agent.expires_at)>Date.now()){
        for(const claim of agent.accepted_claims)card.append(node('p',claim.text));
      }else card.append(node('p',msg("Ask about a shared claim or one of its conditions.")));
    }
    const grounds=(p?.grounds||[]).filter(g=>g.role==='essential_condition');
    const idea=latest?.points?.find(point=>point.origin==='ai_reasoning')||latest?.points?.find(point=>point.origin==='external_evidence');
    if(!expired&&(idea||grounds.length)){
      const detail=node('details');detail.dataset.speaker=id;detail.open=open.has(id);
      detail.append(node('summary',idea?msg("Latest contribution"):msg("Premises and conditions to consider")));
      if(idea)detail.append(node('p',idea.text));
      for(const g of grounds)detail.append(node('p',joinText([msg("Condition:"),claimText(g.claim_id,g.text)],' ')));
      card.append(detail);
    }
    list.append(card);
  }
  if(state.session.initial_opinion.text.trim()){
    const own=node('details',undefined,'participant-card');own.dataset.speaker='user';own.open=open.has('user');
    own.append(node('summary',msg("My starting view")),node('p',state.session.initial_opinion.text));list.append(own);
  }
}
function updateTranscript(room){
  const key=JSON.stringify([state.session.session_id,room.room_id,room.messages.find(m=>m.author_kind==='agent')?.evidence_scope==='expired']);
  const previous=renderedTranscript;
  if(previous?.key!==key||previous.count>room.messages.length)renderMessages();
  else if(previous.count<room.messages.length)renderMessages(previous.count);
  renderedTranscript={key,count:room.messages.length};
}
function renderRoom(){
  const room=state.room;
  $('empty-conversation').hidden=true;$('chat-workspace').hidden=false;
  updateTranscript(room);
  renderRooms();
  renderConclusion(room);
  renderParticipants(room);
  renderConversationProgress(room);
  const ids=room.participant_ids||[];
  $('room-avatars').replaceChildren(...ids.map(id=>avatar(id)));
  setText($('room-title'), ids.length ? joinText(ids.map(label),' × ') : msg("Your conversation"));
  const automatic=room.kind==='structured_debate'||room.kind==='debate_draft';
  $('messages').classList.toggle('structured-transcript',automatic);
  $('show-debate-result').hidden=!room.conclusion;
  $('return-to-group').hidden=!room.plan?.source_room_id;
  $('group-consensus').hidden=automatic||room.mode!=='group'||!room.turn_count||
    !supportsDebate(ids.length)||!['awaiting_user','paused','closed','exhausted'].includes(room.state);
  $('group-consensus').disabled=Boolean(pendingQuestionRoom);
  setText($('room-summary'), automatic?msg("Read the positions, replies and final conclusion."):
    room.kind==='synthesis_chat'?msg("Ask about the shared claims and conditions."):
    room.mode==='group'?msg("Different perspectives, in one conversation."):msg("A conversation with this perspective."));
  const names={
    idle:msg("Start with a question."),running:msg("A perspective is responding."),
    opening:msg("Each perspective is describing its position."),replying:msg("The participants are replying to each other."),
    synthesizing:msg("The participants are reviewing shared claims and disagreements."),compiling:msg("Preparing the debate conclusion."),
    pausing:msg("Pausing after the current response."),paused:automatic?msg("The debate is paused. You can resume it."):msg("The conversation is paused. Ask a question or resume."),
    awaiting_user:msg("The conversation is complete. You can ask a follow-up question."),
    closed:msg("This conversation has ended."),closing:msg("Closing after the current response."),
    error:msg("Some replies could not be completed. Earlier turns are saved."),
    exhausted:msg("This conversation reached its limit."),needs_reconciliation:msg("The run status needs review.")
  };
  const stateParts = [names[room.state]||roomStates[room.state]||room.state];
  if(automatic&&room.conclusion)stateParts.push(room.turn_count+'/'+room.turn_limit);
  if(room.error_code)stateParts.push(msg(errorText(room.error_code)));
  setText($('room-state'),joinText(stateParts));
  $('recover-room').hidden=automatic||room.state!=='error';
  const target=$('question-target'),lastTarget=target.value;
  $('address-agent').hidden=automatic||room.mode!=='group';
  if(!$('address-agent').hidden){
    const all=node('option',msg("Everyone"));all.value='';target.replaceChildren(all);
    for(const id of ids){const option=node('option',label(id));option.value=id;target.append(option);}
    if(ids.includes(lastTarget))target.value=lastTarget;
  }
  const openingQuestion=$('opening-question');
  openingQuestion.readOnly=Boolean(room.plan)&&room.state==='idle';
  if(openingQuestion.readOnly){openingQuestion.value=room.plan.question;openingQuestion.removeAttribute('data-suggested');}
  $('opening').hidden=room.state!=='idle';
  $('opening').querySelector('button[type=submit]').disabled=state.openingPending||room.can_start===false;
  setText($('opening').querySelector('h2'), automatic?msg("Which issue would you like to debate?"):msg("What would you like to ask?"));
  setText($('opening-submit-label'), automatic?msg("Start automatic debate"):msg("Start conversation"));
  $('pause').disabled=automatic?!room.can_pause:!['running','awaiting_user'].includes(room.state);
  $('resume').disabled=!room.can_resume;
  $('next-round').hidden=automatic||room.kind==='synthesis_chat';
  $('next-round').disabled=!room.can_ask;
  $('close-room').disabled=automatic?!room.can_close:room.state==='closed'||room.state==='closing';
  $('interject').hidden=automatic||(room.kind==='synthesis_chat'?!room.can_ask:
    ['idle','closed','closing','exhausted','needs_reconciliation','error'].includes(room.state));
}
function watchRoom(){
  clearTimeout(state.roomTimer);
  if(activeRoomStates.has(state.room?.state)){
    state.roomTimer=setTimeout(()=>refreshRoom().catch(error=>{
      status(error.message);
      if(!error.code)watchRoom();
    }),700);
  }
}
async function refreshRoom(){
  const previous=state.room;
  if(!previous)return;
  if(previous.room_id){
    const latest=await api(roomPath(previous));
    if(state.room!==previous)return;
    state.room=latest;
  }
  renderRoom();
  watchRoom();
}
async function control(action){
  const roomId=state.room?.room_id;
  if(!roomId)return;
  const rid=requestId();
  for(let attempt=0;attempt<3;attempt++){
    await refreshRoom();
    const room=state.room;
    if(room?.room_id!==roomId)return;
    try{
      await api(roomPath(room)+'/control','POST',{action,expected_revision:room.revision,request_id:rid});
      if(state.room?.room_id===roomId)await refreshRoom();
      return;
    }catch(error){if(error.code!=='revision_conflict'||attempt===2)throw error;}
  }
}
async function openSynthesisChat(debate,button){
  if(button.disabled)return;
  button.disabled=true;
  try{
    const selected=debate.synthesis_agent;
    const resource='/synthesis-agents/'+encodeURIComponent(selected.agent_id);
    const agent=await api(resource);
    if(!agent.can_ask)throw new Error("The consensus agent is not available for new questions right now.");
    const room=await retryableWrite('chat',resource+'/rooms','POST',{
      agent_revision:agent.revision,initial_revision:state.session.initial_opinion.revision});
    await refreshSession();
    if(state.room?.room_id!==debate.room_id)return;
    setRoom(room);
    $('opening-question').value='';$('opening-question').removeAttribute('data-suggested');
    await refreshRoom();
    showStep('converse');
    status('');
    $('opening-question').focus();
  }catch(error){status(error.message);}
  finally{button.disabled=false;}
}
async function refreshReflection(){
  await refreshSession();setText($('initial-copy'), state.session.initial_opinion.text);
  if (!currentViewEdited) {
    const current = state.session.current_opinion;
    $('current').value = current.revision ? current.text : state.session.initial_opinion.text;
  }
  updateRestoreInitial();
  $('reflection-rooms').replaceChildren();
  state.session.rooms.forEach((room,i)=>{const line=node('div',undefined,'reflection-room'),button=node('button',joinText([roomName(room,i),roomStates[room.state]||room.state]));button.type='button';button.onclick=()=>{setRoom(room);refreshReflection().catch(error=>status(error.message));};line.append(button);$('reflection-rooms').append(line);});
  $('context-messages').replaceChildren();
  if(state.room){await refreshRoom();for(const message of state.room.messages){const line=node('label',undefined,'context-item'),check=node('input');check.type='checkbox';check.checked=state.context.has(message.message_id);check.onchange=()=>{if(check.checked){if(state.context.size>=24){check.checked=false;status(errorText('context_capacity'));return;}state.context.add(message.message_id);}else state.context.delete(message.message_id);};line.append(check,node('span',joinText([message.author_kind==='user'?msg("You"):label(message.agent_id), (message.body||message.points?.map(p=>p.text).join(' ')||'').slice(0,160)||msg("No evidence")],': ')));$('context-messages').append(line);}}
  if(state.reflectionResult)highlightReflection(state.reflectionResult);
}
function updateRestoreInitial(){
  $('restore-initial').hidden = $('current').hidden || Boolean($('current').value) || !state.session?.initial_opinion.text;
}
function clearInsights(){state.reflectionJob=null;state.reflectionResult=null;$('suggestions').replaceChildren();$('insight-panel').hidden=true;$('reflection-layout').classList.remove('review');$('current').hidden=false;$('current-copy').hidden=true;$('edit-current').hidden=true;updateRestoreInitial();}
async function saveCurrent() {
  const value = $('current').value;
  const current = state.session.current_opinion;
  if (!current.revision || value !== current.text) {
    await retryableWrite('current', base()+'/opinions/current', 'PUT', {text:value, expected_revision:current.revision});
    clearInsights();
    await refreshSession();
  }
  return state.session.current_opinion.revision;
}
async function jumpTo(mid,refs){const ref=refs?.find(m=>m.message_id===mid);if(ref){await chooseRoom(ref.room_id);$('message-'+mid)?.scrollIntoView({block:'center'});}}
function highlightReflection(result){
  for(const kind of ['initial','current']){const opinion=state.session[kind+'_opinion'],spans=[];for(const [key,items] of Object.entries(result.categories))for(const item of items)for(const id of item[kind+'_span_ids']){const span=opinion.segments.find(s=>s.id===id);if(span)spans.push({...span,category:key});}highlighted($(kind+'-copy'),opinion.text,spans);}
}
const categories = {stayed:msg("What stayed the same"), changed:msg("What changed"), newly_learned:msg("Newly learned"), worth_more_thought:msg("Worth more thought")};
function renderSuggestions(result){
  $('suggestions').replaceChildren();$('reflection-tabs').replaceChildren();$('insight-panel').hidden=false;$('reflection-layout').classList.add('review');$('current').hidden=true;$('current-copy').hidden=false;$('edit-current').hidden=false;updateRestoreInitial();
  const all=node('button',msg("All"),'active');all.type='button';all.onclick=()=>{$('suggestions').scrollTop=0;};$('reflection-tabs').append(all);
  let number=0;
  for(const [key,title] of Object.entries(categories)){number++;const items=result.categories[key],group=node('section',undefined,'suggestion '+key);group.id='insight-'+key;
    const heading=node('h3');heading.append(node('span',number,'category-number'),node('span',title),node('small',msg("{0} points",items.length)));group.append(heading);
    const tab=node('button',joinText([title,items.length]),key);tab.type='button';tab.onclick=()=>group.scrollIntoView({block:'nearest'});$('reflection-tabs').append(tab);
    for(const item of items){const row=node('article',undefined,'reflection-insight');row.append(node('p',item.explanation));
      for(const kind of ['initial','current']){const ids=item[kind+'_span_ids'],spans=state.session[kind+'_opinion'].segments.filter(s=>ids.includes(s.id));if(spans.length)row.append(node('blockquote',msg(kind==='initial'?"BEFORE · {0}":"NOW · {0}",spans.map(s=>s.text).join(' ')),'opinion-reference'));}
      for(const mid of item.related_message_ids){const button=node('button',msg("Related conversation"),'source-button');button.type='button';button.onclick=()=>jumpTo(mid,result.context_message_refs).catch(e=>status(e.message));row.append(button);}group.append(row);
    }
    if(!items.length)group.append(node('p',msg("No suggestions in this category."),'hint'));
    const adopt=node('button',msg("Use these suggestions"),'secondary');adopt.type='button';adopt.disabled=!items.length;adopt.onclick=()=>{$(key).value=items.map(i=>i.explanation).join('\n');$('reflection-save-panel').open=true;$(key).focus();};group.append(adopt);$('suggestions').append(group);
  }
  highlightReflection(result);
}
async function openSavedReflection(id){
  const value=await api(base()+'/reflections/'+encodeURIComponent(id));
  state.saved=value;
  clearInsights();
  const view=$('saved-view');
  view.replaceChildren(node('h3',value.stale?msg("Reflection saved with an earlier view"):msg("Saved reflection")));
  for(const [key,title] of Object.entries(categories)){
    view.append(node('h3',title));
    $(key).value=value.user_items[key].map(item=>item.text).join('\n');
    for(const entry of value.user_items[key]){
      view.append(node('p',entry.text));
      for(const mid of entry.related_message_ids){
        const link=node('button',msg("Related conversation"),'source-button');
        link.type='button';
        link.onclick=()=>jumpTo(mid,value.context_message_refs).catch(error=>status(error.message));
        view.append(link);
      }
    }
  }
  $('reflection-save-panel').open=true;
  setText($('save-state'), msg("You can edit this reflection. Earlier versions are saved."));
}

function renderSaved(){
  const list=$('saved-reflections');
  list.replaceChildren();
  for(const item of state.session.reflections){
    const button=node('button',msg("View reflection · Revision {0}",item.revision),'secondary');
    button.type='button';
    button.onclick=()=>openSavedReflection(item.reflection_id).catch(error=>status(error.message));
    list.append(button);
  }
}

function readStored(storage,key){
  try{return JSON.parse(storage.getItem(key)||'null');}catch{return null;}
}

function browserRecords(){
  const active=readStored(localStorage,savedSessionKey);
  const saved=readStored(localStorage,librarySessionsKey);
  const records=[active,...(Array.isArray(saved)?saved:[])];
  return [...new Map(records.reverse().filter(item=>typeof item?.session_id==='string'&&typeof item.token==='string')
    .map(item=>[item.session_id,item])).values()].reverse();
}

function rememberSession(sessionId,token){
  const record={session_id:sessionId,token};
  const records=browserRecords().filter(item=>item.session_id!==sessionId);
  localStorage.setItem(librarySessionsKey,JSON.stringify([record,...records]));
  localStorage.setItem(savedSessionKey,JSON.stringify(record));
  sessionStorage.setItem(tabSessionKey,sessionId);
}

function activeAccess() {
  const id = sessionStorage.getItem(tabSessionKey);
  if (id === null) return readStored(localStorage, savedSessionKey);
  return id ? browserRecords().find(record => record.session_id === id) : null;
}

function leaveSession() {
  const active = activeAccess();
  if (active && readStored(localStorage, savedSessionKey)?.session_id === active.session_id) {
    localStorage.removeItem(savedSessionKey);
  }
  sessionStorage.setItem(tabSessionKey, '');
  sessionStorage.removeItem(lastRoomKey);
}

function availableAnalysis(analysis){
  return ['experimental','available'].includes(analysis.status);
}

function libraryRow(title,detail,action,onClick){
  const row=node('div',undefined,'library-item');
  const information=node('div');
  information.append(node('strong',title),node('small',detail,'muted'));
  const button=node('button',action,'secondary');
  button.type='button';
  setLabel(button,'aria-label',joinText([action,title]));
  button.disabled=!onClick;
  if(onClick)button.onclick=onClick;
  row.append(information,button);
  return row;
}

function openDestination(destination){
  if (!state.session && destination.analysis_id && destination.analysis_id === state.analysis?.analysis_id) {
    closeLibrary();
    return;
  }
  sessionStorage.setItem(libraryDestinationKey,JSON.stringify(destination));
  if(history.state?.reviewLibrary){
    const {reviewLibrary,...rest}=history.state;
    history.replaceState(rest,'');
  }
  location.reload();
}

async function renderLibrary(){
  const load=++libraryLoad;
  const videos=$('library-videos');
  const records=$('library-records');
  videos.replaceChildren(node('p',msg("Loading analyzed videos…"),'muted'));
  records.replaceChildren(node('p',msg("Loading your records…"),'muted'));
  const current=()=>load===libraryLoad&&$('library-dialog').open;
  const browser=browserRecords();
  const catalog=api('/analyses','GET',undefined,'').then(({analyses})=>{
    if(!current())return;
    videos.replaceChildren();
    for(const analysis of analyses){
      const title=analysis.video?.title||msg("Registered discussion");
      const detail=availableAnalysis(analysis)
        ? msg("{0} analyzed comments · {1} perspectives",analysis.analyzed_comments,analysis.perspectives.length)
        : msg("Source refresh required");
      videos.append(libraryRow(title,detail,availableAnalysis(analysis)?msg("Open video"):msg("Expired"),
        availableAnalysis(analysis)?()=>openDestination({analysis_id:analysis.analysis_id}):null));
    }
    if(!analyses.length)videos.append(node('p',msg("No analyzed videos are available."),'muted'));
  }).catch(()=>{
    if(!current())return;
    const retry=node('button',msg("Retry loading videos"),'secondary');
    retry.type='button';
    retry.onclick=async()=>{
      await renderLibrary();
      if($('library-dialog').open && [document.body, $('library-dialog')].includes(document.activeElement))
        videos.querySelector('button:not(:disabled)')?.focus();
    };
    videos.replaceChildren(node('p',msg("Could not load the video list."),'muted'),retry);
  });
  const recordsLoad=Promise.allSettled(browser.map(async access=>{
    const session=await api('/sessions/'+encodeURIComponent(access.session_id),'GET',undefined,access.token);
    return {access,session};
  })).then(results=>{
    if(!current())return;
    records.replaceChildren();
    for(const {status:resultStatus,value} of results){
      if(resultStatus!=='fulfilled')continue;
      const {access,session}=value;
      const title=session.analysis.video?.title||msg("Registered discussion");
      for(const [index,room] of session.rooms.entries()){
        records.append(libraryRow(roomName(room,index),joinText([title,roomStates[room.state]||room.state]),msg("Open"),
          ()=>openDestination({access,room_id:room.room_id})));
      }
      for(const reflection of session.reflections){
        records.append(libraryRow(msg("Reflection · Revision {0}",reflection.revision),title,msg("Open"),
          ()=>openDestination({access,reflection_id:reflection.reflection_id})));
      }
    }
    if(!records.childElementCount){
      records.append(node('p',results.some(result=>result.status==='rejected')
        ? msg("No accessible records. A session may have expired.") : msg("No saved debates or reflections yet."),'muted'));
      const start=node('button',msg("Start a review"),'secondary');
      start.type='button';
      start.onclick=closeLibrary;
      records.append(start);
    }
  });
  await Promise.all([catalog,recordsLoad]);
}

function openLibrary(push=true){
  const dialog=$('library-dialog');
  if(dialog.open)return;
  if(push&&!history.state?.reviewLibrary)history.pushState({...history.state,reviewLibrary:true},'');
  openDialog('library-dialog');
  void renderLibrary();
}

function closeLibrary(){
  if(history.state?.reviewLibrary)history.back();
  else closeDialog('library-dialog');
}

$('open-library').onclick=()=>openLibrary();
$('browse-videos').onclick=()=>openLibrary();
$('close-library').onclick=closeLibrary;
$('library-dialog').addEventListener('cancel',event=>{event.preventDefault();closeLibrary();});
window.addEventListener('popstate',()=>{
  if(history.state?.reviewLibrary)openLibrary(false);
  else closeDialog('library-dialog');
});

async function enter(session,destination){
  setSession(session);
  state.analysis=session.analysis;
  sessionStorage.setItem(selectedAnalysisKey,session.analysis_id);
  renderAnalysis();
  $('before').hidden=true;
  $('workspace').hidden=false;
  document.querySelectorAll('button[data-step]').forEach(button => { button.disabled = false; });
  renderPerspectives();
  status('');
  if(destination?.reflection_id&&session.reflections.some(item=>item.reflection_id===destination.reflection_id)){
    showStep('reflect');
    await openSavedReflection(destination.reflection_id);
    return;
  }
  const last=destination?.room_id?{session_id:session.session_id,room_id:destination.room_id}:readStored(sessionStorage,lastRoomKey);
  if(last?.session_id===session.session_id&&session.rooms.some(room=>room.room_id===last.room_id)){
    const stepBeforeRestore=document.body.dataset.step;
    try{
      await chooseRoom(last.room_id);
    }catch(error){
      if(state.room?.room_id===last.room_id)setRoom(null);
      if(document.body.dataset.step===stepBeforeRestore){
        showStep('explore');
        status(msg("Could not restore the last conversation. Reopen it from the conversation list."));
      }
    }
    return;
  }
  showStep('explore');
  $('explore-title').focus({preventScroll:true});
}
$('initial').oninput=()=>{setText($('initial-count'), msg("Characters: {0} / 500",[...$('initial').value].length));};
$('clear-initial').onclick=()=>{$('initial').value='';$('initial').oninput();$('initial').focus();};
$('video-url').oninput=()=>{setText($('video-lookup-status'), '');};
$('video-lookup').onsubmit=async event=>{
  event.preventDefault();
  const button=$('open-video-url');
  if(button.disabled)return;
  const begin=$('begin').querySelector('button[type=submit]');
  const beforeDisabled=begin.disabled;
  const feedback=$('video-lookup-status');
  const input=$('video-url');
  button.disabled=true;
  begin.disabled=true;
  input.readOnly=true;
  setText(feedback, msg("Looking for a saved analysis…"));
  try{
    const query=new URLSearchParams({video:input.value});
    const {analyses}=await api('/analyses?'+query,'GET',undefined,'');
    const match=analyses.find(availableAnalysis);
    if(!match){
      setText(feedback, analyses.length
        ? msg("The saved analysis for this video has expired. Choose another video in Library.")
        : msg("This video has no saved analysis yet. Choose an analyzed video in Library."));
      return;
    }
    if(match.analysis_id===state.analysis?.analysis_id){
      setText(feedback, msg("This video is already open."));
      return;
    }
    openDestination({analysis_id:match.analysis_id});
  }catch(error){
    setText(feedback, error.code==='invalid_video_url'
      ? msg("Enter a valid YouTube video URL.")
      : msg("Could not look up this video. Try again."));
  }finally{
    input.readOnly=false;
    begin.disabled=beforeDisabled;
    button.disabled=false;
  }
};
$('begin').onsubmit=async event=>{
  event.preventDefault();
  const button=$('begin').querySelector('button[type=submit]');
  if(button.disabled)return;
  button.disabled=true;
  $('open-video-url').disabled=true;
  try{
    const session=await retryableWrite('begin','/sessions','POST',{analysis_id:state.analysis.analysis_id,
      bundle_revision:state.analysis.bundle_revision,initial_opinion:$('initial').value});
    rememberSession(session.session_id,state.token);
    await enter(session);
  }catch(error){status(error.message);}
  finally{button.disabled=false;$('open-video-url').disabled=false;}
};
$('edit-initial').onsubmit=async event=>{
  event.preventDefault();
  const text=$('initial-edit').value;
  if(text===state.session.initial_opinion.text){status(msg("This view is already saved."));return;}
  try{
    await retryableWrite('initial',base()+'/opinions/initial','PUT',{text,expected_revision:state.session.initial_opinion.revision});
    clearInsights();closeDialog('comparison');
    await refreshSession();
    currentComparisons();
    renderPerspectives();startComparisons();status(msg("Your initial view was saved."));
  }catch(error){status(error.message);}
};
let creatingChat=false;
async function openConversation(ids,automatic,button){
  if(creatingChat||state.openingPending||!ids.length)return;
  creatingChat=true;button.disabled=true;
  try{
    if(automatic&&supportsDebate(ids.length)){
      setRoom({kind:'debate_draft',mode:'group',state:'idle',turn_count:0,turn_limit:2*ids.length,
               participant_ids:ids,messages:[],create_request_id:requestId(),start_request_id:requestId()});
      $('opening-question').value='';$('opening-question').removeAttribute('data-suggested');
    }else{
      const room=await retryableWrite('chat',base()+'/rooms','POST',{mode:ids.length===1?'one_to_one':'group',
        participant_ids:ids,initial_revision:state.session.initial_opinion.revision});
      setRoom(room);$('opening-question').value=formatText(msg(defaultOpeningQuestion));$('opening-question').setAttribute('data-suggested','');await refreshSession();
    }
    await refreshRoom();showStep('converse');status('');$('opening-question').focus();
  }catch(error){status(error.message);setText($('chat-picker-hint'), interfaceNotice(error.message));}
  finally{creatingChat=false;button.disabled=false;updateSelection();}
}
$('open-room').onclick=()=>openConversation([...state.selected],supportsDebate(state.selected.size),$('open-room'));
function chatParticipants(){return [...$('chat-options').querySelectorAll('input:checked')].map(input=>input.value);}
function updateChatPicker(){
  const ids=chatParticipants(),limit=ids.length>=3;
  for(const input of $('chat-options').querySelectorAll('input'))input.disabled=limit&&!input.checked;
  $('chat-format-label').hidden=!supportsDebate(ids.length);
  setText($('chat-picker-hint'), state.analysis.perspectives.length?msg("{0} / 3 selected",ids.length):msg("This video has no available perspectives."));
  $('chat-picker').querySelector('button[type=submit]').disabled=!ids.length||creatingChat;
}
function showChatPicker(preselected = []){
  $('chat-options').replaceChildren();$('chat-format').value='conversation';
  for(const p of state.analysis.perspectives){
    const option=node('label'),check=node('input');check.type='checkbox';check.value=p.id;
    check.checked=preselected.includes(p.id);
    check.onchange=updateChatPicker;option.append(check,node('span',label(p.id)));$('chat-options').append(option);
  }
  updateChatPicker();openDialog('new-chat-dialog');
}
$('chat-picker').onsubmit=event=>{
  event.preventDefault();openConversation(chatParticipants(),$('chat-format').value==='debate',$('chat-picker').querySelector('button[type=submit]'));
};
$('close-chat-picker').onclick=()=>closeDialog('new-chat-dialog');
$('rooms').onchange=()=>{if($('rooms').value)chooseRoom($('rooms').value).catch(e=>status(e.message));};
$('room-search').oninput=renderRooms;
document.querySelectorAll('[data-room-filter]').forEach(button=>button.onclick=()=>{state.roomFilter=button.dataset.roomFilter;document.querySelectorAll('[data-room-filter]').forEach(b=>b.classList.toggle('active',b===button));renderRooms();});
$('new-chat').onclick=()=>showChatPicker();
$('empty-new-chat').onclick=()=>showChatPicker();
$('show-debate-result').onclick=()=>{
  const panel=$('debate-conclusion');
  panel.scrollIntoView({behavior:'smooth',block:'start'});
  panel.focus({preventScroll:true});
};
$('opening').onsubmit=async event=>{
  event.preventDefault();
  let room=state.room;
  if(state.openingPending||room?.state!=='idle'||room.can_start===false)return;
  const question=room.plan?.question||$('opening-question').value;
  if(!question.trim()){
    status(msg("Enter an opening question."));
    $('opening-question').focus();
    return;
  }
  if([...question].length>1000){
    status(msg("Use 1,000 characters or fewer for your question."));
    $('opening-question').focus();
    return;
  }
  state.openingPending=true;
  renderConversationProgress(room);
  status('');
  $('opening').querySelector('button[type=submit]').disabled=true;
  try{
    if(room.kind==='debate_draft'){
      const draft=room;
      const create={analysis_revision:state.session.bundle_revision,participant_ids:room.participant_ids,
        question,initial_revision:state.session.initial_opinion.revision,request_id:room.create_request_id};
      const key=JSON.stringify(create);
      if(draft.createKey&&draft.createKey!==key)create.request_id=draft.create_request_id=requestId();
      draft.createKey=JSON.stringify(create);
      room=await api(base()+'/debates','POST',create);
      if(state.room!==draft)return;
      room.start_request_id=draft.start_request_id;
      setRoom(room);
      rememberConversation();
      await refreshSession();
    }
    const start={expected_revision:room.revision,request_id:room.start_request_id||requestId()};
    if(room.kind!=='structured_debate')start.opening_question=question;
    await api(roomPath(room)+'/start','POST',start);
  }catch(error){status(error.message);}
  finally{
    state.openingPending=false;
    if(state.room===room)await refreshRoom().catch(error=>status(error.message));
  }
};
for(const [id,action] of [['pause','pause'],['resume','resume'],['next-round','next_round'],['close-room','close']])$(id).onclick=()=>control(action).catch(e=>status(e.message));
$('recover-room').onclick=async()=>{
  const roomId=state.room?.room_id,button=$('recover-room');
  if(button.disabled)return;
  button.disabled=true;
  try{await control('acknowledge_error');if(state.room?.room_id===roomId&&state.room.can_ask)$('question').focus();}
  catch(error){status(error.message);}finally{button.disabled=false;}
};
async function revisionForQuestion(roomId) {
  await refreshRoom();
  if (state.room?.room_id !== roomId) return null;
  if (state.room.state === 'running') await control('pause');
  while (state.room?.room_id === roomId && state.room.state === 'pausing') {
    await wait(600);
    await refreshRoom();
  }
  return state.room?.room_id === roomId ? state.room.revision : null;
}
function asksForGroupConclusion(question){
  // Only explicit collective requests take this shortcut. The button is available for any wording.
  const text=question.trim().toLowerCase();
  if(/합의.{0,8}(말고|아니|하지\s*마|어렵|불가능)|((don't|do not|without|why|how is)\s+.{0,30}(consensus|agreement|common ground))/.test(text))return false;
  return /(합의점|공통\s*결론|공통\s*제안|공통점).{0,18}(뭐|무엇|찾아|정리|도출|제안|알려|있[나어을])|(?:너희|여러분|셋|둘|모두|다들|다\s*같이).{0,15}결론.{0,10}(뭐|무엇|정리|내려|알려)|(?:what|find|give|reach|suggest|summari[sz]e).{0,48}(?:common ground|shared (?:idea|proposal|conclusion)|group consensus|all agree (?:on|to)|your consensus)|what(?:’s|'s| is) (?:the|your) consensus/.test(text);
}
async function findGroupConclusion(question){
  const sourceRoom=state.room;
  if(pendingQuestionRoom||!sourceRoom?.room_id||!supportsDebate(sourceRoom.participant_ids.length))return;
  if([...question].length>1000){status(msg("Use 1,000 characters or fewer for your question."));return;}
  pendingQuestionRoom=sourceRoom.room_id;renderConversationProgress(sourceRoom);$('group-consensus').disabled=true;
  try{
    if(activeRoomStates.has(sourceRoom.state))await revisionForQuestion(sourceRoom.room_id);
    if(state.room?.room_id!==sourceRoom.room_id)return;
    const room=state.room;
    const created=await retryableWrite('group-conclusion-'+room.room_id,base()+'/debates','POST',{
      analysis_revision:state.session.bundle_revision,participant_ids:room.participant_ids,
      question,initial_revision:state.session.initial_opinion.revision,
      source_room_id:room.room_id,source_cutoff_seq:room.last_seq});
    if(state.room?.room_id!==room.room_id)return;
    setRoom(created);rememberConversation();renderRoom();
    pendingQuestionRoom=created.room_id;renderConversationProgress(created);
    await refreshSession();
    if(created.state==='idle')await retryableWrite('start-conclusion-'+created.room_id,roomPath(created)+'/start','POST',
      {expected_revision:created.revision});
    status('');
  }catch(error){status(error.message);}
  finally{
    const pending=pendingQuestionRoom;pendingQuestionRoom=null;
    if(state.room?.room_id===pending||state.room?.room_id===sourceRoom.room_id)await refreshRoom().catch(error=>status(error.message));
  }
}
$('group-consensus').onclick=()=>findGroupConclusion($('question').value.trim()||
  formatText(msg("What practical idea can we agree on from this discussion, and under what conditions?")));
$('return-to-group').onclick=()=>chooseRoom(state.room.plan.source_room_id).catch(error=>status(error.message));
$('interject').onsubmit=async event=>{
  event.preventDefault();
  const button=$('interject').querySelector('button[type=submit]'),roomId=state.room?.room_id;
  const question=$('question').value,recipient=$('address-agent').hidden?'':$('question-target').value;
  if(button.disabled||pendingQuestionRoom||!roomId||!question.trim())return;
  if(!recipient&&state.room.mode==='group'&&state.room.turn_count>0&&supportsDebate(state.room.participant_ids.length)&&asksForGroupConclusion(question)){
    await findGroupConclusion(question);return;
  }
  button.disabled=true;
  pendingQuestionRoom=roomId;renderConversationProgress(state.room);
  try{
    await retryableWrite('message-'+roomId,'/rooms/'+roomId+'/messages','POST',{
      text:question,reply_to_message_id:null,...(recipient?{target_agent_id:recipient}:{})
    },()=>revisionForQuestion(roomId));
    if(state.room?.room_id===roomId){if($('question').value===question)$('question').value='';await refreshRoom();}
  }catch(error){status(error.message);}finally{
    pendingQuestionRoom=null;button.disabled=false;
    if(state.room?.room_id===roomId){renderConversationProgress(state.room);$('group-consensus').disabled=false;}
  }
};
document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{$('question').value=formatText(msg(button.dataset.prompt));$('question').focus();});
$('agent-info').onclick=async()=>{
  const container=$('perspective-info');
  container.replaceChildren();
  const room=state.room;
  try{
    if(room?.kind==='synthesis_chat'){
      const agent=await api('/synthesis-agents/'+encodeURIComponent(room.participant_ids[0]));
      if(state.room?.room_id!==room.room_id)return;
      container.append(node('h3',msg("Consensus agent")),node('p',joinText(agent.parent_refs.map(row=>label(row.agent_id)),', ')));
      for(const claim of agent.accepted_claims)container.append(node('p',claim.text));
    }else{
      for(const id of room?.participant_ids||[]){
        const p=perspective(id);
        const entry=node('section',undefined,'perspective-info-entry');
        entry.append(node('h3',label(id)),node('p',claimText(p.core_claim_id, p.text)),node('small',msg(p.source_count===1?"{0} direct source comment":"{0} direct source comments",p.source_count)));
        container.append(entry);
      }
    }
    openDialog('perspective-dialog');
  }catch(error){status(error.message);}
};
for(const [button,id] of [['close-comparison','comparison'],['close-source','source-dialog'],['close-perspective','perspective-dialog']])$(button).onclick=()=>closeDialog(id);
$('comparison').addEventListener('close',()=>{$('comparison').hidden=true;});
$('go-reflect').onclick=()=>showStep('reflect');document.querySelectorAll('button[data-step]').forEach(button=>button.onclick=()=>showStep(button.dataset.step));
$('current').oninput=()=>{currentViewEdited=true;updateRestoreInitial();};
$('restore-initial').onclick=()=>{
  $('current').value=state.session.initial_opinion.text;
  $('current').oninput();
  $('current').focus();
};
$('edit-current').onclick=()=>{clearInsights();$('current').focus();};
$('write-manually').onclick=()=>{$('reflection-save-panel').open=true;$('stayed').focus();};
$('analyze').onclick=async()=>{const button=$('analyze');button.disabled=true;try{await saveCurrent();status(msg("Reviewing your views and selected conversations."));const value=await api(base()+'/reflection-analyses','POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,context_message_ids:[...state.context],request_id:requestId()});const job=await pollJob(value);if(job.stale){status(msg("Your view has changed. Analyze the current version again."));return;}state.reflectionJob=job.job_id;state.reflectionResult=job.result;renderSuggestions(job.result);status(msg("Choose the suggestions you want or edit them before saving."));}catch(e){status(e.message);}finally{button.disabled=false;}};
$('save-reflection').onsubmit = async event => {
  event.preventDefault();
  const button = $('save-reflection').querySelector('button[type=submit]');
  if (button.disabled) return;
  button.disabled = true;
  try {
    await saveCurrent();
    const saved = state.saved;
    const sameOpinions = saved && ['initial','current'].every(kind => saved[kind+'_revision'] === state.session[kind+'_opinion'].revision);
    const userItems = {};
    for (const key of Object.keys(categories)) {
      const lines = $(key).value.split('\n').filter(line => line.trim());
      userItems[key] = lines.map(text => {
        const original = state.reflectionResult?.categories[key].find(item => item.explanation === text)
          || (sameOpinions && saved.user_items[key].find(item => item.text === text));
        return {text, initial_span_ids:original?.initial_span_ids || [], current_span_ids:original?.current_span_ids || [],
          related_message_ids:original?.related_message_ids || []};
      });
    }
    const path = base()+'/reflections'+(saved ? '/'+saved.reflection_id : '');
    const value = await retryableWrite('reflection', path, saved ? 'PUT' : 'POST', {
      initial_revision:state.session.initial_opinion.revision, current_revision:state.session.current_opinion.revision,
      analysis_job_id:state.reflectionJob ?? (sameOpinions ? saved.analysis_job_id : null),
      user_items:userItems, expected_revision:saved?.revision || 0
    });
    state.saved = value;
    setText($('save-state'), msg("Saved · Revision {0}",value.revision));
    status('');
    await refreshSession();
  } catch (error) {
    status(error.message);
  } finally {
    button.disabled = false;
  }
};
$('new-session').onclick=()=>{clearTimeout(state.roomTimer);leaveSession();location.reload();};

async function start(){
  const destination=readStored(sessionStorage,libraryDestinationKey);
  sessionStorage.removeItem(libraryDestinationKey);
  if(history.state?.reviewLibrary){
    const {reviewLibrary,...rest}=history.state;
    history.replaceState(rest,'');
  }
  let resumeMessage='';
  if(destination?.analysis_id){
    sessionStorage.setItem(selectedAnalysisKey,destination.analysis_id);
    leaveSession();
  }
  const saved=destination?.access||activeAccess();
  if(saved){
    state.token=saved.token;
    let session;
    try{
      session=await api('/sessions/'+encodeURIComponent(saved.session_id));
    }catch(error){
      if(!['session_expired','session_token_required','resource_missing','analysis_revision_conflict'].includes(error.code)){
        status(msg("Your records could not be loaded. Refresh and try again."));
        return;
      }
      if(readStored(localStorage,savedSessionKey)?.session_id===saved.session_id){
        localStorage.removeItem(savedSessionKey);
      }
      if (sessionStorage.getItem(tabSessionKey) === saved.session_id) leaveSession();
      state.token='';
      resumeMessage=error.code==='session_expired'
        ? msg("Your previous session has expired. Start a new one.")
        : msg("The previous record could not be opened. Choose another record or analysis in Library.");
      if(destination?.access&&activeAccess()){
        await start();
        status(resumeMessage);
        return;
      }
    }
    if(session){
      rememberSession(session.session_id,state.token);
      await enter(session,destination);
      return;
    }
  }
  const available=await api('/analyses');
  const preferred=sessionStorage.getItem(selectedAnalysisKey);
  state.analysis=available.analyses.find(item=>item.analysis_id===preferred&&availableAnalysis(item))
    || available.analyses.find(availableAnalysis);
  if(!state.analysis){status(msg("No analyses are available yet."));return;}
  renderAnalysis();
  $('begin').querySelector('button[type=submit]').disabled=false;
  status(resumeMessage||(preferred&&preferred!==state.analysis.analysis_id
    ? msg("This analysis is unavailable. Check the video now shown.")
    : msg("Enter your initial view, or leave it blank to explore.")));
}

installInterfaceLanguage();
$('opening-question').addEventListener('input',()=>$('opening-question').removeAttribute('data-suggested'));
start().catch(error=>status(error.message)).finally(()=>{$('open-video-url').disabled=false;});
