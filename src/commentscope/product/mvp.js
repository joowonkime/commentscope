'use strict';
const $ = id => document.getElementById(id);
const categories = {stayed:'What stayed the same', changed:'What changed', newly_learned:'Newly learned', worth_more_thought:'Worth more thought'};
const state = {analysis:null, session:null, token:'', room:null, roomTimer:null, selected:new Set(), context:new Set(), comparisons:new Map(), reflectionJob:null, reflectionResult:null, saved:null, roomFilter:'all', openingPending:false, openComparison:null, sourceTexts:new Map(), editingInitial:false, closeness:new Map(), closenessSummary:new Map()};
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const requestId = () => crypto.randomUUID();
const savedSessionKey = 'commentscope-mvp-session';
const tabSessionKey = 'commentscope-mvp-active-tab';
const librarySessionsKey = 'commentscope-mvp-library-sessions';
const libraryDestinationKey = 'commentscope-mvp-library-destination';
const selectedAnalysisKey = 'commentscope-mvp-selected-analysis';
let libraryLoad = 0;
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function asset(name) { const img=node('img'); img.src='/mvp/assets/'+name+'.svg'; img.alt=''; return img; }
function status(text) { $('status').textContent=text; }
function errorText(code) { return ({revision_conflict:'내용이 갱신됐습니다. 최신 화면을 확인한 뒤 다시 눌러 주세요.',opinion_revision_conflict:'의견이 갱신됐습니다. 다시 확인해 주세요.',analysis_revision_conflict:'의견 또는 분석 버전이 달라졌습니다. 제안을 다시 확인하거나 직접 저장해 주세요.',resource_busy:'이미 토론이 진행 중입니다. 현재 기록에서 확인할 수 있습니다.',debate_not_ready:'이 토론은 현재 상태에서 다시 시작할 수 없습니다.',capacity_hold:'필수 근거의 분량이 커 검증이 보류됐습니다. 게시된 발언은 보존됩니다.',room_not_ready:'현재 응답이 끝나거나 대화가 정지한 뒤 질문할 수 있습니다.',budget_exhausted:'현재 AI 사용 한도에 도달했습니다. 기존 대화 읽기와 직접 저장은 가능합니다.',cycle_deadline:'이번 AI 실행 시간이 끝났습니다. 읽기와 직접 저장은 가능합니다.',unconfirmed_provider_call:'AI 서비스 응답과 과금 확인이 중단됐습니다. 운영자가 기록을 확인한 뒤 새 질문을 보낼 수 있습니다. 원댓글 조회와 직접 성찰 저장은 가능합니다.',reconcile_required:'AI 요청 기록을 운영자가 확인하고 있습니다. 원댓글을 보거나 Reflect에서 직접 작성해 저장할 수 있습니다.',source_expired:'근거 자료의 사용 기한이 지났습니다.',session_expired:'세션 기한이 지났습니다. 새로 시작해 주세요.',invalid_participants:'대화할 수 있는 관점을 하나 이상 선택해 주세요.',turn_limit:'이 대화의 발화 한도에 도달했습니다.',context_capacity:'관련 대화는 최대 24개까지 선택할 수 있습니다.',queue_capacity:'다른 작업을 처리하고 있습니다. 잠시 뒤 다시 눌러 주세요.',model_or_validation_failed:'AI 응답을 완료하지 못했습니다. 입력과 기존 기록은 보존됐습니다.'})[code] || '요청을 완료하지 못했습니다. 입력과 이전 기록을 확인해 주세요.'; }
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
    if (error instanceof TypeError) throw new Error('응답을 확인하지 못했습니다. 입력을 그대로 다시 보내면 같은 요청을 확인합니다.');
    throw error;
  }
  if (creatingSession) state.token = attempt.token;
  if (readStored(sessionStorage, key)?.requestId === attempt.requestId) sessionStorage.removeItem(key);
  return value;
}
function indexOf(id){return (state.analysis?.perspectives||[]).findIndex(p=>p.id===id);}
function perspective(id){return (state.analysis?.perspectives||[]).find(p=>p.id===id);}
function label(id){if(state.room?.kind==='synthesis_chat'&&state.room.participant_ids?.includes(id))return '합의 Agent';const p=perspective(id);return p?.display_name||p?.text||'Perspective';}
function avatar(id,small=false){const i=Math.max(0,indexOf(id)); return asset(small?'0385b':['4ea9b','5e642','baf01','d51bb','e77a2'][i%5]);}
function closeDialog(id){const dialog=$(id); if(dialog.open)dialog.close(); if(id==='comparison')dialog.hidden=true;}
function openDialog(id){const dialog=$(id); dialog.hidden=false; if(!dialog.open)dialog.showModal();}
function showStep(step){
  if(!state.session)return;
  if(state.editingInitial)leaveInitialEdit();
  $('before').hidden=true;$('workspace').hidden=false;
  if(step==='converse'&&!state.room&&state.session.rooms.length){chooseRoom(state.session.rooms[0].room_id).catch(e=>status(e.message));return;}
  if(step==='converse'){$('empty-conversation').hidden=Boolean(state.room);$('chat-workspace').hidden=!state.room;}
  for(const id of ['comparison','source-dialog','perspective-dialog','new-chat-dialog'])closeDialog(id);
  closeEvidence();
  for(const name of ['explore','converse','reflect'])$(name).hidden=name!==step;
  document.body.dataset.step=step;
  rememberConversation();
  document.querySelectorAll('button[data-step]').forEach(b=>{b.classList.toggle('active',b.dataset.step===step); if(b.dataset.step===step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
  if(step==='reflect')refreshReflection().catch(e=>status(e.message));
}
async function pollJob(value){
  const end=Date.now()+300000;
  while(Date.now()<end){const job=await api('/jobs/'+value.job_id); if(!['queued','running'].includes(job.state)){if(job.state!=='succeeded')throw new Error(errorText(job.error?.code)); return job;} await wait(600);}
  throw new Error('작업이 아직 진행 중입니다. 대화 상태에서 확인해 주세요.');
}
function setSession(session){
  state.session=session;
  $('initial-peek-text').textContent=session.initial_opinion.text.trim()||'You started without an initial view.';
  renderRooms();
  renderSaved();
}
async function refreshSession(){setSession(await api(base()));}
function renderAnalysis(){
  const a=state.analysis, video=a.video||{}, title=video.title||'This discussion', vid=video.video_id||video.id;
  $('video-title').textContent=title; $('sidebar-video-title').textContent=title;
  const n=a.analyzed_comments, unit=a.count_scope==='registered_sources'?'registered source comments':'processed comments';
  const other = a.composition?.find(entry => entry.kind === 'other');
  let coverage = Number.isInteger(n) ? n+' '+unit : 'the registered comments';
  if (n > 0 && other && a.count_scope === 'processed_comments') {
    const linked = n - other.count;
    coverage = linked+' of '+n+' '+unit+' linked to these perspectives ('+(100*linked/n).toFixed(1)+'%)';
  }
  $('analysis-summary').textContent = a.perspectives.length+' perspectives · '+coverage
    +(a.canonical_population && a.canonical_population !== n ? ' · Original population: '+a.canonical_population+' comments.' : '.');
  $('sidebar-video-meta').textContent=Number.isInteger(n)?n+' '+unit:'';
  $('video-description').textContent=video.description||'';
  $('sidebar-thumbnail').replaceChildren();
  $('video-frame').replaceChildren(node('p','No source video is linked to this analysis.','video-placeholder'));
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
    play.setAttribute('aria-label','Play source video: '+title);
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
    play.onclick=()=>{const frame=node('iframe');frame.src='https://www.youtube-nocookie.com/embed/'+vid+'?autoplay=1';frame.title=title;frame.referrerPolicy='strict-origin-when-cross-origin';frame.allow='autoplay; encrypted-media; picture-in-picture';frame.allowFullscreen=true;$('video-frame').replaceChildren(frame);};
    $('video-frame').replaceChildren(play);
  }
  renderComposition();
}
function renderComposition(){
  const entries=state.analysis.composition||[],engagement=state.analysis.engagement;
  renderBarChart('composition',entries,'count','comment','Comment composition is not available.');
  renderBarChart('likes',engagement?.available?entries:[],'likes','like',
    engagement?.available?'No likes were recorded on the analyzed comments.':'Like counts are unavailable for the full set of analyzed comments.');
}
// Both charts share one look and behaviour: the bar fills with what is linked to perspectives, the
// unlinked remainder is listed in the legend, and hovering a segment or legend entry highlights its card.
function renderBarChart(prefix,entries,field,unit,emptyText){
  const chart=$(prefix+'-chart'),legend=$(prefix+'-legend'),fmt=n=>Number(n).toLocaleString('en-US');
  chart.replaceChildren();legend.replaceChildren();
  const total=entries.reduce((sum,e)=>sum+(e[field]||0),0);
  if(!total){chart.append(node('p',emptyText,'muted'));return;}
  const linked=entries.filter(e=>e[field]&&e.kind!=='other'),linkedTotal=linked.reduce((sum,e)=>sum+e[field],0);
  const hover=(el,pid)=>{el.dataset.perspective=pid;el.onmouseenter=()=>linkComposition(pid,true);el.onmouseleave=()=>linkComposition(pid,false);};
  if(linkedTotal){
    const bar=node('div',undefined,'composition-bar');bar.setAttribute('role','img');bar.setAttribute('aria-label',unit[0].toUpperCase()+unit.slice(1)+'s linked to each perspective');
    for(const e of linked){
      const seg=node('span',e.perspective_id?label(e.perspective_id):'Multiple',e.perspective_id?'chart-'+Math.max(0,indexOf(e.perspective_id))%5:'chart-'+e.kind);
      seg.style.flexGrow=String(e[field]);seg.title=fmt(e[field])+' '+unit+(e[field]===1?'':'s');
      if(e.perspective_id)hover(seg,e.perspective_id);
      bar.append(seg);
    }
    chart.append(bar);
  }
  for(const e of entries){
    const value=e[field];if(!value)continue;
    const cls=e.perspective_id?'accent-'+Math.max(0,indexOf(e.perspective_id))%5:e.kind;
    const name=e.perspective_id?label(e.perspective_id):e.kind==='multiple'?'Multiple perspectives':'Not linked to a perspective';
    const line=node('span',undefined,cls);line.append(node('i',undefined,'legend-dot'),node('span',name+' · '+fmt(value)+' ('+(value/total*100).toFixed(1)+'%)'));
    if(e.perspective_id)hover(line,e.perspective_id);
    legend.append(line);
  }
}
// Hovering a card or a bar segment highlights its counterpart in both charts.
function linkComposition(pid,on){
  for(const el of document.querySelectorAll('#composition-chart [data-perspective], #composition-legend [data-perspective], #likes-chart [data-perspective], #likes-legend [data-perspective], #perspectives .card'))if(el.dataset.perspective===pid)el.classList.toggle('linked',on);
}
function supportsDebate(count){return count>=2&&state.session.capabilities?.structured_debate;}
function updateSelection(){
  if(!$('open-room'))return;
  const count=state.selected.size;
  const mode=count===1?'Start a 1:1 conversation.':supportsDebate(count)?'Start an automatic debate.':'Start a group conversation.';
  $('selection-hint').textContent=count?count+' selected · '+mode:'Choose one perspective for a 1:1 conversation, or up to three for a group.';
  $('open-room').disabled=!count;
}
function perspectiveCard(p){
  const card=node('article',undefined,'card compact accent-'+indexOf(p.id)%5);card.dataset.perspective=p.id;
  const top=node('header'),title=node('div',undefined,'card-title');
  title.append(node('strong',label(p.id)),perspectiveStats(p));
  top.append(avatar(p.id),title);
  const relation=node('p','','relation-summary'),stance=node('p',p.text,'card-stance');stance.title=p.text;
  card.append(top,stance,relation);
  // The whole card opens the comparison popup.
  card.classList.add('clickable');card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label','Compare '+label(p.id)+' with your view');
  card.onclick=()=>compareWith(p.id).catch(e=>status(e.message));
  card.onmouseenter=()=>linkComposition(p.id,true);card.onmouseleave=()=>linkComposition(p.id,false);
  card.onkeydown=event=>{if(event.target===card&&(event.key==='Enter'||event.key===' ')){event.preventDefault();card.click();}};
  return card;
}
// One sentence from what the popup shows: the consideration question for "consider", otherwise the lead explanation.
function firstSentence(text){const t=(text||'').trim(),m=t.match(/^.*?[.!?。](?=\s|$)/s);return m?m[0]:t;}
function keySentence(item,level){if(!item)return '';return firstSentence(level==='consider'&&item.consideration_question?item.consideration_question:item.explanation);}
// Card totals count every comment that supports this perspective, including comments shared with
// other perspectives (the composition charts count each comment once instead).
function perspectiveStats(p){
  const totals=p.support_totals,entry=(state.analysis.composition||[]).find(e=>e.perspective_id===p.id),stats=node('small',undefined,'card-stats');
  const fmt=n=>Number(n).toLocaleString('en-US'),count=totals?.comments??entry?.count??0;
  const likes=totals?totals.likes:(state.analysis.engagement?.available?entry?.likes:null);
  stats.append(node('span',fmt(count)+' comment'+(count===1?'':'s')));
  if(typeof likes==='number')stats.append(node('span','👍 '+fmt(likes)+' like'+(likes===1?'':'s'),'card-likes'));
  stats.title='Comments that support this perspective, including comments shared with other perspectives'+(typeof likes==='number'?', and the likes they received when the video was collected.':'.')+' The charts below count each comment only once.';
  return stats;
}
function cardGrid(cards){const grid=node('div',undefined,'cards');grid.append(...cards);return grid;}
// Groups run from closest to most different, so reading top to bottom conveys distance without a score.
const closenessOrder=['close','mixed','consider','differ','none','error'];
const groupTitles={close:'Close to your view',mixed:'Partly close, partly different',consider:'Adds something to consider',
  differ:'Different from your view',none:'No clear link to your view',error:'Could not compare right now'};
async function renderPerspectives(){
  const box=$('perspectives'),render=state.cardRender=(state.cardRender||0)+1,list=state.analysis.perspectives;
  state.closeness.clear();state.closenessSummary.clear();
  box.replaceChildren();
  if(!list.length){box.append(node('p','근거를 확인한 관점이 아직 없습니다. 나의 의견은 Reflect에서 정리할 수 있습니다.','muted'));return;}
  const cards=new Map(list.map(p=>[p.id,perspectiveCard(p)]));
  if(!hasInitialView()){
    for(const card of cards.values())setCloseness(card,'empty');
    box.append(node('p','Write your initial view to see which perspectives are close to yours.','group-hint'),cardGrid([...cards.values()]));return;
  }
  for(const card of cards.values()){setCloseness(card,'pending');card.querySelector('.relation-summary').textContent='Comparing with your view…';}
  // While comparing, keep every card on one row; they are regrouped once all comparisons settle.
  const row=cardGrid([...cards.values()]);row.classList.add('single-row');row.style.setProperty('--count',String(list.length));
  box.append(node('p','Comparing your view with '+list.length+' perspective'+(list.length===1?'':'s')+'…','group-hint'),row);
  const revision=state.session.initial_opinion.revision;
  const results=await Promise.allSettled(list.map(p=>comparison(p.id)));
  if(render!==state.cardRender||revision!==state.session.initial_opinion.revision)return;
  const groups=new Map(closenessOrder.map(level=>[level,[]]));
  results.forEach((result,i)=>{
    const p=list[i],card=cards.get(p.id),summary=card.querySelector('.relation-summary');
    if(result.status!=='fulfilled'||result.value.stale||!result.value.result.available){setCloseness(card,'error');summary.textContent='';groups.get('error').push(card);return;}
    const items=result.value.result.items||[],level=closeness(items);
    // Lead with the explanation that matches the group.
    const lead=items.find(i=>level==='differ'||level==='mixed'?i.relation==='difference':level==='close'?i.relation==='agreement':true);
    setCloseness(card,level);summary.textContent=keySentence(lead,level);summary.title=summary.textContent;state.closenessSummary.set(p.id,summary.textContent);groups.get(level).push(card);state.closeness.set(p.id,level);
  });
  // The four closeness groups sit side by side as columns; groups without a comparison result go on a row below.
  box.replaceChildren();
  const rows=[['close','mixed','differ','consider'],['none','error']];
  for(const levels of rows){
    const row=node('div',undefined,'closeness-row'+(levels[0]==='close'?'':' closeness-row-wide'));
    for(const level of levels){
      const members=groups.get(level);if(!members.length)continue;
      const section=node('section',undefined,'closeness-group closeness-'+level),stack=node('div',undefined,'group-cards');
      stack.append(...members);section.append(node('h2',groupTitles[level]+' · '+members.length,'closeness-group-title'),stack);row.append(section);
    }
    if(row.childElementCount)box.append(row);
  }
}
function hasInitialView(){return !!state.session.initial_opinion.text.trim();}
// One comparison job per (initial revision, perspective). Revisiting reuses the finished job.
function comparison(pid){
  const session=state.session,revision=session.initial_opinion.revision,key=session.session_id+'/'+revision+'/'+pid;
  if(!state.comparisons.has(key)){
    // A comparison already recorded for this session is reopened instead of generated again.
    const previous=session.comparisons?.[pid];
    const pending=(previous?Promise.resolve(previous):api(base()+'/comparisons','POST',{perspective_id:pid,initial_revision:revision,request_id:requestId()})).then(pollJob);
    pending.catch(()=>state.comparisons.delete(key));state.comparisons.set(key,pending);
  }
  return state.comparisons.get(key);
}
// Closeness is a fixed rule over the comparison's relation kinds, not a score:
// shared points only -> close, differences only -> differ, both -> mixed.
const closenessLabels={close:'Close to your view',mixed:'Partly close, partly different',differ:'Different from your view',
  consider:'Adds something to consider',none:'No clear link to your view',pending:'Comparing with your view…',
  empty:'Add your initial view to compare',error:'Comparison is not available right now'};
function relationKind(relation){return relation==='agreement'||relation==='difference'?relation:'consider';}
function closeness(items){
  const kinds=new Set(items.map(i=>relationKind(i.relation)));
  if(kinds.has('agreement')&&kinds.has('difference'))return 'mixed';
  if(kinds.has('agreement'))return 'close';
  if(kinds.has('difference'))return 'differ';
  return kinds.size?'consider':'none';
}
function closenessTag(level){return node('span',closenessLabels[level],'closeness-text closeness-'+level);}
function setCloseness(card,level){
  for(const name of [...card.classList])if(name.startsWith('closeness-'))card.classList.remove(name);
  card.classList.add('closeness-'+level);
}
async function sourceText(id){
  const key=base()+'/sources/'+encodeURIComponent(id);
  if(!state.sourceTexts.has(key))state.sourceTexts.set(key,api(key).catch(e=>{state.sourceTexts.delete(key);throw e;}));
  return state.sourceTexts.get(key);
}
async function source(id, resource=base()){try{const value=await api(resource+'/sources/'+encodeURIComponent(id));$('source').textContent=value.text+(value.PARENT_CONTEXT_ONLY?'\n\n부모 댓글 · 문맥 참고\n'+value.PARENT_CONTEXT_ONLY.text:'');openDialog('source-dialog');}catch(e){status(e.message);}}
function sourceButtons(container,point){commentSourceButtons(container,(point.citations?.comment_evidence||[]).map(e=>e.source_id));for(const evidence of point.citations?.external_evidence||[]){let url;try{url=new URL(evidence.url);}catch(_){continue;}if(url.protocol!=='https:'||url.username||url.password)continue;const a=node('a',evidence.title||'외부 자료','source-button');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.title=evidence.text;container.append(a);}}
function commentSourceButtons(container,sourceIds,caption='Evidence'){
  for(const [index,sourceId] of sourceIds.entries()){
    const button=node('button',caption+' '+(index+1),'source-button');
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
// Every source comment of the perspective, in first-seen order, with the comparison items that cite it.
function commentEntries(p,items){
  const entries=new Map(),add=id=>{if(!entries.has(id))entries.set(id,{id,items:[],grounds:[],quote:''});return entries.get(id);};
  for(const id of p.source_ids||[])add(id);
  for(const g of p.grounds||[])for(const id of g.source_ids||[])add(id).grounds.push(g);
  for(const item of items)for(const claim of [...(item.perspective_claims||[]),...(item.required_premises||[])])
    for(const evidence of claim.citations?.comment_evidence||[]){const entry=add(evidence.source_id);if(!entry.items.includes(item))entry.items.push(item);if(!entry.quote)entry.quote=evidence.span?.text||'';}
  return [...entries.values()];
}
const commentGroups=[['close','Comments close to your view'],['mixed','Comments partly close, partly different'],['differ','Comments different from your view'],['consider','Comments that add something to consider'],['none','Other comments in this perspective']];
const relationIcons={agreement:'✓',difference:'✕',consider:'?'};
function commentCard(entry,compared){
  const article=node('article',undefined,'comment-entry'),quote=node('blockquote',entry.quote||'…','comment-text');
  article.append(quote);
  sourceText(entry.id).then(value=>{quote.textContent=value.text;
    if(value.PARENT_CONTEXT_ONLY){const parent=node('details',undefined,'comment-parent');parent.append(node('summary','Replying to another comment'),node('p',value.PARENT_CONTEXT_ONLY.text));article.insertBefore(parent,quote);}
  }).catch(()=>{if(!entry.quote)quote.textContent='This comment could not be loaded.';});
  for(const g of entry.grounds)article.append(node('p',(g.role==='essential_condition'?'Condition: ':g.role==='concession'?'Qualification: ':'Reason: ')+g.text,'comment-ground'));
  if(compared)for(const item of entry.items){
    const note=node('p',undefined,'comment-note note-'+relationKind(item.relation));note.append(node('span',relationIcons[relationKind(item.relation)],'note-icon'),node('span',item.explanation));article.append(note);
    if(item.consideration_question)article.append(node('p','💭 '+item.consideration_question,'comment-question'));
  }
  return article;
}
function renderComments(p,items,compared){
  const box=$('comparison-items');box.replaceChildren();
  const entries=commentEntries(p,items);
  if(!entries.length){box.append(node('p','No source comments are linked to this perspective.','muted'));return;}
  if(!compared){box.append(node('h3','What commenters said','comment-group-title'));for(const e of entries)box.append(commentCard(e,false));return;}
  for(const [level,title] of commentGroups){
    const group=entries.filter(e=>closeness(e.items)===level);if(!group.length)continue;
    const section=node('section',undefined,'comment-group closeness-'+level);section.append(node('h3',title+' · '+group.length,'comment-group-title'));
    for(const e of group)section.append(commentCard(e,true));box.append(section);
  }
}
async function compareWith(pid){
  // Open immediately: the perspective's source comments are readable even without an initial view.
  const p=perspective(pid),revision=state.session.initial_opinion.revision,dialog=$('comparison');
  dialog.className='comparison-modal accent-'+indexOf(pid)%5;$('comparison-avatar').replaceChildren(avatar(pid));$('comparison-title').textContent=label(pid);$('comparison-stance').textContent=p.text;
  $('comparison-tag').replaceChildren();state.openComparison=pid;
  $('comparison-your-view').hidden=!hasInitialView();$('comparison-initial').textContent=state.session.initial_opinion.text;
  renderComments(p,[],false);openDialog('comparison');
  if(!hasInitialView()){$('comparison-tag').append(closenessTag('empty'));return;}
  $('comparison-tag').append(closenessTag('pending'));
  let job;
  try{job=await comparison(pid);}catch(e){if(state.openComparison===pid)$('comparison-tag').replaceChildren(closenessTag('error'));throw e;}
  if(revision!==state.session.initial_opinion.revision||state.openComparison!==pid||!dialog.open)return;
  if(job.stale||!job.result.available){$('comparison-tag').replaceChildren(closenessTag('empty'));return;}
  const items=job.result.items||[];
  dialog.classList.add('closeness-'+closeness(items));$('comparison-tag').replaceChildren(closenessTag(closeness(items)));
  highlighted($('comparison-initial'),state.session.initial_opinion.text,items.flatMap(i=>i.user_spans.map(s=>({...s,category:i.relation}))));
  renderComments(p,items,true);
}
const roomStates={
  idle:'시작 전',running:'진행 중',pausing:'정지 중',paused:'일시 정지',awaiting_user:'질문 대기',
  opening:'입장 발언',replying:'상대 입장에 응답 중',synthesizing:'합의 검토 중',compiling:'결론 정리 중',
  completed:'완료',completed_no_consensus:'합의 없음',completed_no_proposal:'공통 주장 제안 없음',
  verification_hold:'검증 보류',incomplete:'응답 불완전',failed:'실행 실패',cancelled:'중단',
  closed:'종료',closing:'종료 중',error:'일부 응답 실패',exhausted:'한도 도달',needs_reconciliation:'확인 필요'
};
const activeRoomStates=new Set(['running','opening','replying','synthesizing','compiling','pausing','closing']);
const lastRoomKey='commentscope-mvp-last-conversation';
const defaultOpeningQuestion=$('opening-question').defaultValue;

function roomKindLabel(room){
  if(room.kind==='synthesis_chat')return 'Consensus Agent chat';
  if(room.kind==='structured_debate'||room.kind==='debate_draft')return 'Automatic debate';
  return room.mode==='group'?'Group chat':'1:1 chat';
}
// A conversation is named after its first question; before that, after its kind.
function roomName(room,index){
  const summary=state.session?.rooms?.find(r=>r.room_id===room.room_id);
  const question=(room.question||summary?.question||room.plan?.question||room.messages?.find(m=>m.author_kind==='user')?.body||'').trim();
  // The consensus agent's room is created by the debate itself, so it keeps the agent's name.
  if(room.kind==='synthesis_chat')return '합의 Agent';
  if(question)return [...question].length>48?[...question].slice(0,47).join('')+'…':question;
  const kind=roomKindLabel(room);
  return 'New '+(kind.startsWith('1:1')?kind:kind[0].toLowerCase()+kind.slice(1))+(index>=0?' '+(index+1):'');
}
function participantNames(room){return (room.participant_ids||[]).map(label).join(', ');}
function roomPath(room){
  return room.debate_id?'/debates/'+encodeURIComponent(room.debate_id):'/rooms/'+encodeURIComponent(room.room_id);
}
function setRoom(room){
  if(room?.room_id!==state.room?.room_id||room?.kind==='debate_draft'){
    if(typeof closeEvidence==='function'&&$('evidence-panel'))closeEvidence();
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
  const select=$('rooms'),list=$('room-list');select.replaceChildren(node('option','Choose a conversation'));select.firstChild.value='';list.replaceChildren();
  if(!state.session)return;
  const query=$('room-search').value.toLowerCase();
  state.session.rooms.forEach((room,i)=>{if(room.room_id===state.room?.room_id)room=state.room;const title=roomName(room,i),option=node('option',title+' · '+(roomStates[room.state]||room.state));option.value=room.room_id;select.append(option);
    if(state.roomFilter!=='all'&&room.mode!==state.roomFilter||!title.toLowerCase().includes(query))return;
    const button=node('button',undefined,'room-entry');button.type='button';button.classList.toggle('active',state.room?.room_id===room.room_id);const faces=node('span',undefined,'room-faces'+((room.participant_ids||[]).length>1?' group':''));for(const id of (room.participant_ids||[]).slice(0,3))faces.append(avatar(id,true));
    const text=node('span',undefined,'room-text');text.append(node('strong',title),node('small',[participantNames(room),roomStates[room.state]||room.state].filter(Boolean).join(' · ')));
    button.append(faces,text);button.title=title;button.onclick=()=>chooseRoom(room.room_id).catch(e=>status(e.message));list.append(button);
  });
  if(!list.childNodes.length)list.append(node('p','No conversations here yet.','muted'));if(state.room?.room_id)select.value=state.room.room_id;
}
function messageTime(m){const t=m.created_at?new Date(m.created_at):null;return t&&!isNaN(t)?t.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'}):'';}
// Figma 314:2807: agent messages show avatar, a speaker row (name · time) above a grey bubble and an
// Evidence chip below it; user messages are lavender bubbles on the right with the time beside them.
function renderMessages(){
  $('messages').replaceChildren();
  const first=state.room.messages.find(m=>m.created_at);
  if(first){const day=new Date(first.created_at),today=new Date().toDateString()===day.toDateString();
    const row=node('div',undefined,'date-row');row.append(node('span',(today?'Today':day.toLocaleDateString('en-US',{month:'short',day:'numeric'}))+' · '+messageTime(first)+' · continuing from your initial view'));$('messages').append(row);}
  for(const m of state.room.messages){const box=node('article',undefined,'message '+m.author_kind);box.id='message-'+m.message_id;
    const bubble=node('div',undefined,'bubble'),content=node('div',undefined,'message-content');
    const phase=({opening:'입장 발언',reply:'상대 입장 응답'})[m.phase];
    if(m.author_kind==='agent'){
      const icon=node('div',undefined,'message-avatar');icon.append(avatar(m.agent_id));box.append(icon);
      // Figma: the speaker row is just name · time; turn type and reply context live in Evidence.
      const speaker=node('div',undefined,'speaker-row');speaker.append(node('strong',label(m.agent_id),'speaker-name'),node('span',messageTime(m),'message-time'));content.append(speaker);
    }else box.append(node('span',messageTime(m),'message-time'));
    if(m.body)bubble.append(node('p',m.body));
    if(m.author_kind==='agent'&&!m.points?.length){
      const expired=m.evidence_scope==='expired';
      bubble.append(node('p',expired?'근거 자료의 기한이 지났습니다.':m.limitation==='verification_hold'?'이 질문에 대한 답변을 검증하지 못했습니다.':'이 질문에 답할 근거를 자료에서 찾지 못했습니다.'));
    }
    for(const point of m.points||[]){
      const text=node('p',point.text);
      if(point.point_id)text.id='point-'+point.point_id;
      const origin=pointOrigin(point.origin);
      if(origin)text.append(node('span',origin,'origin-tag'));
      bubble.append(text);
    }
    if(m.status==='abstain'&&m.points?.length)bubble.append(node('small','요청한 답을 확인할 수 없어 자료의 한계를 설명합니다.'));
    if(m.points?.length&&m.limitation==='verification_hold')bubble.append(node('small','추가 설명을 확인하지 못해, 확인할 수 있는 내용만 표시했습니다.'));
    content.append(bubble);
    if(m.author_kind==='agent'){const count=evidenceCount(m);if(count){const button=node('button',undefined,'evidence-button');button.type='button';button.append(node('span','📎 Evidence · '+count),node('span','›','evidence-chevron'));button.dataset.message=m.message_id;button.onclick=()=>openEvidence(m);content.append(button);}}
    box.append(content);$('messages').append(box);
  }
}
// Comment-backed points need no tag; AI reasoning and external claims stay visibly separate (DEC-028).
function evidenceItems(m){
  const comments=new Map(),external=[],anchors=new Map(),targets=[];
  const addComment=(id,quote,supports)=>{if(!comments.has(id))comments.set(id,{id,quote:quote||'',supports:[]});const c=comments.get(id);if(!c.quote&&quote)c.quote=quote;if(supports&&!c.supports.includes(supports))c.supports.push(supports);};
  for(const point of [...(m.points||[]),...(m.required_premises||[])]){
    for(const e of point.citations?.comment_evidence||[])addComment(e.source_id,e.span?.text,point.text);
    for(const e of point.citations?.external_evidence||[]){let url;try{url=new URL(e.url);}catch(_){continue;}if(url.protocol==='https:'&&!url.username&&!url.password)external.push({url:url.href,title:e.title||url.hostname,text:e.text,supports:point.text});}
    if(m.evidence_scope==='seeded_provenance'&&point.origin==='ai_reasoning'){const view=perspective(m.agent_id);const claims=new Map((view?.grounds||[]).map(g=>[g.claim_id,g.text]));if(view)claims.set(view.core_claim_id,view.text);for(const id of point.citations?.anchor_claim_ids||[])if(claims.has(id))anchors.set(id,claims.get(id));}
    for(const target of point.target_edges||[])targets.push(target);
  }
  if(!m.points?.length&&m.evidence_scope==='seeded_provenance'){const view=perspective(m.agent_id);for(const id of view?.source_ids||[])addComment(id,'',view.text);}
  return {comments:[...comments.values()],external,anchors:[...anchors.values()],targets};
}
function evidenceCount(m){const e=evidenceItems(m);return e.comments.length+e.external.length;}
function replyContext(m){const reply=m.reply_to_message_id&&state.room.messages.find(x=>x.message_id===m.reply_to_message_id);return reply?.author_kind==='agent'?reply:null;}
function evidenceCard({category,title,origin,excerpt,jump,link}){
  const card=node('article',undefined,'evidence-card');
  if(title)card.append(node('h3',title,'evidence-card-title'));
  if(origin)card.append(node('p',origin,'evidence-origin'));
  if(link){const a=node('a',link.text+' ↗','evidence-link');a.href=link.url;a.target='_blank';a.rel='noopener noreferrer';card.append(a);}
  const quote=node('blockquote',excerpt||'','evidence-text');if(excerpt!==undefined)card.append(quote);
  const foot=node('div',undefined,'evidence-foot');foot.append(node('span',category,'evidence-category'));
  if(jump){const go=node('button','Jump to reply ›','evidence-jump');go.type='button';go.onclick=jump;foot.append(go);}
  card.append(foot);return {card,quote};
}
function jumpTo(messageId){const el=$('message-'+messageId);if(!el)return;el.scrollIntoView({block:'center',behavior:'smooth'});el.classList.add('focused');setTimeout(()=>el.classList.remove('focused'),1600);}
function openEvidence(m){
  const e=evidenceItems(m),list=$('evidence-list');list.replaceChildren();
  $('evidence-title').textContent='Evidence of Reply';
  $('evidence-context').textContent=label(m.agent_id)+(messageTime(m)?' · '+messageTime(m):'')+' — '+e.comments.length+' comment'+(e.comments.length===1?'':'s')+(e.external.length?', '+e.external.length+' external source'+(e.external.length===1?'':'s'):'')+'.';
  const jump=()=>jumpTo(m.message_id);
  for(const c of e.comments){
    const {card,quote}=evidenceCard({category:'COMMENT EVIDENCE',title:c.supports[0]||label(m.agent_id),origin:'Comment from the video'+(c.supports.length>1?' · supports '+c.supports.length+' points':''),excerpt:c.quote||'…',jump});
    sourceText(c.id).then(v=>{quote.textContent=v.text;if(v.PARENT_CONTEXT_ONLY){const parent=node('details',undefined,'comment-parent');parent.append(node('summary','Replying to another comment'),node('p',v.PARENT_CONTEXT_ONLY.text));card.insertBefore(parent,quote);}}).catch(()=>{if(!c.quote)quote.textContent='This evidence could not be loaded.';});
    list.append(card);
  }
  for(const x of e.external)list.append(evidenceCard({category:'EXTERNAL SOURCE',title:x.supports,link:{url:x.url,text:x.title},excerpt:x.text||undefined,jump}).card);
  for(const t of e.anchors)list.append(evidenceCard({category:'AGENT EXPLANATION',title:'A claim the agent referred to',excerpt:t,jump}).card);
  for(const premise of m.required_premises||[])list.append(evidenceCard({category:'CONDITION TO CHECK',title:'Premise or condition to check together',excerpt:premise.text,jump}).card);
  const reply=replyContext(m);
  if(reply||e.targets.length){
    const {card}=evidenceCard({category:'REPLY CONTEXT',title:reply?'Replying to '+label(reply.agent_id):'Responds to'});
    const row=node('div',undefined,'evidence-targets');
    if(reply){const go=node('button',label(reply.agent_id)+(messageTime(reply)?' · '+messageTime(reply):''),'source-button');go.type='button';go.onclick=()=>jumpTo(reply.message_id);row.append(go);}
    for(const t of e.targets)appendPointLinks(row,[t.point_id],state.room,label(t.agent_id));
    card.insertBefore(row,card.lastChild);list.append(card);
  }
  if(!list.childElementCount)list.append(node('p','No evidence is attached to this message.','evidence-intro'));
  document.querySelectorAll('.evidence-button.active').forEach(b=>b.classList.remove('active'));
  document.querySelector('.evidence-button[data-message="'+CSS.escape(m.message_id)+'"]')?.classList.add('active');
  $('evidence-panel').hidden=false;$('converse').classList.add('with-evidence');$('evidence-panel').scrollTop=0;
}
function closeEvidence(){$('evidence-panel').hidden=true;$('converse').classList.remove('with-evidence');document.querySelectorAll('.evidence-button.active').forEach(b=>b.classList.remove('active'));}
function pointOrigin(origin){
  return ({ai_reasoning:'AI reasoning · not the commenters’ words',external_evidence:'Based on external sources'})[origin];
}
function appendPointLinks(parent,pointIds,room,title){
  for(const pointId of new Set(pointIds)){
    const message=room.messages.find(m=>m.points?.some(point=>point.point_id===pointId));
    if(!message)continue;
    const link=node('button',title||label(message.agent_id)+'의 근거 발언','source-button');
    link.type='button';
    link.onclick=()=>{
      const point=$('point-'+pointId);
      point?.scrollIntoView({block:'center'});
      point?.parentElement?.setAttribute('tabindex','-1');
      point?.parentElement?.focus({preventScroll:true});
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
    completed:'모든 참가 관점이 수락한 공통 주장입니다.',
    completed_no_consensus:'전원이 수락한 공동 주장이 없습니다. 아래 이견과 발언을 확인할 수 있습니다.',
    completed_no_proposal:'이번 질문에서 공동 주장 후보를 제시하지 못했습니다. 발언을 보며 각 관점을 비교해 보세요.',
    verification_hold:'공통 주장의 근거나 수락을 확인하지 못했습니다. 검증된 발언은 위에 남아 있습니다.',
    incomplete:'일부 응답이 질문이나 상대 발언을 충분히 다루지 못했습니다.',
    failed:'토론을 완료하지 못했습니다. 게시된 발언은 보존됩니다.',
    exhausted:'AI 실행 한도에 도달했습니다. 게시된 발언은 보존됩니다.',
    needs_reconciliation:'실행 상태를 확인해야 합니다. 게시된 발언은 보존됩니다.'
  };
  panel.append(node('h2','토론 결론 · '+(roomStates[result.status]||'종료')));
  panel.append(node('p',result.evidence_scope==='expired'?'근거 자료의 사용 기한이 지났습니다.':
    summaries[result.status]||'이 토론의 게시된 발언을 확인할 수 있습니다.'));
  for(const claim of result.shared_claims||[]){
    const card=node('article',undefined,'debate-claim');
    card.append(node('h3',claim.text));
    const origin=pointOrigin(claim.origin);
    if(origin)card.append(node('p',origin,'muted'));
    const names=(claim.accepting_agent_ids||[]).map(label);
    if(names.length)card.append(node('p','수락한 관점 · '+names.join(', '),'muted'));
    const conditions=new Set((claim.condition_ids||[]).map(id=>result.conditions?.[id])
      .filter(Boolean).map(condition=>condition.scope?.conditions||condition.text));
    for(const condition of conditions)card.append(node('p','조건 · '+condition));
    const references=node('div',undefined,'debate-references');
    appendPointLinks(references,claim.premise_point_ids||[],room);
    sourceButtons(references,claim);
    card.append(references);
    panel.append(card);
  }
  if(result.disagreements?.length){
    panel.append(node('h3','이견과 조건부 응답'));
    const list=node('ul');
    const relations={reject:'수락하지 않음',needs_condition:'조건 보완 요청',disagree:'반대',conditional:'조건부 응답'};
    for(const item of result.disagreements){
      const row=node('li',label(item.agent_id)+' · '+(relations[item.relation]||'이견'));
      const references=node('div',undefined,'debate-references');
      appendPointLinks(references,item.point_ids||[],room);
      row.append(references);
      list.append(row);
    }
    panel.append(list);
  }
  if(result.unanswered?.length&&result.evidence_scope!=='expired'){
    panel.append(node('h3','아직 답하지 못한 내용'));
    const list=node('ul');
    for(const row of result.unanswered){
      list.append(node('li',label(row.agent_id)+' · '+(row.targets.length?
        row.targets.map(target=>target.text).join(' / '):'질문에 대한 응답 부족')));
    }
    panel.append(list);
  }
  if(room.synthesis_agent){
    const card=node('section',undefined,'synthesis-card');
    card.append(node('h3','합의 Agent'),node('p','참가 관점이 수락한 주장과 조건을 바탕으로 질문에 답합니다.'));
    const references=node('div',undefined,'debate-references');
    const resource='/synthesis-agents/'+encodeURIComponent(room.synthesis_agent.agent_id);
    for(const [i,id] of (result.root_source_ids||[]).entries()){
      const read=node('button','Evidence '+(i+1),'source-button');
      read.type='button';
      read.onclick=()=>source(id,resource);
      references.append(read);
    }
    card.append(references);
    const ask=node('button','합의 Agent에 질문하기','primary');
    ask.type='button';
    ask.id='ask-synthesis-agent';
    ask.onclick=()=>openSynthesisChat(room,ask);
    card.append(ask);
    panel.append(card);
  } else if (result.evidence_scope !== 'expired' && ['incomplete','verification_hold','completed_no_consensus','completed_no_proposal'].includes(result.status)) {
    const followup = node('button', 'Ask these perspectives in a new chat', 'secondary');
    followup.type = 'button';
    followup.id = 'discuss-with-participants';
    followup.onclick = () => showChatPicker(room.participant_ids);
    panel.append(followup);
  }
}
function renderRoom(){
  const room=state.room;
  $('empty-conversation').hidden=true;$('chat-workspace').hidden=false;
  renderMessages();
  renderRooms();
  renderConclusion(room);
  const ids=room.participant_ids||[];
  $('room-avatars').replaceChildren(...ids.map(id=>avatar(id)));
  const index=state.session.rooms.findIndex(r=>r.room_id===room.room_id);
  $('room-title').textContent=roomName(room,index);$('room-title').title=(room.question||room.plan?.question||'');
  // Who is in this conversation.
  const members=node('span',undefined,'room-members');members.append(node('span',roomKindLabel(room)+' with','room-members-label'));
  for(const id of ids){const chip=node('span',undefined,'member-chip accent-'+Math.max(0,indexOf(id))%5);chip.append(avatar(id,true),node('span',label(id)));members.append(chip);}
  const automatic=room.kind==='structured_debate'||room.kind==='debate_draft';
  $('messages').classList.toggle('structured-transcript',automatic);
  $('show-debate-result').hidden=!room.conclusion;
  $('room-summary').replaceChildren(members);
  const names={
    idle:'질문으로 시작할 수 있습니다.',running:'관점이 응답하고 있습니다.',
    opening:'각 관점이 입장을 설명하고 있습니다.',replying:'다른 관점의 발언에 답하고 있습니다.',
    synthesizing:'공통 주장과 이견을 검토하고 있습니다.',compiling:'토론 결론을 정리하고 있습니다.',
    pausing:'현재 응답 뒤에 멈춥니다.',paused:automatic?'잠시 멈췄습니다. 토론을 이어갈 수 있습니다.':'잠시 멈췄습니다. 질문하거나 이어갈 수 있습니다.',
    awaiting_user:'대화가 끝났습니다. 나의 질문을 이어갈 수 있습니다.',
    closed:'종료한 대화입니다.',closing:'현재 처리를 마친 뒤 종료합니다.',
    error:'일부 응답을 완료하지 못했습니다. 이전 발언은 보존됩니다.',
    exhausted:'대화 한도에 도달했습니다.',needs_reconciliation:'처리 상태 확인이 필요합니다.'
  };
  $('room-state').textContent=(names[room.state]||roomStates[room.state]||room.state)+' · '+room.turn_count+'/'+room.turn_limit;
  if(room.error_code)$('room-state').textContent+=' · '+errorText(room.error_code);
  $('recover-room').hidden=automatic||room.state!=='error';
  const target=$('question-target'),lastTarget=target.value;
  $('address-agent').hidden=automatic||room.mode!=='group';
  if(!$('address-agent').hidden){
    const all=node('option','Everyone');all.value='';target.replaceChildren(all);
    for(const id of ids){const option=node('option',label(id));option.value=id;target.append(option);}
    if(ids.includes(lastTarget))target.value=lastTarget;
    // Pill buttons choose the recipient; the hidden select keeps the value the form sends.
    const chips=$('recipient-chips');chips.replaceChildren();
    for(const id of ['',...ids]){
      const chip=node('button',undefined,'recipient-chip'+(id?' accent-'+Math.max(0,indexOf(id))%5:''));chip.type='button';chip.setAttribute('role','radio');
      if(id)chip.append(avatar(id,true));chip.append(node('span',id?label(id):'Everyone'));
      const sync=()=>{for(const c of chips.children){const on=c===chip;c.classList.toggle('active',on);c.setAttribute('aria-checked',String(on));}};
      chip.onclick=()=>{target.value=id;sync();};if(target.value===id)setTimeout(sync);chips.append(chip);
    }
  }
  const openingQuestion=$('opening-question');
  openingQuestion.readOnly=Boolean(room.plan)&&room.state==='idle';
  if(openingQuestion.readOnly)openingQuestion.value=room.plan.question;
  $('opening').hidden=room.state!=='idle';
  $('opening').querySelector('button[type=submit]').disabled=state.openingPending||room.can_start===false;
  $('opening').querySelector('h2').textContent=automatic?'어떤 쟁점을 토론할까요?':'What would you like to ask?';
  $('opening-submit-label').textContent=automatic?'자동 토론 시작':'Start conversation';
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
    if(!agent.can_ask)throw new Error('지금은 합의 Agent에 새 질문을 보낼 수 없습니다.');
    const room=await retryableWrite('chat',resource+'/rooms','POST',{
      agent_revision:agent.revision,initial_revision:state.session.initial_opinion.revision});
    await refreshSession();
    if(state.room?.room_id!==debate.room_id)return;
    setRoom(room);
    $('opening-question').value='';
    await refreshRoom();
    showStep('converse');
    status('');
    $('opening-question').focus();
  }catch(error){status(error.message);}
  finally{button.disabled=false;}
}
async function refreshReflection(){
  await refreshSession();$('initial-copy').textContent=state.session.initial_opinion.text;
  if(!$('current').value)$('current').value=state.session.current_opinion.revision?state.session.current_opinion.text:state.session.initial_opinion.text;
  $('reflection-rooms').replaceChildren();
  state.session.rooms.forEach((room,i)=>{const line=node('div',undefined,'reflection-room'),button=node('button',roomName(room,i)+' · '+(roomStates[room.state]||room.state));button.type='button';button.onclick=()=>{setRoom(room);refreshReflection().catch(error=>status(error.message));};line.append(button);$('reflection-rooms').append(line);});
  $('context-messages').replaceChildren();
  if(state.room){await refreshRoom();for(const message of state.room.messages){const line=node('label',undefined,'context-item'),check=node('input');check.type='checkbox';check.checked=state.context.has(message.message_id);check.onchange=()=>{if(check.checked){if(state.context.size>=24){check.checked=false;status(errorText('context_capacity'));return;}state.context.add(message.message_id);}else state.context.delete(message.message_id);};line.append(check,node('span',(message.author_kind==='user'?'You':label(message.agent_id))+': '+(message.body||message.points?.map(p=>p.text).join(' ')||'근거 없음').slice(0,160)));$('context-messages').append(line);}}
  if(state.reflectionResult)highlightReflection(state.reflectionResult);
}
function clearInsights(){state.reflectionJob=null;state.reflectionResult=null;$('suggestions').replaceChildren();$('insight-panel').hidden=true;$('reflection-layout').classList.remove('review');$('current').hidden=false;$('current-copy').hidden=true;$('edit-current').hidden=true;}
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
function renderSuggestions(result){
  $('suggestions').replaceChildren();$('reflection-tabs').replaceChildren();$('insight-panel').hidden=false;$('reflection-layout').classList.add('review');$('current').hidden=true;$('current-copy').hidden=false;$('edit-current').hidden=false;
  const all=node('button','All','active');all.type='button';all.onclick=()=>{$('suggestions').scrollTop=0;};$('reflection-tabs').append(all);
  let number=0;
  for(const [key,title] of Object.entries(categories)){number++;const items=result.categories[key],group=node('section',undefined,'suggestion '+key);group.id='insight-'+key;
    const heading=node('h3');heading.append(node('span',number,'category-number'),node('span',title),node('small',items.length+' points'));group.append(heading);
    const tab=node('button',title+' · '+items.length,key);tab.type='button';tab.onclick=()=>group.scrollIntoView({block:'nearest'});$('reflection-tabs').append(tab);
    for(const item of items){const row=node('article',undefined,'reflection-insight');row.append(node('p',item.explanation));
      for(const kind of ['initial','current']){const ids=item[kind+'_span_ids'],spans=state.session[kind+'_opinion'].segments.filter(s=>ids.includes(s.id));if(spans.length)row.append(node('blockquote',(kind==='initial'?'BEFORE  ':'NOW  ')+spans.map(s=>s.text).join(' '),'opinion-reference'));}
      for(const mid of item.related_message_ids){const button=node('button','관련 대화','source-button');button.type='button';button.onclick=()=>jumpTo(mid,result.context_message_refs).catch(e=>status(e.message));row.append(button);}group.append(row);
    }
    if(!items.length)group.append(node('p','No suggestions in this category.','hint'));
    const adopt=node('button','Use these suggestions','secondary');adopt.type='button';adopt.disabled=!items.length;adopt.onclick=()=>{$(key).value=items.map(i=>i.explanation).join('\n');$('reflection-save-panel').open=true;$(key).focus();};group.append(adopt);$('suggestions').append(group);
  }
  highlightReflection(result);
}
async function openSavedReflection(id){
  const value=await api(base()+'/reflections/'+encodeURIComponent(id));
  state.saved=value;
  clearInsights();
  const view=$('saved-view');
  view.replaceChildren(node('h3',value.stale?'이전 의견으로 저장한 성찰':'저장한 성찰'));
  for(const [key,title] of Object.entries(categories)){
    view.append(node('h3',title));
    $(key).value=value.user_items[key].map(item=>item.text).join('\n');
    for(const entry of value.user_items[key]){
      view.append(node('p',entry.text));
      for(const mid of entry.related_message_ids){
        const link=node('button','관련 대화','source-button');
        link.type='button';
        link.onclick=()=>jumpTo(mid,value.context_message_refs).catch(error=>status(error.message));
        view.append(link);
      }
    }
  }
  $('reflection-save-panel').open=true;
  $('save-state').textContent='이 저장본을 수정할 수 있습니다. 이전 저장본은 보존됩니다.';
}

function renderSaved(){
  const list=$('saved-reflections');
  list.replaceChildren();
  for(const item of state.session.reflections){
    const button=node('button','성찰 보기 · 저장본 '+item.revision,'secondary');
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
  button.setAttribute('aria-label', action + ' · ' + title);
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
  videos.replaceChildren(node('p','Loading analyzed videos…','muted'));
  records.replaceChildren(node('p','Loading your records…','muted'));
  const current=()=>load===libraryLoad&&$('library-dialog').open;
  const browser=browserRecords();
  const catalog=api('/analyses','GET',undefined,'').then(({analyses})=>{
    if(!current())return;
    videos.replaceChildren();
    for(const analysis of analyses){
      const title=analysis.video?.title||'Registered discussion';
      const detail=availableAnalysis(analysis)
        ? analysis.analyzed_comments+' analyzed comments · '+analysis.perspectives.length+' perspectives'
        : 'Source refresh required';
      videos.append(libraryRow(title,detail,availableAnalysis(analysis)?'Open video':'Expired',
        availableAnalysis(analysis)?()=>openDestination({analysis_id:analysis.analysis_id}):null));
    }
    if(!analyses.length)videos.append(node('p','No analyzed videos are available.','muted'));
  }).catch(()=>{
    if(current())videos.replaceChildren(node('p','Could not load videos. Reopen Library to retry.','muted'));
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
      const title=session.analysis.video?.title||'Registered discussion';
      for(const [index,room] of session.rooms.entries()){
        records.append(libraryRow(roomName(room,index),title+' · '+(roomStates[room.state]||room.state),'Open',
          ()=>openDestination({access,room_id:room.room_id})));
      }
      for(const reflection of session.reflections){
        records.append(libraryRow('Reflection · Revision '+reflection.revision,title,'Open',
          ()=>openDestination({access,reflection_id:reflection.reflection_id})));
      }
    }
    if(!records.childElementCount){
      records.append(node('p',results.some(result=>result.status==='rejected')
        ? 'No accessible records. A session may have expired.' : 'No saved debates or reflections yet.','muted'));
      const start=node('button','Start a review','secondary');
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

$('open-library').onclick=()=>{closeDialog('account-drawer');openLibrary();};
// The brand returns to the first page (video URL and initial view). The current session stays
// reachable through the step buttons until a new one is started.
document.querySelector('a.brand').addEventListener('click',event=>{
  event.preventDefault();
  for(const id of ['comparison','source-dialog','perspective-dialog','account-drawer'])closeDialog(id);
  if(state.editingInitial)leaveInitialEdit();
  $('workspace').hidden=true;$('before').hidden=false;$('initial').value='';$('initial').oninput();
  clearStepNav();
  status('');window.scrollTo(0,0);$('video-url').focus();
});
$('account-button').onclick=()=>openDialog('account-drawer');
$('close-account').onclick=()=>closeDialog('account-drawer');
$('original-video').addEventListener('click',()=>closeDialog('account-drawer'));
// Clicking the dimmed area outside the drawer closes it.
$('account-drawer').addEventListener('click',event=>{if(event.target===$('account-drawer'))closeDialog('account-drawer');});
$('close-library').onclick=closeLibrary;
$('library-dialog').addEventListener('cancel',event=>{event.preventDefault();closeLibrary();});
window.addEventListener('popstate',()=>{
  if(history.state?.reviewLibrary)openLibrary(false);
  else closeDialog('library-dialog');
});

async function enter(session,destination){
  state.analysis=session.analysis;
  setSession(session);
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
        status('최근 대화를 불러오지 못했습니다. Converse의 대화 목록에서 다시 열어 주세요.');
      }
    }
    return;
  }
  showStep('explore');
  $('explore-title').focus({preventScroll:true});
  status('');
}
$('initial').oninput=()=>{$('initial-count').textContent='Characters: '+[...$('initial').value].length+' / 500';};
$('clear-initial').onclick=()=>{$('initial').value='';$('initial').oninput();$('initial').focus();};
$('video-url').oninput=()=>{$('video-lookup-status').textContent='';};
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
  feedback.textContent='Looking for a saved analysis…';
  try{
    const query=new URLSearchParams({video:input.value});
    const {analyses}=await api('/analyses?'+query,'GET',undefined,'');
    const match=analyses.find(availableAnalysis);
    if(!match){
      feedback.textContent=analyses.length
        ? 'The saved analysis for this video has expired. Choose another video in Library.'
        : 'This video has no saved analysis yet. Choose an analyzed video in Library.';
      return;
    }
    if(match.analysis_id===state.analysis?.analysis_id){
      feedback.textContent='This video is already open.';
      return;
    }
    openDestination({analysis_id:match.analysis_id});
  }catch(error){
    feedback.textContent=error.code==='invalid_video_url'
      ? 'Enter a valid YouTube video URL.'
      : 'Could not look up this video. Try again.';
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
  if(state.editingInitial){button.disabled=true;try{await saveInitialEdit();}catch(e){status(e.message);}finally{button.disabled=false;}return;}
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
// The step bar lights up only after the first page; it stays unlit while writing the initial view.
function clearStepNav(){document.querySelectorAll('button[data-step]').forEach(b=>{b.classList.remove('active');b.removeAttribute('aria-current');});}
function beginLabel(text){$('begin-label').textContent=text;}
function startInitialEdit(){
  for(const id of ['comparison','source-dialog','perspective-dialog'])closeDialog(id);
  state.editingInitial=true;clearStepNav();$('workspace').hidden=true;$('before').hidden=false;$('video-lookup').hidden=true;$('cancel-initial-edit').hidden=false;
  $('initial').value=state.session.initial_opinion.text;$('initial').oninput();beginLabel('Update my view & return');
  $('begin').querySelector('button[type=submit]').disabled=false;window.scrollTo(0,0);$('initial').focus();
  status('');
}
function leaveInitialEdit(){
  state.editingInitial=false;$('before').hidden=true;$('workspace').hidden=false;$('video-lookup').hidden=false;$('cancel-initial-edit').hidden=true;
  beginLabel('Save & explore perspectives');
}
async function saveInitialEdit(){
  const text=$('initial').value,changed=text!==state.session.initial_opinion.text;
  if(changed){
    await retryableWrite('initial',base()+'/opinions/initial','PUT',{text,expected_revision:state.session.initial_opinion.revision});
    state.comparisons.clear();clearInsights();await refreshSession();
  }
  leaveInitialEdit();showStep('explore');renderPerspectives();
  status('');
}
$('toggle-initial').onclick=()=>{const open=$('initial-peek').hidden;$('initial-peek').hidden=!open;$('toggle-initial').setAttribute('aria-expanded',String(open));};
$('edit-initial-first').onclick=startInitialEdit;
$('cancel-initial-edit').onclick=()=>{leaveInitialEdit();showStep('explore');};
let creatingChat=false;
async function openConversation(ids,automatic,button){
  if(creatingChat||state.openingPending||!ids.length)return;
  creatingChat=true;button.disabled=true;
  try{
    if(automatic&&supportsDebate(ids.length)){
      setRoom({kind:'debate_draft',mode:'group',state:'idle',turn_count:0,turn_limit:2*ids.length,
               participant_ids:ids,messages:[],create_request_id:requestId(),start_request_id:requestId()});
      $('opening-question').value='';
    }else{
      const room=await retryableWrite('chat',base()+'/rooms','POST',{mode:ids.length===1?'one_to_one':'group',
        participant_ids:ids,initial_revision:state.session.initial_opinion.revision});
      setRoom(room);$('opening-question').value=defaultOpeningQuestion;await refreshSession();
    }
    closeDialog('new-chat-dialog');await refreshRoom();showStep('converse');status('');$('opening-question').focus();
  }catch(error){status(error.message);$('chat-picker-hint').textContent=error.message;}
  finally{creatingChat=false;button.disabled=false;updateSelection();}
}
if($('open-room'))$('open-room').onclick=()=>openConversation([...state.selected],supportsDebate(state.selected.size),$('open-room'));
let chatMode=null,chatOrder=[];
// Participants speak in the order they were picked.
function chatParticipants(){const checked=new Set([...$('chat-options').querySelectorAll('input:checked')].map(input=>input.value));chatOrder=chatOrder.filter(id=>checked.has(id));for(const id of checked)if(!chatOrder.includes(id))chatOrder.push(id);return [...chatOrder];}
function chatFormat(){return $('chat-picker').querySelector('input[name=chat-format]:checked')?.value||'conversation';}
function updateChatPicker(){
  const ids=chatParticipants(),group=chatMode==='group',limit=group?3:1;
  for(const input of $('chat-options').querySelectorAll('input'))input.disabled=group&&ids.length>=limit&&!input.checked;
  for(const row of $('chat-options').querySelectorAll('.picker-row'))row.classList.toggle('selected',row.querySelector('input').checked);
  $('chat-format-label').hidden=!(group&&supportsDebate(ids.length));
  $('chat-picker-hint').textContent=!state.analysis.perspectives.length?'This video has no available perspectives.':
    group?ids.length+' / 3 selected · choose two or three':ids.length?'1 selected':'Choose one perspective';
  $('chat-picker').querySelector('button[type=submit]').disabled=creatingChat||(group?ids.length<2:ids.length!==1);
}
// New chat rows follow the Figma conversation-list item: avatar, name, one line; groups stack vertically.
function pickerCard(p){
  const level=state.closeness.get(p.id)||(hasInitialView()?'pending':'empty');
  const row=node('label',undefined,'picker-row accent-'+indexOf(p.id)%5+' closeness-'+level),input=node('input');
  input.type=chatMode==='group'?'checkbox':'radio';input.name='chat-participant';input.value=p.id;
  input.onchange=()=>{if(input.checked&&!chatOrder.includes(p.id))chatOrder.push(p.id);updateChatPicker();};
  const face=node('span',undefined,'picker-face');face.append(avatar(p.id));
  const text=node('span',undefined,'picker-text'),line=state.closenessSummary.get(p.id)||p.text;
  text.append(node('strong',label(p.id)),node('small',line));text.title=line;
  const meta=node('span',undefined,'picker-meta');meta.append(perspectiveStats(p));
  row.append(input,face,text,meta,node('span','✓','picker-check'));
  return row;
}
function renderChatOptions(preselected){
  const box=$('chat-options');box.replaceChildren();chatOrder=[...preselected];
  const rows=new Map(state.analysis.perspectives.map(p=>[p.id,pickerCard(p)]));
  for(const id of preselected){const input=rows.get(id)?.querySelector('input');if(input)input.checked=true;}
  const order=state.closeness.size?['close','mixed','differ','consider','none','error']:[];
  for(const level of order){
    const members=state.analysis.perspectives.filter(p=>state.closeness.get(p.id)===level);if(!members.length)continue;
    const section=node('section',undefined,'picker-group closeness-'+level);
    section.append(node('h3',groupTitles[level]+' · '+members.length,'closeness-group-title'),...members.map(p=>rows.get(p.id)));box.append(section);
  }
  const rest=state.analysis.perspectives.filter(p=>!state.closeness.has(p.id));
  if(rest.length){const section=node('section',undefined,'picker-group');if(order.length)section.append(node('h3','Other perspectives','closeness-group-title'));section.append(...rest.map(p=>rows.get(p.id)));box.append(section);}
  updateChatPicker();
}
function chooseChatMode(mode,preselected=[]){
  chatMode=mode;$('chat-step-mode').hidden=true;$('chat-step-people').hidden=false;
  $('chat-step-label').textContent='NEW CHAT · STEP 2 OF 2';
  $('new-chat-title').textContent=mode==='group'?'Choose two or three perspectives':'Choose one perspective';
  $('chat-picker').querySelector('input[name=chat-format][value=conversation]').checked=true;
  renderChatOptions(preselected);
}
function showChatPicker(preselected = []){
  chatMode=null;$('chat-step-mode').hidden=false;$('chat-step-people').hidden=true;
  $('chat-step-label').textContent='NEW CHAT · STEP 1 OF 2';$('new-chat-title').textContent='How would you like to talk?';
  openDialog('new-chat-dialog');
  if(preselected.length)chooseChatMode(preselected.length>1?'group':'one',preselected);
}
document.querySelectorAll('[data-chat-mode]').forEach(button=>button.onclick=()=>chooseChatMode(button.dataset.chatMode));
$('chat-back').onclick=()=>showChatPicker();
$('chat-picker').onsubmit=event=>{
  event.preventDefault();openConversation(chatParticipants(),chatMode==='group'&&chatFormat()==='debate',$('chat-picker').querySelector('button[type=submit]'));
};
$('close-chat-picker').onclick=()=>closeDialog('new-chat-dialog');
$('close-evidence').onclick=closeEvidence;
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
    status('시작할 질문을 입력해 주세요.');
    $('opening-question').focus();
    return;
  }
  if([...question].length>1000){
    status('질문은 1,000자 이내로 입력해 주세요.');
    $('opening-question').focus();
    return;
  }
  state.openingPending=true;
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
$('interject').onsubmit=async event=>{
  event.preventDefault();
  const button=$('interject').querySelector('button[type=submit]'),roomId=state.room?.room_id;
  const question=$('question').value,recipient=$('address-agent').hidden?'':$('question-target').value;
  if(button.disabled||!roomId||!question.trim())return;
  button.disabled=true;
  try{
    await retryableWrite('message-'+roomId,'/rooms/'+roomId+'/messages','POST',{
      text:question,reply_to_message_id:null,...(recipient?{target_agent_id:recipient}:{})
    },()=>revisionForQuestion(roomId));
    if(state.room?.room_id===roomId){if($('question').value===question)$('question').value='';await refreshRoom();}
  }catch(error){status(error.message);}finally{button.disabled=false;}
};
document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{$('question').value=button.dataset.prompt;$('question').focus();});
$('agent-info').onclick=async()=>{
  const container=$('perspective-info');
  container.replaceChildren();
  const room=state.room;
  try{
    if(room?.kind==='synthesis_chat'){
      const agent=await api('/synthesis-agents/'+encodeURIComponent(room.participant_ids[0]));
      if(state.room?.room_id!==room.room_id)return;
      container.append(node('h3','합의 Agent'),node('p',agent.parent_refs.map(row=>label(row.agent_id)).join(', ')));
      for(const claim of agent.accepted_claims)container.append(node('p',claim.text));
    }else{
      for(const id of room?.participant_ids||[]){
        const p=perspective(id);
        const entry=node('section',undefined,'perspective-info-entry');
        entry.append(node('h3',label(id)),node('p',p.text),node('small',p.source_count+(p.admission_policy?' verified source comments':' source comments')));
        container.append(entry);
      }
    }
    openDialog('perspective-dialog');
  }catch(error){status(error.message);}
};
for(const [button,id] of [['close-comparison','comparison'],['close-source','source-dialog'],['close-perspective','perspective-dialog']])$(button).onclick=()=>closeDialog(id);
$('comparison').addEventListener('close',()=>{$('comparison').hidden=true;state.openComparison=null;});
$('go-reflect').onclick=()=>showStep('reflect');$('go-converse').onclick=()=>showStep('converse');document.querySelectorAll('button[data-step]').forEach(button=>button.onclick=()=>showStep(button.dataset.step));
$('edit-current').onclick=()=>{clearInsights();$('current').focus();};
$('write-manually').onclick=()=>{$('reflection-save-panel').open=true;$('stayed').focus();};
$('analyze').onclick=async()=>{const button=$('analyze');button.disabled=true;try{await saveCurrent();status('나의 의견과 선택한 대화를 정리하고 있습니다.');const value=await api(base()+'/reflection-analyses','POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,context_message_ids:[...state.context],request_id:requestId()});const job=await pollJob(value);if(job.stale){status('의견이 변경됐습니다. 현재 의견으로 다시 분석해 주세요.');return;}state.reflectionJob=job.job_id;state.reflectionResult=job.result;renderSuggestions(job.result);status('제안에서 필요한 내용을 선택하거나 직접 수정해 저장해 주세요.');}catch(e){status(e.message);}finally{button.disabled=false;}};
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
    $('save-state').textContent = '저장했습니다. '+value.revision+'번째 저장본';
    status('');
    await refreshSession();
  } catch (error) {
    status(error.message);
  } finally {
    button.disabled = false;
  }
};

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
        status('기존 기록을 불러오지 못했습니다. 잠시 뒤 새로고침해 다시 시도해 주세요.');
        return;
      }
      if(readStored(localStorage,savedSessionKey)?.session_id===saved.session_id){
        localStorage.removeItem(savedSessionKey);
      }
      if (sessionStorage.getItem(tabSessionKey) === saved.session_id) leaveSession();
      state.token='';
      resumeMessage=error.code==='session_expired'
        ? '이전 세션 기한이 지났습니다. 새로 시작해 주세요.'
        : '이전 기록을 열 수 없습니다. Library에서 분석이나 다른 기록을 선택하세요.';
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
  if(!state.analysis){status('아직 사용할 수 있는 분석이 없습니다.');return;}
  renderAnalysis();
  $('begin').querySelector('button[type=submit]').disabled=false;
  status(resumeMessage||(preferred&&preferred!==state.analysis.analysis_id
    ? '선택한 분석은 지금 열 수 없습니다. 현재 선택된 영상을 확인하세요.'
    : ''));
}

start().catch(error=>status(error.message)).finally(()=>{$('open-video-url').disabled=false;});
