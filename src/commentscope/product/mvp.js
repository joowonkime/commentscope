'use strict';
const $ = id => document.getElementById(id);
const categories = {stayed:'What stayed the same', changed:'What changed', newly_learned:'Newly learned', worth_more_thought:'Worth more thought'};
const state = {analysis:null, session:null, token:'', room:null, roomTimer:null, selected:new Set(), context:new Set(), comparisons:new Map(), reflectionJob:null, reflectionResult:null, saved:null, roomFilter:'all', openingPending:false, openComparison:null, sourceTexts:new Map(), editingInitial:false, closeness:new Map()};
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const requestId = () => crypto.randomUUID();
const savedSessionKey = 'commentscope-mvp-session';
const librarySessionsKey = 'commentscope-mvp-library-sessions';
const libraryDestinationKey = 'commentscope-mvp-library-destination';
const selectedAnalysisKey = 'commentscope-mvp-selected-analysis';
let libraryLoad = 0;
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function asset(name) { const img=node('img'); img.src='/mvp/assets/'+name+'.svg'; img.alt=''; return img; }
function status(text) { $('status').textContent=text; }
function errorText(code) { return ({revision_conflict:'내용이 갱신됐습니다. 최신 화면을 확인한 뒤 다시 눌러 주세요.',opinion_revision_conflict:'의견이 갱신됐습니다. 다시 확인해 주세요.',analysis_revision_conflict:'의견 또는 분석 버전이 달라졌습니다. 제안을 다시 확인하거나 직접 저장해 주세요.',resource_busy:'이미 토론이 진행 중입니다. 현재 기록에서 확인할 수 있습니다.',debate_not_ready:'이 토론은 현재 상태에서 다시 시작할 수 없습니다.',capacity_hold:'필수 근거의 분량이 커 검증이 보류됐습니다. 게시된 발언은 보존됩니다.',room_not_ready:'현재 응답이 끝나거나 대화가 정지한 뒤 질문할 수 있습니다.',budget_exhausted:'현재 AI 사용 한도에 도달했습니다. 기존 대화 읽기와 직접 저장은 가능합니다.',cycle_deadline:'이번 AI 실행 시간이 끝났습니다. 읽기와 직접 저장은 가능합니다.',reconcile_required:'AI 처리가 중단돼 확인이 필요합니다. 기존 기록은 보존됩니다.',source_expired:'근거 자료의 사용 기한이 지났습니다.',session_expired:'세션 기한이 지났습니다. 새로 시작해 주세요.',invalid_participants:'대화할 수 있는 관점을 하나 이상 선택해 주세요.',turn_limit:'이 대화의 발화 한도에 도달했습니다.',context_capacity:'관련 대화는 최대 24개까지 선택할 수 있습니다.',queue_capacity:'다른 작업을 처리하고 있습니다. 잠시 뒤 다시 눌러 주세요.',model_or_validation_failed:'AI 응답을 완료하지 못했습니다. 입력과 기존 기록은 보존됐습니다.'})[code] || '요청을 완료하지 못했습니다. 입력과 이전 기록을 확인해 주세요.'; }
async function api(path, method='GET', body, token=state.token) {
  const headers={}; if(token)headers['X-Session-Token']=token;
  if(body!==undefined)headers['Content-Type']='application/json';
  const response=await fetch('/api/v1'+path,{method,headers,...(body===undefined?{}:{body:JSON.stringify(body)})});
  const value=await response.json();
  if(!response.ok){const e=new Error(errorText(value.error?.code||value.error)); e.code=value.error?.code||value.error; throw e;}
  return value;
}
function base(){return '/sessions/'+state.session.session_id;}
function indexOf(id){return state.analysis.perspectives.findIndex(p=>p.id===id);}
function perspective(id){return state.analysis.perspectives.find(p=>p.id===id);}
function label(id){if(state.room?.kind==='synthesis_chat'&&state.room.participant_ids.includes(id))return '합의 Agent';const i=indexOf(id); return i<0?'Perspective':'Perspective '+(i+1);}
function avatar(id,small=false){const i=Math.max(0,indexOf(id)); return asset(small?'0385b':['4ea9b','5e642','baf01','d51bb','e77a2'][i%5]);}
function closeDialog(id){const dialog=$(id); if(dialog.open)dialog.close(); if(id==='comparison')dialog.hidden=true;}
function openDialog(id){const dialog=$(id); dialog.hidden=false; if(!dialog.open)dialog.showModal();}
function showStep(step){
  if(!state.session)return;
  if(state.editingInitial)leaveInitialEdit();
  $('before').hidden=true;$('workspace').hidden=false;
  if(step==='converse'&&!state.room&&state.session.rooms.length){chooseRoom(state.session.rooms[0].room_id).catch(e=>status(e.message));return;}
  $('converse').toggleAttribute('data-no-room',step==='converse'&&!state.room);
  for(const id of ['comparison','source-dialog','perspective-dialog'])closeDialog(id);
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
  $('analysis-summary').textContent=a.perspectives.length+' perspectives from '+(Number.isInteger(n)?n+' '+unit:'the registered comments')+(a.canonical_population?' · Original population: '+a.canonical_population+' comments.':'.');
  $('sidebar-video-meta').textContent=Number.isInteger(n)?n+' '+unit:'';
  if(video.description)$('video-description').textContent=video.description;
  if(typeof vid==='string'&&/^[A-Za-z0-9_-]{11}$/.test(vid)){
    const url='https://www.youtube.com/watch?v='+vid;
    for(const id of ['original-video','sidebar-video']){$(id).href=url; $(id).hidden=false;}
    const thumb=()=>{const img=node('img');img.src='https://i.ytimg.com/vi/'+vid+'/hqdefault.jpg';img.alt=title;return img;};
    $('sidebar-thumbnail').replaceChildren(thumb());
    const play=node('button',undefined,'video-play');play.type='button';play.setAttribute('aria-label','Play source video');play.append(thumb(),node('span','▶'));
    play.onclick=()=>{const frame=node('iframe');frame.src='https://www.youtube-nocookie.com/embed/'+vid+'?autoplay=1';frame.title=title;frame.referrerPolicy='strict-origin-when-cross-origin';frame.allow='autoplay; encrypted-media; picture-in-picture';frame.allowFullscreen=true;$('video-frame').replaceChildren(frame);};
    $('video-frame').replaceChildren(play);
  }
  renderComposition();
}
function renderComposition(){
  const entries=state.analysis.composition||[], total=entries.reduce((sum,e)=>sum+e.count,0);
  const linked=entries.filter(e=>e.count&&e.kind!=='other'),linkedTotal=linked.reduce((sum,e)=>sum+e.count,0);
  $('composition-chart').replaceChildren();$('composition-legend').replaceChildren();
  if(!total){$('composition-chart').append(node('p','Comment composition is not available.','muted'));return;}
  // The bar fills its width with the comments linked to perspectives; unlinked comments are counted in text.
  $('composition-chart').append(node('p',linkedTotal+' of '+total+' analyzed comments are linked to a perspective.','composition-total'));
  if(linkedTotal){
    const bar=node('div',undefined,'composition-bar');bar.setAttribute('role','img');bar.setAttribute('aria-label','Comments linked to each perspective');
    for(const e of linked){
      const seg=node('span',e.perspective_id?label(e.perspective_id):'Multiple',e.perspective_id?'chart-'+Math.max(0,indexOf(e.perspective_id))%5:'chart-'+e.kind);
      seg.style.flexGrow=String(e.count);seg.title=e.count+' comments';
      if(e.perspective_id){seg.dataset.perspective=e.perspective_id;seg.onmouseenter=()=>linkComposition(e.perspective_id,true);seg.onmouseleave=()=>linkComposition(e.perspective_id,false);}
      bar.append(seg);
    }
    $('composition-chart').append(bar);
  }
  for(const e of entries){if(!e.count)continue;const i=indexOf(e.perspective_id),cls=e.perspective_id?'accent-'+Math.max(0,i)%5:e.kind,percent=e.count/total*100;
    const line=node('span',undefined,cls);line.append(node('i',undefined,'legend-dot'),node('span',(e.perspective_id?label(e.perspective_id):e.kind==='multiple'?'Multiple perspectives':'Not linked to a perspective')+' · '+e.count+' ('+percent.toFixed(1)+'%)'));
    if(e.perspective_id){line.dataset.perspective=e.perspective_id;line.onmouseenter=()=>linkComposition(e.perspective_id,true);line.onmouseleave=()=>linkComposition(e.perspective_id,false);}
    $('composition-legend').append(line);
  }
}
// Hovering a card or a bar segment highlights its counterpart.
function linkComposition(pid,on){
  for(const el of document.querySelectorAll('#composition-chart [data-perspective], #composition-legend [data-perspective], #perspectives .card'))if(el.dataset.perspective===pid)el.classList.toggle('linked',on);
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
  title.append(node('strong',label(p.id)),node('small',p.source_count+(p.admission_policy?' verified source comments':' source comments')));
  top.append(avatar(p.id),title);
  const relation=node('p','','relation-summary');
  card.append(top,node('p',p.text,'card-stance'),relation);
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
function cardGrid(cards){const grid=node('div',undefined,'cards');grid.append(...cards);return grid;}
// Groups run from closest to most different, so reading top to bottom conveys distance without a score.
const closenessOrder=['close','mixed','consider','differ','none','error'];
const groupTitles={close:'Close to your view',mixed:'Partly close, partly different',consider:'Adds something to consider',
  differ:'Different from your view',none:'No clear link to your view',error:'Could not compare right now'};
async function renderPerspectives(){
  const box=$('perspectives'),render=state.cardRender=(state.cardRender||0)+1,list=state.analysis.perspectives;
  state.closeness.clear();
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
    setCloseness(card,level);summary.textContent=keySentence(lead,level);groups.get(level).push(card);state.closeness.set(p.id,level);
  });
  box.replaceChildren();
  for(const [level,members] of groups){
    if(!members.length)continue;
    const section=node('section',undefined,'closeness-group closeness-'+level);
    section.append(node('h2',groupTitles[level]+' · '+members.length,'closeness-group-title'),cardGrid(members));box.append(section);
  }
}
function hasInitialView(){return !!state.session.initial_opinion.text.trim();}
// One comparison job per (initial revision, perspective). Revisiting reuses the finished job.
function comparison(pid){
  const key=state.session.initial_opinion.revision+':'+pid;
  if(!state.comparisons.has(key)){
    const pending=api(base()+'/comparisons','POST',{perspective_id:pid,initial_revision:state.session.initial_opinion.revision,request_id:requestId()}).then(pollJob);
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
function commentSourceButtons(container,sourceIds,caption='원문'){
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

function roomName(room,index){
  if(room.kind==='synthesis_chat')return '합의 Agent 대화 '+(index+1);
  if(room.kind==='structured_debate')return '자동 토론 '+(index+1);
  return (room.mode==='group'?'Group conversation ':'1:1 conversation ')+(index+1);
}
function roomPath(room){
  return room.debate_id?'/debates/'+encodeURIComponent(room.debate_id):'/rooms/'+encodeURIComponent(room.room_id);
}
function setRoom(room){
  clearTimeout(state.roomTimer);
  state.room=room;
}
function rememberConversation(){
  const room=state.room;
  if(document.body.dataset.step==='converse'&&room?.room_id&&room.kind){
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
    const button=node('button',undefined,'room-entry');button.type='button';button.classList.toggle('active',state.room?.room_id===room.room_id);button.append(node('strong',title),node('small',roomStates[room.state]||room.state));button.onclick=()=>chooseRoom(room.room_id).catch(e=>status(e.message));list.append(button);
  });
  if(!list.childNodes.length)list.append(node('p','No conversations here yet.','muted'));if(state.room?.room_id)select.value=state.room.room_id;
}
function renderMessages(){
  $('messages').replaceChildren();
  for(const m of state.room.messages){const box=node('article',undefined,'message '+m.author_kind);box.id='message-'+m.message_id;
    if(m.author_kind==='agent'){const icon=node('div',undefined,'message-avatar');icon.append(avatar(m.agent_id,true));box.append(icon);}
    const bubble=node('div',undefined,'bubble');
    const phase=({opening:'입장 발언',reply:'상대 입장 응답'})[m.phase];
    const speaker=m.author_kind==='user'?'You':label(m.agent_id);
    bubble.append(node('small',phase?speaker+' · '+phase:speaker));
    if(m.reply_to_message_id){const reply=state.room.messages.find(x=>x.message_id===m.reply_to_message_id);if(reply?.author_kind==='agent')bubble.append(node('small',label(reply.agent_id)+'의 앞선 발언에 대한 응답'));}
    if(m.body)bubble.append(node('p',m.body));
    if(m.author_kind==='agent'&&!m.points?.length)bubble.append(node('p',m.evidence_scope==='expired'?'근거 자료의 기한이 지났습니다.':'이 질문에 답할 근거를 자료에서 찾지 못했습니다.'));
    for(const point of m.points||[]){
      const origin=pointOrigin(point.origin);
      if(origin)bubble.append(node('small',origin));
      const text=node('p',point.text);
      if(point.point_id)text.id='point-'+point.point_id;
      bubble.append(text);
      sourceButtons(bubble,point);
      for(const target of point.target_edges||[]){
        appendPointLinks(bubble,[target.point_id],state.room,'응답 대상 · '+label(target.agent_id));
      }
    }
    if(m.status==='abstain'&&m.points?.length)bubble.append(node('small','요청한 답을 확인할 수 없어 자료의 한계를 설명합니다.'));
    if(m.limitation==='verification_hold')bubble.append(node('small','추가 설명을 확인하지 못해, 확인할 수 있는 내용만 표시했습니다.'));
    if(m.required_premises?.length){bubble.append(node('small','함께 확인할 전제·조건'));for(const point of m.required_premises){bubble.append(node('p',point.text));sourceButtons(bubble,point);}}
    box.append(bubble);$('messages').append(box);
  }
}
function pointOrigin(origin){
  return ({original_comment:'댓글 근거',ai_reasoning:'AI 추론 · 원작성자의 발언이 아닙니다',
    external_evidence:'외부 자료 기반 주장'})[origin];
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
      const read=node('button','계보 원문 '+(i+1),'source-button');
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
  }
}
function renderRoom(){
  const room=state.room;
  renderMessages();
  renderRooms();
  renderConclusion(room);
  const ids=room.participant_ids||[];
  $('room-avatars').replaceChildren(...ids.map(id=>avatar(id)));
  $('room-title').textContent=ids.map(label).join(' × ')||'Your conversation';
  const automatic=room.kind==='structured_debate'||room.kind==='debate_draft';
  $('messages').classList.toggle('structured-transcript',automatic);
  $('show-debate-result').hidden=!room.conclusion;
  $('room-summary').textContent=automatic?'관점별 입장과 응답을 읽고 마지막 결론을 확인하세요.':
    room.kind==='synthesis_chat'?'공통 주장과 조건에 대해 질문할 수 있습니다.':
    room.mode==='group'?'Different perspectives, in one conversation.':'A conversation with this perspective.';
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
  const openingQuestion=$('opening-question');
  openingQuestion.readOnly=Boolean(room.plan)&&room.state==='idle';
  if(openingQuestion.readOnly)openingQuestion.value=room.plan.question;
  $('opening').hidden=room.state!=='idle';
  $('opening').querySelector('button[type=submit]').disabled=state.openingPending||room.can_start===false;
  $('opening').querySelector('h2').textContent=automatic?'어떤 쟁점을 토론할까요?':'What would you like to ask?';
  $('opening-submit-label').textContent=automatic?'자동 토론 시작':'Start conversation';
  $('pause').disabled=automatic?!room.can_pause:!['running','awaiting_user'].includes(room.state);
  $('resume').disabled=automatic?!room.can_resume:room.state!=='paused';
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
    const room=await api(resource+'/rooms','POST',{
      agent_revision:agent.revision,initial_revision:state.session.initial_opinion.revision,request_id:requestId()});
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
async function saveCurrent(){const value=$('current').value;if(!state.session.current_opinion.revision||value!==state.session.current_opinion.text){await api(base()+'/opinions/current','PUT',{text:value,expected_revision:state.session.current_opinion.revision,request_id:requestId()});clearInsights();await refreshSession();}return state.session.current_opinion.revision;}
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
  button.disabled=!onClick;
  if(onClick)button.onclick=onClick;
  row.append(information,button);
  return row;
}

function openDestination(destination){
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
  setSession(session);
  state.analysis=session.analysis;
  renderAnalysis();
  $('before').hidden=true;
  $('workspace').hidden=false;
  renderPerspectives();
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
      if(document.body.dataset.step==='converse')status('');
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
  const bytes=crypto.getRandomValues(new Uint8Array(32));
  state.token=btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  try{
    const session=await api('/sessions','POST',{analysis_id:state.analysis.analysis_id,
      bundle_revision:state.analysis.bundle_revision,initial_opinion:$('initial').value,request_id:requestId()});
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
    await api(base()+'/opinions/initial','PUT',{text,expected_revision:state.session.initial_opinion.revision,request_id:requestId()});
    state.comparisons.clear();clearInsights();await refreshSession();
  }
  leaveInitialEdit();showStep('explore');renderPerspectives();
  status('');
}
$('toggle-initial').onclick=()=>{const open=$('initial-peek').hidden;$('initial-peek').hidden=!open;$('toggle-initial').setAttribute('aria-expanded',String(open));};
$('edit-initial-first').onclick=startInitialEdit;
$('cancel-initial-edit').onclick=()=>{leaveInitialEdit();showStep('explore');};
if($('open-room'))$('open-room').onclick=async()=>{
  const button=$('open-room');
  if(button.disabled||state.openingPending)return;
  button.disabled=true;
  try{
    const ids=[...state.selected];
    if(supportsDebate(ids.length)){
      setRoom({kind:'debate_draft',mode:'group',state:'idle',turn_count:0,turn_limit:2*ids.length,
               participant_ids:ids,messages:[],create_request_id:requestId(),start_request_id:requestId()});
      $('opening-question').value='';
    }else{
      $('opening-question').value=defaultOpeningQuestion;
      setRoom(await api(base()+'/rooms','POST',{mode:ids.length===1?'one_to_one':'group',
        participant_ids:ids,initial_revision:state.session.initial_opinion.revision,request_id:requestId()}));
      await refreshSession();
    }
    await refreshRoom();
    showStep('converse');
    status('');
    $('opening-question').focus();
  }catch(error){status(error.message);}
  finally{updateSelection();}
};
$('rooms').onchange=()=>{if($('rooms').value)chooseRoom($('rooms').value).catch(e=>status(e.message));};
$('room-search').oninput=renderRooms;
document.querySelectorAll('[data-room-filter]').forEach(button=>button.onclick=()=>{state.roomFilter=button.dataset.roomFilter;document.querySelectorAll('[data-room-filter]').forEach(b=>b.classList.toggle('active',b===button));renderRooms();});
$('new-chat').onclick=()=>showStep('explore');
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
$('interject').onsubmit=async event=>{event.preventDefault();try{await refreshRoom();if(state.room.state==='running')await control('pause');while(state.room.state==='pausing'){await wait(600);await refreshRoom();}await api('/rooms/'+state.room.room_id+'/messages','POST',{text:$('question').value,reply_to_message_id:null,expected_revision:state.room.revision,request_id:requestId()});$('question').value='';await refreshRoom();}catch(e){status(e.message);}};
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
$('save-reflection').onsubmit=async event=>{event.preventDefault();try{await saveCurrent();const user_items={};for(const key of Object.keys(categories)){const values=$(key).value.split('\n').filter(s=>s.trim());user_items[key]=values.map(value=>{const savedMatches=state.saved&&['initial','current'].every(kind=>state.saved[kind+'_revision']===state.session[kind+'_opinion'].revision);const original=state.reflectionResult?.categories[key].find(i=>i.explanation===value)||(savedMatches?state.saved.user_items[key].find(i=>i.text===value):null);return {text:value,initial_span_ids:original?.initial_span_ids||[],current_span_ids:original?.current_span_ids||[],related_message_ids:original?.related_message_ids||[]};});}const path=base()+'/reflections'+(state.saved?'/'+state.saved.reflection_id:'');const value=await api(path,state.saved?'PUT':'POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,analysis_job_id:state.reflectionJob,user_items,expected_revision:state.saved?.revision||0,request_id:requestId()});state.saved=value;$('save-state').textContent='저장했습니다. '+value.revision+'번째 저장본';await refreshSession();}catch(e){status(e.message);}};

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
    localStorage.removeItem(savedSessionKey);
    sessionStorage.removeItem(lastRoomKey);
  }
  const saved=destination?.access||readStored(localStorage,savedSessionKey);
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
        sessionStorage.removeItem(lastRoomKey);
      }
      state.token='';
      resumeMessage=error.code==='session_expired'
        ? '이전 세션 기한이 지났습니다. 새로 시작해 주세요.'
        : '이전 기록을 열 수 없습니다. Library에서 분석이나 다른 기록을 선택하세요.';
      if(destination?.access&&readStored(localStorage,savedSessionKey)){
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

// ---- Interface language (English / 한국어) ----
// Only interface text is translated. User opinions, source comments and AI output are left as written.
// Each pair is [English, 한국어]; the DOM is translated in place, including text added later.
const I18N_PAIRS=[
['Re.View · Explore different perspectives','Re.View · 다양한 관점 살펴보기'],['Explore','탐색'],['Converse','대화'],['Reflect','성찰'],
['Loading the registered discussion…','등록된 토론을 불러오는 중…'],['YouTube video URL','YouTube 영상 URL'],['Open video','영상 열기'],
['A discussion, seen from more than one side.','하나의 토론을 여러 시각에서.'],['Start with your own point of view.','나의 관점에서 시작하세요.'],
['BEFORE YOU DISCOVER','관점을 보기 전에'],['What do you think?','어떻게 생각하세요?'],
['You’ll get to explore other perspectives after saving your initial thoughts.','처음 생각을 저장하면 다른 관점을 살펴볼 수 있습니다.'],
['Your initial view','나의 처음 의견'],['× Clear','× 지우기'],['Save & explore perspectives','저장하고 관점 살펴보기'],['Cancel and go back','취소하고 돌아가기'],
['Update my view & return','의견 수정하고 돌아가기'],['STEP 01 · EXPLORE DIVERSE PERSPECTIVES','1단계 · 다양한 관점 탐색'],
['Here’s what the comments are saying','댓글에 나타난 관점들입니다'],['✍ My initial view ▾','✍ 나의 처음 의견 ▾'],['← Edit on the first page','← 첫 페이지에서 수정'],
['How the analyzed comments are composed','분석한 댓글의 구성'],['Each comment is counted once.','댓글 하나는 한 번만 셉니다.'],['Go to Converse','대화로 이동'],
['Conversations','대화 목록'],['SOURCE VIDEO','영상'],['This discussion','이 토론'],['RECENT','최근'],['All','전체'],['Group','그룹'],
['Search conversations','대화 검색'],['⌕ Search conversations','⌕ 대화 검색'],['Previous conversation','이전 대화'],['Choose a conversation','대화 선택'],['＋ New chat','＋ 새 대화'],
['Choose a perspective','관점을 선택하세요'],['Your conversation stays connected to its source comments.','대화는 원댓글과 계속 연결됩니다.'],
['ⓘ Perspective info','ⓘ 관점 정보'],['Choose perspectives in Explore to start.','탐색에서 관점을 선택해 시작하세요.'],['Pause','멈추기'],['Resume','계속'],
['Next round','다음 라운드'],['End chat','대화 종료'],['Show debate conclusion','토론 결론 보기'],['START A CONVERSATION','대화 시작하기'],
['What would you like to ask?','무엇을 물어볼까요?'],['Opening question','첫 질문'],
['What is this perspective’s central position, and what reasons support it?','이 관점의 핵심 입장은 무엇이고, 어떤 이유가 뒷받침하나요?'],
['Start conversation','대화 시작'],['No conversations yet. Starting a conversation from Explore will be added next.','아직 대화가 없습니다. 탐색에서 대화를 시작하는 기능은 다음에 추가됩니다.'],
['Your question or contribution','나의 질문이나 의견'],['⌁ Ask for evidence','⌁ 근거 묻기'],['Ask about conditions','조건 묻기'],['Reflect on your own view →','나의 의견 성찰하기 →'],
['Ask why, request evidence, or explore another angle…','이유를 묻거나, 근거를 요청하거나, 다른 측면을 살펴보세요…'],['Send question','질문 보내기'],
['STEP 03 · REFLECTION ON YOUR OWN VIEWPOINT','3단계 · 나의 관점 성찰'],['Reflect on your own viewpoint','나의 관점을 돌아보세요'],
['You’ve explored different perspectives and talked with the agents. Now write down your thoughts freely.','다양한 관점을 살펴보고 에이전트와 대화했습니다. 이제 생각을 자유롭게 적어 보세요.'],
['If your view changed, how did it change? If it stayed the same, why? What did you notice or learn?','의견이 바뀌었다면 어떻게 바뀌었나요? 그대로라면 왜인가요? 무엇을 알게 되었나요?'],
['📌 YOUR INITIAL VIEW','📌 나의 처음 의견'],['◴ YOUR CONVERSATIONS','◴ 나의 대화'],['Choose conversations to refer to in your reflection.','성찰에 참고할 대화를 고르세요.'],
['Choose individual messages','메시지 골라 선택'],['✍ YOUR CURRENT VIEW','✍ 나의 지금 의견'],['Edit my current view','지금 의견 수정'],['Analyze my reflection','성찰 분석하기'],
['Or write and save without AI','또는 AI 없이 직접 작성해 저장'],['◴ How your thinking evolved','◴ 생각이 어떻게 달라졌나'],['Read each part ↓','항목별로 읽기 ↓'],
['Write, edit & save your reflection','성찰 작성·수정·저장'],['Keep the suggestions that fit your thinking, or write your own. You can leave any category empty.','생각에 맞는 제안을 남기거나 직접 쓰세요. 비워 둔 항목이 있어도 됩니다.'],
['What stayed the same','그대로인 점'],['What changed','바뀐 점'],['What you learned','새로 알게 된 점'],['Newly learned','새롭게 배운 점'],['Worth more thought','더 생각해볼 점'],
['✓ Save my reflection','✓ 성찰 저장'],['Saved reflections','저장한 성찰 목록'],
['What do you think now? Keeping the same view is just as valid as changing it.','지금은 어떻게 생각하세요? 의견을 유지하는 것도 바꾸는 것만큼 의미 있습니다.'],
['Guest','게스트'],['Private session on this browser','이 브라우저의 개인 세션'],['Your activity','나의 활동'],['Library','라이브러리'],
['Analyzed videos and your saved records','분석한 영상과 저장한 기록'],['Original video','원본 영상'],['Open on YouTube ↗','YouTube에서 열기 ↗'],['Account','계정'],
['Coming soon','준비 중'],['Profile','프로필'],['Name and sign-in','이름과 로그인'],['Settings','설정'],['Language and display','언어와 화면'],['Help & feedback','도움말·의견 보내기'],
['You are not signed in. Your records are kept with this browser session.','로그인하지 않은 상태입니다. 기록은 이 브라우저 세션에 보관됩니다.'],['Language','언어'],
['Close','닫기'],['Analyzed videos','분석한 영상'],['My records','나의 기록'],['COMPARE WITH YOUR VIEW','나의 의견과 비교'],['Perspective','관점'],
['✍ Your initial view','✍ 나의 처음 의견'],['━ Similar','━ 비슷함'],['━ Different','━ 다름'],['━ To consider','━ 생각해볼 점'],['Original comment','원댓글'],
['Read the comment behind the response.','응답의 근거가 된 댓글을 읽어 보세요.'],['Choose an evidence link in the conversation.','대화의 근거 링크를 선택하세요.'],
['About these perspectives','관점 소개'],['This experience needs JavaScript to save your view and connect conversations.','의견 저장과 대화 연결에 JavaScript가 필요합니다.'],
['Re.View home','Re.View 홈'],['Your journey','진행 단계'],['Open your menu','메뉴 열기'],['Close menu','메뉴 닫기'],['Your menu','나의 메뉴'],
['What stands out to you? What do you agree with, disagree with, or feel unsure about?','무엇이 눈에 띄나요? 동의하는 점, 동의하지 않는 점, 확신이 서지 않는 점을 적어 보세요.'],
['Close comparison','비교 닫기'],['Close original comment','원댓글 닫기'],['Close perspective info','관점 정보 닫기'],['Debate conclusion','토론 결론'],
['You started without an initial view.','처음 의견 없이 시작했습니다.'],['Play source video','원본 영상 재생'],['Comment composition is not available.','댓글 구성을 표시할 수 없습니다.'],
['Comments linked to each perspective','관점별로 연결된 댓글'],['Multiple perspectives','여러 관점'],['Not linked to a perspective','관점에 연결되지 않음'],['Multiple','복수'],
['Close to your view','나와 가까운 관점'],['Partly close, partly different','일부 가깝고 일부 다른 관점'],['Adds something to consider','생각해볼 점을 주는 관점'],
['Different from your view','나와 다른 관점'],['No clear link to your view','나의 의견과 뚜렷한 관련이 없음'],['Could not compare right now','지금은 비교할 수 없음'],
['Write your initial view to see which perspectives are close to yours.','처음 의견을 쓰면 어떤 관점이 나와 가까운지 볼 수 있습니다.'],
['Comparing with your view…','나의 의견과 비교하는 중…'],['Add your initial view to compare','처음 의견을 쓰면 비교할 수 있습니다'],['Comparison is not available right now','지금은 비교할 수 없습니다'],
['Comments close to your view','나와 비슷한 댓글'],['Comments partly close, partly different','일부 비슷하고 일부 다른 댓글'],['Comments different from your view','나와 다른 댓글'],
['Comments that add something to consider','생각해볼 점을 주는 댓글'],['Other comments in this perspective','이 관점의 다른 댓글'],['Replying to another comment','다른 댓글에 단 답글'],
['This comment could not be loaded.','이 댓글을 불러오지 못했습니다.'],['Condition:','조건:'],['Qualification:','단서:'],['Reason:','이유:'],
['No source comments are linked to this perspective.','이 관점에 연결된 원댓글이 없습니다.'],['What commenters said','댓글 작성자들의 말'],
['No conversations here yet.','아직 대화가 없습니다.'],['Your conversation','나의 대화'],['Different perspectives, in one conversation.','여러 관점을 한 대화에서.'],
['A conversation with this perspective.','이 관점과의 대화.'],['BEFORE','이전'],['NOW','지금'],['No suggestions in this category.','이 항목에는 제안이 없습니다.'],['Use these suggestions','이 제안 사용'],
['Loading analyzed videos…','분석한 영상을 불러오는 중…'],['Loading your records…','기록을 불러오는 중…'],['Registered discussion','등록된 토론'],['Source refresh required','원본 갱신 필요'],
['No analyzed videos are available.','분석한 영상이 없습니다.'],['Could not load videos. Reopen Library to retry.','영상을 불러오지 못했습니다. 라이브러리를 다시 열어 주세요.'],
['No accessible records. A session may have expired.','열 수 있는 기록이 없습니다. 세션이 만료되었을 수 있습니다.'],['No saved debates or reflections yet.','저장한 토론이나 성찰이 아직 없습니다.'],
['Start a review','검토 시작'],['Looking for a saved analysis…','저장된 분석을 찾는 중…'],
['The saved analysis for this video has expired. Choose another video in Library.','이 영상의 저장된 분석이 만료되었습니다. 라이브러리에서 다른 영상을 고르세요.'],
['This video has no saved analysis yet. Choose an analyzed video in Library.','이 영상은 아직 분석되지 않았습니다. 라이브러리에서 분석된 영상을 고르세요.'],
['This video is already open.','이미 열려 있는 영상입니다.'],['Enter a valid YouTube video URL.','올바른 YouTube 영상 URL을 입력하세요.'],['Could not look up this video. Try again.','영상을 찾지 못했습니다. 다시 시도해 주세요.'],
['Group conversation','그룹 대화'],['1:1 conversation','1:1 대화'],
// Korean-first interface messages
['The content was updated. Check the latest screen and try again.','내용이 갱신됐습니다. 최신 화면을 확인한 뒤 다시 눌러 주세요.'],
['Your view was updated. Please check it again.','의견이 갱신됐습니다. 다시 확인해 주세요.'],
['Your view or the analysis version changed. Review the suggestions again or save directly.','의견 또는 분석 버전이 달라졌습니다. 제안을 다시 확인하거나 직접 저장해 주세요.'],
['A debate is already running. You can follow it in the current record.','이미 토론이 진행 중입니다. 현재 기록에서 확인할 수 있습니다.'],
['This debate cannot be restarted in its current state.','이 토론은 현재 상태에서 다시 시작할 수 없습니다.'],
['Verification is on hold because the required evidence is too large. Posted turns are kept.','필수 근거의 분량이 커 검증이 보류됐습니다. 게시된 발언은 보존됩니다.'],
['You can ask after the current response finishes or the conversation pauses.','현재 응답이 끝나거나 대화가 정지한 뒤 질문할 수 있습니다.'],
['The AI usage limit has been reached. You can still read conversations and save directly.','현재 AI 사용 한도에 도달했습니다. 기존 대화 읽기와 직접 저장은 가능합니다.'],
['This AI session window has ended. You can still read and save directly.','이번 AI 실행 시간이 끝났습니다. 읽기와 직접 저장은 가능합니다.'],
['AI processing was interrupted and needs a check. Existing records are kept.','AI 처리가 중단돼 확인이 필요합니다. 기존 기록은 보존됩니다.'],
['The source material has expired.','근거 자료의 사용 기한이 지났습니다.'],['The session has expired. Please start again.','세션 기한이 지났습니다. 새로 시작해 주세요.'],
['Choose at least one perspective to talk with.','대화할 수 있는 관점을 하나 이상 선택해 주세요.'],['This conversation reached its turn limit.','이 대화의 발화 한도에 도달했습니다.'],
['You can choose up to 24 related messages.','관련 대화는 최대 24개까지 선택할 수 있습니다.'],['Another task is in progress. Please try again shortly.','다른 작업을 처리하고 있습니다. 잠시 뒤 다시 눌러 주세요.'],
['The AI response could not be completed. Your input and records are kept.','AI 응답을 완료하지 못했습니다. 입력과 기존 기록은 보존됐습니다.'],
['The request could not be completed. Check your input and earlier records.','요청을 완료하지 못했습니다. 입력과 이전 기록을 확인해 주세요.'],
['Consensus Agent','합의 Agent'],['The task is still running. Check it in the conversation status.','작업이 아직 진행 중입니다. 대화 상태에서 확인해 주세요.'],
['No perspectives with checked evidence yet. You can still write your view in Reflect.','근거를 확인한 관점이 아직 없습니다. 나의 의견은 Reflect에서 정리할 수 있습니다.'],
['External source','외부 자료'],['Source','원문'],['Not started','시작 전'],['Running','진행 중'],['Pausing','정지 중'],['Paused','일시 정지'],['Waiting for a question','질문 대기'],
['Opening statements','입장 발언'],['Replying to other views','상대 입장에 응답 중'],['Reviewing consensus','합의 검토 중'],['Compiling the conclusion','결론 정리 중'],['Completed','완료'],
['No consensus','합의 없음'],['No shared claim proposed','공통 주장 제안 없음'],['Verification on hold','검증 보류'],['Incomplete response','응답 불완전'],['Run failed','실행 실패'],
['Cancelled','중단'],['Ended','종료'],['Ending','종료 중'],['Some responses failed','일부 응답 실패'],['Limit reached','한도 도달'],['Needs a check','확인 필요'],
['Consensus Agent chat','합의 Agent 대화'],['Automatic debate','자동 토론'],['Reply to another view','상대 입장 응답'],['Responding to','응답 대상'],['Debate conclusion','토론 결론'],
['Accepted by','수락한 관점'],['Condition','조건'],['Saved','저장했습니다.'],['Comment evidence','댓글 근거'],['AI inference · not the original author’s words','AI 추론 · 원작성자의 발언이 아닙니다'],
['Claim based on external sources','외부 자료 기반 주장'],['Premises and conditions to check together','함께 확인할 전제·조건'],
['No evidence in the material answers this question.','이 질문에 답할 근거를 자료에서 찾지 못했습니다.'],
['The requested answer could not be confirmed, so the limits of the material are explained.','요청한 답을 확인할 수 없어 자료의 한계를 설명합니다.'],
['Further explanation could not be confirmed, so only what can be confirmed is shown.','추가 설명을 확인하지 못해, 확인할 수 있는 내용만 표시했습니다.'],
['A shared claim accepted by every participating perspective.','모든 참가 관점이 수락한 공통 주장입니다.'],
['No shared claim was accepted by everyone. You can review the disagreements and turns below.','전원이 수락한 공동 주장이 없습니다. 아래 이견과 발언을 확인할 수 있습니다.'],
['No shared claim candidate was proposed for this question. Compare the perspectives through their turns.','이번 질문에서 공동 주장 후보를 제시하지 못했습니다. 발언을 보며 각 관점을 비교해 보세요.'],
['The evidence or acceptance of the shared claim could not be confirmed. Verified turns remain above.','공통 주장의 근거나 수락을 확인하지 못했습니다. 검증된 발언은 위에 남아 있습니다.'],
['Some responses did not fully address the question or the other turns.','일부 응답이 질문이나 상대 발언을 충분히 다루지 못했습니다.'],
['The debate could not be completed. Posted turns are kept.','토론을 완료하지 못했습니다. 게시된 발언은 보존됩니다.'],
['The AI run limit was reached. Posted turns are kept.','AI 실행 한도에 도달했습니다. 게시된 발언은 보존됩니다.'],
['The run status needs a check. Posted turns are kept.','실행 상태를 확인해야 합니다. 게시된 발언은 보존됩니다.'],
['You can review the posted turns of this debate.','이 토론의 게시된 발언을 확인할 수 있습니다.'],['Disagreements and conditional replies','이견과 조건부 응답'],
['Not accepted','수락하지 않음'],['Asked to add a condition','조건 보완 요청'],['Opposed','반대'],['Conditional reply','조건부 응답'],['Disagreement','이견'],
['Not yet answered','아직 답하지 못한 내용'],['Insufficient answer to the question','질문에 대한 응답 부족'],
['Answers using the claims and conditions accepted by the participating perspectives.','참가 관점이 수락한 주장과 조건을 바탕으로 질문에 답합니다.'],
['Lineage source','계보 원문'],['Ask the Consensus Agent','합의 Agent에 질문하기'],['Read each perspective’s position and replies, then check the conclusion.','관점별 입장과 응답을 읽고 마지막 결론을 확인하세요.'],
['You can ask about the shared claim and its conditions.','공통 주장과 조건에 대해 질문할 수 있습니다.'],['You can start with a question.','질문으로 시작할 수 있습니다.'],
['A perspective is responding.','관점이 응답하고 있습니다.'],['Each perspective is explaining its position.','각 관점이 입장을 설명하고 있습니다.'],
['Replying to another perspective’s turn.','다른 관점의 발언에 답하고 있습니다.'],['Reviewing shared claims and disagreements.','공통 주장과 이견을 검토하고 있습니다.'],
['Compiling the debate conclusion.','토론 결론을 정리하고 있습니다.'],['Stops after the current response.','현재 응답 뒤에 멈춥니다.'],
['Paused. You can continue the debate.','잠시 멈췄습니다. 토론을 이어갈 수 있습니다.'],['Paused. You can ask or continue.','잠시 멈췄습니다. 질문하거나 이어갈 수 있습니다.'],
['The conversation ended. You can keep asking your own questions.','대화가 끝났습니다. 나의 질문을 이어갈 수 있습니다.'],['This conversation has ended.','종료한 대화입니다.'],
['Ends after the current step.','현재 처리를 마친 뒤 종료합니다.'],['Some responses could not be completed. Earlier turns are kept.','일부 응답을 완료하지 못했습니다. 이전 발언은 보존됩니다.'],
['The conversation limit has been reached.','대화 한도에 도달했습니다.'],['The processing status needs a check.','처리 상태 확인이 필요합니다.'],
['Which issue should they debate?','어떤 쟁점을 토론할까요?'],['Start automatic debate','자동 토론 시작'],['You cannot send a new question to the Consensus Agent right now.','지금은 합의 Agent에 새 질문을 보낼 수 없습니다.'],
['No evidence','근거 없음'],['Related conversations','관련 대화'],['Reflection saved with an earlier view','이전 의견으로 저장한 성찰'],['Saved reflection','저장한 성찰'],
['You can edit this saved version. Earlier versions are kept.','이 저장본을 수정할 수 있습니다. 이전 저장본은 보존됩니다.'],['View reflection · version','성찰 보기 · 저장본'],
['Could not load the recent conversation. Reopen it from the Converse list.','최근 대화를 불러오지 못했습니다. Converse의 대화 목록에서 다시 열어 주세요.'],
['Enter a question to start.','시작할 질문을 입력해 주세요.'],['Keep the question within 1,000 characters.','질문은 1,000자 이내로 입력해 주세요.'],
['Summarizing your view and the selected conversations.','나의 의견과 선택한 대화를 정리하고 있습니다.'],['Your view changed. Analyze again with the current view.','의견이 변경됐습니다. 현재 의견으로 다시 분석해 주세요.'],
['Choose what you need from the suggestions, or edit them yourself, then save.','제안에서 필요한 내용을 선택하거나 직접 수정해 저장해 주세요.'],
['Could not load earlier records. Refresh in a moment and try again.','기존 기록을 불러오지 못했습니다. 잠시 뒤 새로고침해 다시 시도해 주세요.'],
['The previous session has expired. Please start again.','이전 세션 기한이 지났습니다. 새로 시작해 주세요.'],
['The earlier record cannot be opened. Choose an analysis or another record in Library.','이전 기록을 열 수 없습니다. Library에서 분석이나 다른 기록을 선택하세요.'],
['No analysis is available yet.','아직 사용할 수 있는 분석이 없습니다.'],['The selected analysis cannot be opened now. Check the currently selected video.','선택한 분석은 지금 열 수 없습니다. 현재 선택된 영상을 확인하세요.'],
['Choose a perspective to talk with first.','대화할 관점을 먼저 선택해 주세요.'],['You can choose up to three perspectives in one conversation.','한 대화에서 최대 세 관점을 선택할 수 있습니다.'],
['Parent comment · context only','부모 댓글 · 문맥 참고'],['Display and notifications','화면과 알림'],
];
// Text built from numbers or names: [English pattern, English→Korean, Korean pattern, Korean→English].
const I18N_PATTERNS=[
[/^Perspective (\d+)$/,m=>'관점 '+m[1],/^관점 (\d+)$/,m=>'Perspective '+m[1]],
[/^(\d+) perspectives? from (\d+) (registered source|processed) comments(.*)$/,m=>'댓글 '+m[2]+'개에서 찾은 관점 '+m[1]+'개'+m[4].replace(/ · Original population: (\d+) comments\./,' · 원래 댓글 수: $1개').replace(/^\.$/,''),
 /^댓글 (\d+)개에서 찾은 관점 (\d+)개(.*)$/,m=>m[2]+' perspectives from '+m[1]+' processed comments'+(m[3]?m[3].replace(/ · 원래 댓글 수: (\d+)개/,' · Original population: $1 comments.'):'.')],
[/^(\d+) (verified )?source comments?$/,m=>(m[2]?'검증된 ':'')+'원댓글 '+m[1]+'개',/^(검증된 )?원댓글 (\d+)개$/,m=>m[2]+(m[1]?' verified':'')+' source comments'],
[/^Comparing your view with (\d+) perspectives?…$/,m=>'관점 '+m[1]+'개와 나의 의견을 비교하는 중…',/^관점 (\d+)개와 나의 의견을 비교하는 중…$/,m=>'Comparing your view with '+m[1]+' perspectives…'],
[/^(\d+) of (\d+) analyzed comments are linked to a perspective\.$/,m=>'분석한 댓글 '+m[2]+'개 중 '+m[1]+'개가 관점에 연결되어 있습니다.',/^분석한 댓글 (\d+)개 중 (\d+)개가 관점에 연결되어 있습니다\.$/,m=>m[2]+' of '+m[1]+' analyzed comments are linked to a perspective.'],
[/^Characters: (\d+) \/ (\d+)$/,m=>'글자 수: '+m[1]+' / '+m[2],/^글자 수: (\d+) \/ (\d+)$/,m=>'Characters: '+m[1]+' / '+m[2]],
[/^(\d+) comments$/,m=>'댓글 '+m[1]+'개',/^댓글 (\d+)개$/,m=>m[1]+' comments'],
[/^(\d+) \(([\d.]+%)\)$/,m=>m[1]+'개 ('+m[2]+')',/^(\d+)개 \(([\d.]+%)\)$/,m=>m[1]+' ('+m[2]+')'],
[/^Compare (.+) with your view$/,m=>translate(m[1])+'을(를) 나의 의견과 비교',/^(.+)을\(를\) 나의 의견과 비교$/,m=>'Compare '+translate(m[1])+' with your view'],
[/^(.+)의 앞선 발언에 대한 응답$/,null,/^(.+)의 앞선 발언에 대한 응답$/,m=>'Reply to an earlier turn by '+translate(m[1])],
[/^(.+)의 근거 발언$/,null,/^(.+)의 근거 발언$/,m=>'Evidence turn from '+translate(m[1])],
[/^저장했습니다\. (\d+)번째 저장본$/,null,/^저장했습니다\. (\d+)번째 저장본$/,m=>'Saved. Version '+m[1]],
[/^(.+?) (\d+)$/,m=>{const head=translate(m[1]);return head!==m[1]?head+' '+m[2]:null;},/^(.+?) (\d+)$/,m=>{const head=translate(m[1]);return head!==m[1]?head+' '+m[2]:null;}],
];
const i18nMaps={ko:new Map(),en:new Map()};
for(const [en,ko] of I18N_PAIRS){if(!i18nMaps.ko.has(en))i18nMaps.ko.set(en,ko);if(!i18nMaps.en.has(ko))i18nMaps.en.set(ko,en);}
const langKey='commentscope-lang';
let currentLang=(()=>{try{return localStorage.getItem(langKey)==='ko'?'ko':'en';}catch(_){return 'en';}})();
function translate(text){
  const map=i18nMaps[currentLang];if(map.has(text))return map.get(text);
  for(const [enRe,toKo,koRe,toEn] of I18N_PATTERNS){
    const re=currentLang==='ko'?enRe:koRe,fn=currentLang==='ko'?toKo:toEn;if(!fn)continue;
    const m=text.match(re);if(m){const value=fn(m);if(value!=null)return value;}
  }
  // "A · B" labels translate part by part.
  if(text.includes(' · ')){const parts=text.split(' · '),out=parts.map(translateOnce);if(out.some((p,i)=>p!==parts[i]))return out.join(' · ');}
  return text;
}
function translateOnce(text){const t=text.trim();if(!t)return text;const v=translate(t);return v===t?text:text.replace(t,v);}
const i18nSkip='textarea,script,style,[data-no-i18n],.comment-text,.card-stance,.relation-summary,.detail-quote,#initial-peek-text,#comparison-initial,#comparison-stance,.bubble,#source,.opinion-copy';
function translateTree(root){
  if(root.nodeType===Node.TEXT_NODE){const el=root.parentElement;if(el&&!el.closest(i18nSkip)){const v=translateOnce(root.nodeValue);if(v!==root.nodeValue)root.nodeValue=v;}return;}
  if(root.nodeType!==Node.ELEMENT_NODE||root.closest(i18nSkip))return;
  for(const el of [root,...root.querySelectorAll('[placeholder],[aria-label],[title]')]){
    if(el.closest(i18nSkip))continue;
    for(const attr of ['placeholder','aria-label','title'])if(el.hasAttribute(attr)){const v=translateOnce(el.getAttribute(attr));if(v!==el.getAttribute(attr))el.setAttribute(attr,v);}
  }
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);const texts=[];while(walker.nextNode())texts.push(walker.currentNode);
  for(const node of texts)translateTree(node);
}
function applyLanguage(lang){
  currentLang=lang==='ko'?'ko':'en';try{localStorage.setItem(langKey,currentLang);}catch(_){}
  document.documentElement.lang=currentLang;document.title=translate(document.title);translateTree(document.body);
  for(const b of document.querySelectorAll('[data-lang]')){const on=b.dataset.lang===currentLang;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));}
}
new MutationObserver(records=>{for(const r of records){if(r.type==='characterData')translateTree(r.target);else for(const n of r.addedNodes)translateTree(n);}})
  .observe(document.body,{subtree:true,childList:true,characterData:true});
for(const b of document.querySelectorAll('[data-lang]'))b.onclick=()=>applyLanguage(b.dataset.lang);
applyLanguage(currentLang);

start().catch(error=>status(error.message)).finally(()=>{$('open-video-url').disabled=false;});
