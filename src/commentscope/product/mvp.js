'use strict';
const $ = id => document.getElementById(id);
const categories = {stayed:'What stayed the same', changed:'What changed', newly_learned:'Newly learned', worth_more_thought:'Worth more thought'};
const state = {analysis:null, session:null, token:'', room:null, roomTimer:null, selected:new Set(), context:new Set(), comparisons:new Map(), reflectionJob:null, reflectionResult:null, saved:null, roomFilter:'all', openingPending:false};
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const requestId = () => crypto.randomUUID();
const savedSessionKey = 'commentscope-mvp-session';
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function asset(name) { const img=node('img'); img.src='/mvp/assets/'+name+'.svg'; img.alt=''; return img; }
function status(text) { $('status').textContent=text; }
function errorText(code) { return ({revision_conflict:'내용이 갱신됐습니다. 최신 화면을 확인한 뒤 다시 눌러 주세요.',opinion_revision_conflict:'의견이 갱신됐습니다. 다시 확인해 주세요.',analysis_revision_conflict:'의견 또는 분석 버전이 달라졌습니다. 제안을 다시 확인하거나 직접 저장해 주세요.',resource_busy:'이미 토론이 진행 중입니다. 현재 기록에서 확인할 수 있습니다.',debate_not_ready:'이 토론은 현재 상태에서 다시 시작할 수 없습니다.',capacity_hold:'필수 근거의 분량이 커 검증이 보류됐습니다. 게시된 발언은 보존됩니다.',room_not_ready:'현재 응답이 끝나거나 대화가 정지한 뒤 질문할 수 있습니다.',budget_exhausted:'현재 AI 사용 한도에 도달했습니다. 기존 대화 읽기와 직접 저장은 가능합니다.',cycle_deadline:'이번 AI 실행 시간이 끝났습니다. 읽기와 직접 저장은 가능합니다.',reconcile_required:'AI 처리가 중단돼 확인이 필요합니다. 기존 기록은 보존됩니다.',source_expired:'근거 자료의 사용 기한이 지났습니다.',session_expired:'세션 기한이 지났습니다. 새로 시작해 주세요.',invalid_participants:'대화할 수 있는 관점을 하나 이상 선택해 주세요.',turn_limit:'이 대화의 발화 한도에 도달했습니다.',context_capacity:'관련 대화는 최대 24개까지 선택할 수 있습니다.',queue_capacity:'다른 작업을 처리하고 있습니다. 잠시 뒤 다시 눌러 주세요.',model_or_validation_failed:'AI 응답을 완료하지 못했습니다. 입력과 기존 기록은 보존됐습니다.'})[code] || '요청을 완료하지 못했습니다. 입력과 이전 기록을 확인해 주세요.'; }
async function api(path, method='GET', body) {
  const headers={}; if(state.token)headers['X-Session-Token']=state.token;
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
  if(step==='converse'&&!state.room){if(state.session.rooms.length){chooseRoom(state.session.rooms[0].room_id).catch(e=>status(e.message));return;}step='explore';status('대화할 관점을 먼저 선택해 주세요.');}
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
  $('initial-edit').value=session.initial_opinion.text;
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
  $('analysis-state').textContent=a.quality_gate_passed?'':'Development analysis · quality review pending';
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
  $('composition-chart').replaceChildren();$('composition-legend').replaceChildren();
  if(!total){$('composition-chart').append(node('p','Comment composition is not available.','muted'));return;}
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1000 26');svg.setAttribute('role','img');svg.setAttribute('aria-label','Exclusive comment composition');
  let x=0;
  for(const e of entries){if(!e.count)continue;const i=indexOf(e.perspective_id),cls=e.perspective_id?'accent-'+Math.max(0,i)%5:e.kind,percent=e.count/total*100;
    const rect=document.createElementNS(ns,'rect');rect.setAttribute('x',String(x));rect.setAttribute('y','0');rect.setAttribute('width',String(percent*10));rect.setAttribute('height','26');rect.setAttribute('class','chart-'+(e.perspective_id?Math.max(0,i)%5:e.kind));const title=document.createElementNS(ns,'title');title.textContent=e.count+' comments';rect.append(title);svg.append(rect);x+=percent*10;
    const line=node('span',undefined,cls);line.append(node('i',undefined,'legend-dot'),node('span',(e.perspective_id?label(e.perspective_id):e.kind==='multiple'?'Multiple perspectives':'Other comments')+' · '+e.count+' ('+percent.toFixed(1)+'%)'));$('composition-legend').append(line);
  }
  $('composition-chart').append(svg);
}
function supportsDebate(count){return count>=2&&state.session.capabilities?.structured_debate;}
function updateSelection(){
  const count=state.selected.size;
  const mode=count===1?'Start a 1:1 conversation.':supportsDebate(count)?'Start an automatic debate.':'Start a group conversation.';
  $('selection-hint').textContent=count?count+' selected · '+mode:'Choose one perspective for a 1:1 conversation, or up to three for a group.';
  $('open-room').disabled=!count;
}
function renderPerspectives(){
  $('perspectives').replaceChildren();
  if(!state.analysis.perspectives.length){
    $('perspectives').append(node('p','근거를 확인한 관점이 아직 없습니다. 나의 의견은 Reflect에서 정리할 수 있습니다.','muted'));
  }
  for(const p of state.analysis.perspectives){
    const card=node('article',undefined,'card accent-'+indexOf(p.id)%5);card.classList.toggle('selected',state.selected.has(p.id));
    const top=node('header'),choice=node('label',undefined,'card-select'),check=node('input');check.type='checkbox';check.checked=state.selected.has(p.id);check.setAttribute('aria-label','Select '+label(p.id));
    check.onchange=()=>{if(check.checked){if(state.selected.size>=3){check.checked=false;status('한 대화에서 최대 세 관점을 선택할 수 있습니다.');return;}state.selected.add(p.id);}else state.selected.delete(p.id);card.classList.toggle('selected',check.checked);updateSelection();};
    choice.append(check,node('span','✓'));top.append(avatar(p.id),choice);
    const title=node('div',undefined,'card-title'),count=node('span',p.source_count+(p.admission_policy?' verified source comments':' source comments'),'source-badge');title.append(node('strong',label(p.id)),node('small','A viewpoint from the comments'));top.append(title);
    if(p.admission_policy)card.append(node('small','댓글에 나타난 입장입니다. 전체 시청자의 비율을 뜻하지 않습니다.'));
    card.append(top,count,node('p','STANCE','card-section-label'),node('p',p.text,'card-stance'));
    const stanceSources=node('div',undefined,'card-sources');
    commentSourceButtons(stanceSources,p.source_ids||[],'입장 원문');
    if(stanceSources.childElementCount)card.append(stanceSources);
    const grounds=p.grounds||[];
    if(grounds.length){
      card.append(node('p','REASONS & CONDITIONS IN THE SOURCES','card-section-label'));
      for(const g of grounds){
        const row=node('p',undefined,'card-ground');
        row.append(node('span',g.role==='essential_condition'?'Condition: ':g.role==='concession'?'Qualification: ':''),
          node('span',g.text),node('small',' · '+g.source_count+' source'+(g.source_count===1?'':'s'),'ground-count'));
        const sources=node('span',undefined,'card-ground-sources');
        commentSourceButtons(sources,g.source_ids||[],'근거 원문');
        if(sources.childElementCount)row.append(sources);
        card.append(row);
      }
    }
    const compare=node('button','Compare with my view','secondary compare-button');compare.type='button';compare.onclick=async()=>{compare.disabled=true;try{await compareWith(p.id);}catch(e){status(e.message);}finally{compare.disabled=false;}};
    card.append(compare);$('perspectives').append(card);
  }
  updateSelection();
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
async function compareWith(pid){
  status('나의 의견과 관점을 비교하고 있습니다.');const key=state.session.initial_opinion.revision+':'+pid;
  let value=state.comparisons.get(key);if(!value){value=await api(base()+'/comparisons','POST',{perspective_id:pid,initial_revision:state.session.initial_opinion.revision,request_id:requestId()});state.comparisons.set(key,value);}
  const job=await pollJob(value);if(job.stale){status('초기 의견이 바뀌어 이전 비교가 됐습니다. 현재 의견으로 다시 비교해 주세요.');return;}
  $('comparison').className='comparison-modal accent-'+indexOf(pid)%5;$('comparison-avatar').replaceChildren(avatar(pid));$('comparison-title').textContent=label(pid);$('comparison-stance').textContent=perspective(pid).text;
  $('comparison-items').replaceChildren();highlighted($('comparison-initial'),state.session.initial_opinion.text,(job.result.items||[]).flatMap(i=>i.user_spans.map(s=>({...s,category:i.relation}))));
  if(!job.result.available)$('comparison-items').append(node('p','초기 의견을 적으면 이 관점과 비교할 수 있습니다.'));
  else{
    const names={agreement:'Where your views align',difference:'Where your views differ',additional_condition:'A condition to consider',unclear:'Something to clarify'};
    for(const item of job.result.items){const row=node('article',undefined,'comparison-item '+item.relation);row.append(node('h3',names[item.relation]),node('p',item.explanation),node('blockquote','Your view: '+item.user_spans.map(s=>s.text).join(' ')));
      for(const claim of [...item.perspective_claims,...item.required_premises]){row.append(node('blockquote',claim.text));sourceButtons(row,claim);}
      if(item.consideration_question)row.append(node('p',item.consideration_question,'comparison-question'));$('comparison-items').append(row);
    }
    if(!job.result.items.length)$('comparison-items').append(node('p','두 입력에서 분명한 공통점이나 차이를 확인하지 못했습니다.'));
  }
  openDialog('comparison');status('비교 제안을 확인했습니다. 관점의 원문도 함께 살펴보세요.');
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
  setRoom(room);
  await refreshRoom();
  if(state.room?.room_id===id)showStep('converse');
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
function renderSaved(){
  const list=$('saved-reflections');list.replaceChildren();
  for(const item of state.session.reflections){const button=node('button','성찰 보기 · 저장본 '+item.revision,'secondary');button.type='button';button.onclick=async()=>{try{const value=await api(base()+'/reflections/'+item.reflection_id);state.saved=value;clearInsights();const view=$('saved-view');view.replaceChildren(node('h3',value.stale?'이전 의견으로 저장한 성찰':'저장한 성찰'));
      for(const [key,title] of Object.entries(categories)){view.append(node('h3',title));$(key).value=value.user_items[key].map(i=>i.text).join('\n');for(const entry of value.user_items[key]){view.append(node('p',entry.text));for(const mid of entry.related_message_ids){const link=node('button','관련 대화','source-button');link.type='button';link.onclick=()=>jumpTo(mid,value.context_message_refs).catch(e=>status(e.message));view.append(link);}}}$('reflection-save-panel').open=true;$('save-state').textContent='이 저장본을 수정할 수 있습니다. 이전 저장본은 보존됩니다.';}catch(e){status(e.message);}};list.append(button);}
}
async function enter(session){
  setSession(session);
  state.analysis=session.analysis;
  renderAnalysis();
  $('before').hidden=true;
  $('workspace').hidden=false;
  renderPerspectives();
  const last=JSON.parse(sessionStorage.getItem(lastRoomKey)||'null');
  if(last?.session_id===session.session_id&&session.rooms.some(room=>room.room_id===last.room_id)){
    try{
      await chooseRoom(last.room_id);
      status('');
    }catch(error){
      setRoom(null);
      showStep('explore');
      status('최근 대화를 불러오지 못했습니다. Converse의 대화 목록에서 다시 열어 주세요.');
    }
    return;
  }
  showStep('explore');
  status('관점을 선택하고 나의 의견과 비교해 보세요.');
}
$('initial').oninput=()=>{$('initial-count').textContent='Characters: '+[...$('initial').value].length+' / 500';};
$('clear-initial').onclick=()=>{$('initial').value='';$('initial').oninput();$('initial').focus();};
$('begin').onsubmit=async event=>{
  event.preventDefault();
  const button=$('begin').querySelector('button[type=submit]');
  if(button.disabled)return;
  button.disabled=true;
  const bytes=crypto.getRandomValues(new Uint8Array(32));
  state.token=btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  try{
    const session=await api('/sessions','POST',{analysis_id:state.analysis.analysis_id,
      bundle_revision:state.analysis.bundle_revision,initial_opinion:$('initial').value,request_id:requestId()});
    localStorage.setItem(savedSessionKey,JSON.stringify({token:state.token,session_id:session.session_id}));
    await enter(session);
  }catch(error){status(error.message);}
  finally{button.disabled=false;}
};
$('edit-initial').onsubmit=async event=>{event.preventDefault();try{await api(base()+'/opinions/initial','PUT',{text:$('initial-edit').value,expected_revision:state.session.initial_opinion.revision,request_id:requestId()});state.comparisons.clear();clearInsights();closeDialog('comparison');await refreshSession();status('초기 의견을 수정했습니다. 현재 의견으로 새 비교를 볼 수 있습니다.');}catch(e){status(e.message);}};
$('open-room').onclick=async()=>{
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
$('comparison').addEventListener('close',()=>{$('comparison').hidden=true;});
$('go-reflect').onclick=()=>showStep('reflect');document.querySelectorAll('button[data-step]').forEach(button=>button.onclick=()=>showStep(button.dataset.step));
$('edit-current').onclick=()=>{clearInsights();$('current').focus();};
$('write-manually').onclick=()=>{$('reflection-save-panel').open=true;$('stayed').focus();};
$('analyze').onclick=async()=>{const button=$('analyze');button.disabled=true;try{await saveCurrent();status('나의 의견과 선택한 대화를 정리하고 있습니다.');const value=await api(base()+'/reflection-analyses','POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,context_message_ids:[...state.context],request_id:requestId()});const job=await pollJob(value);if(job.stale){status('의견이 변경됐습니다. 현재 의견으로 다시 분석해 주세요.');return;}state.reflectionJob=job.job_id;state.reflectionResult=job.result;renderSuggestions(job.result);status('제안에서 필요한 내용을 선택하거나 직접 수정해 저장해 주세요.');}catch(e){status(e.message);}finally{button.disabled=false;}};
$('save-reflection').onsubmit=async event=>{event.preventDefault();try{await saveCurrent();const user_items={};for(const key of Object.keys(categories)){const values=$(key).value.split('\n').filter(s=>s.trim());user_items[key]=values.map(value=>{const savedMatches=state.saved&&['initial','current'].every(kind=>state.saved[kind+'_revision']===state.session[kind+'_opinion'].revision);const original=state.reflectionResult?.categories[key].find(i=>i.explanation===value)||(savedMatches?state.saved.user_items[key].find(i=>i.text===value):null);return {text:value,initial_span_ids:original?.initial_span_ids||[],current_span_ids:original?.current_span_ids||[],related_message_ids:original?.related_message_ids||[]};});}const path=base()+'/reflections'+(state.saved?'/'+state.saved.reflection_id:'');const value=await api(path,state.saved?'PUT':'POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,analysis_job_id:state.reflectionJob,user_items,expected_revision:state.saved?.revision||0,request_id:requestId()});state.saved=value;$('save-state').textContent='저장했습니다. '+value.revision+'번째 저장본';await refreshSession();}catch(e){status(e.message);}};
$('new-session').onclick=()=>{clearTimeout(state.roomTimer);localStorage.removeItem(savedSessionKey);sessionStorage.removeItem(lastRoomKey);location.reload();};

async function start(){
  const previous=localStorage.getItem(savedSessionKey);
  let resumeMessage='';
  if(previous){
    const saved=JSON.parse(previous);
    state.token=saved.token;
    let session;
    try{
      session=await api('/sessions/'+encodeURIComponent(saved.session_id));
    }catch(error){
      if(!['session_expired','session_token_required','resource_missing'].includes(error.code)){
        status('기존 기록을 불러오지 못했습니다. 잠시 뒤 새로고침해 다시 시도해 주세요.');
        return;
      }
      localStorage.removeItem(savedSessionKey);
      sessionStorage.removeItem(lastRoomKey);
      state.token='';
      resumeMessage=error.code==='session_expired'
        ? '이전 세션 기한이 지났습니다. 새로 시작해 주세요.'
        : '이전 세션을 찾을 수 없습니다. 새로 시작해 주세요.';
    }
    if(session){await enter(session);return;}
  }
  const available=await api('/analyses');
  state.analysis=available.analyses.find(a=>a.status==='experimental'||a.status==='available');
  if(!state.analysis){status('아직 사용할 수 있는 분석이 없습니다.');return;}
  renderAnalysis();
  $('begin').querySelector('button[type=submit]').disabled=false;
  status(resumeMessage||'먼저 나의 초기 의견을 적어 주세요. 비워 두고 관점을 살펴봐도 됩니다.');
}

start().catch(error=>status(error.message));
