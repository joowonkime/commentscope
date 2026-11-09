'use strict';
const $ = id => document.getElementById(id);
const categories = {stayed:'What stayed the same', changed:'What changed', newly_learned:'Newly learned', worth_more_thought:'Worth more thought'};
const state = {analysis:null, session:null, token:'', room:null, roomTimer:null, selected:new Set(), context:new Set(), comparisons:new Map(), reflectionJob:null, reflectionResult:null, saved:null, roomFilter:'all'};
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const requestId = () => crypto.randomUUID();
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function asset(name) { const img=node('img'); img.src='/mvp/assets/'+name+'.svg'; img.alt=''; return img; }
function status(text) { $('status').textContent=text; }
function errorText(code) { return ({revision_conflict:'내용이 갱신됐습니다. 최신 화면을 확인한 뒤 다시 눌러 주세요.',opinion_revision_conflict:'의견이 갱신됐습니다. 다시 확인해 주세요.',analysis_revision_conflict:'의견 또는 분석 버전이 달라졌습니다. 제안을 다시 확인하거나 직접 저장해 주세요.',room_not_ready:'현재 응답이 끝나거나 대화가 정지한 뒤 질문할 수 있습니다.',budget_exhausted:'현재 AI 사용 한도에 도달했습니다. 기존 대화 읽기와 직접 저장은 가능합니다.',cycle_deadline:'이번 AI 실행 시간이 끝났습니다. 읽기와 직접 저장은 가능합니다.',reconcile_required:'AI 처리가 중단돼 확인이 필요합니다. 기존 기록은 보존됩니다.',source_expired:'근거 자료의 사용 기한이 지났습니다.',session_expired:'세션 기한이 지났습니다. 새로 시작해 주세요.',invalid_participants:'대화할 수 있는 관점을 하나 이상 선택해 주세요.',turn_limit:'이 대화의 발화 한도에 도달했습니다.',context_capacity:'관련 대화는 최대 24개까지 선택할 수 있습니다.',queue_capacity:'다른 작업을 처리하고 있습니다. 잠시 뒤 다시 눌러 주세요.',model_or_validation_failed:'AI 응답을 완료하지 못했습니다. 입력과 기존 기록은 보존됐습니다.'})[code] || '요청을 완료하지 못했습니다. 입력과 이전 기록을 확인해 주세요.'; }
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
function label(id){const i=indexOf(id); return i<0?'Perspective':'Perspective '+(i+1);}
function avatar(id,small=false){const i=Math.max(0,indexOf(id)); return asset(small?'0385b':['4ea9b','5e642','baf01','d51bb','e77a2'][i%5]);}
function closeDialog(id){const dialog=$(id); if(dialog.open)dialog.close(); if(id==='comparison')dialog.hidden=true;}
function openDialog(id){const dialog=$(id); dialog.hidden=false; if(!dialog.open)dialog.showModal();}
function showStep(step){
  if(!state.session)return;
  if(step==='converse'&&!state.room){if(state.session.rooms.length){chooseRoom(state.session.rooms[0].room_id).catch(e=>status(e.message));return;}step='explore';status('대화할 관점을 먼저 선택해 주세요.');}
  for(const id of ['comparison','source-dialog','perspective-dialog'])closeDialog(id);
  for(const name of ['explore','converse','reflect'])$(name).hidden=name!==step;
  document.body.dataset.step=step;
  document.querySelectorAll('button[data-step]').forEach(b=>{b.classList.toggle('active',b.dataset.step===step); if(b.dataset.step===step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
  if(step==='reflect')refreshReflection().catch(e=>status(e.message));
}
async function pollJob(value){
  const end=Date.now()+300000;
  while(Date.now()<end){const job=await api('/jobs/'+value.job_id); if(!['queued','running'].includes(job.state)){if(job.state!=='succeeded')throw new Error(errorText(job.error?.code)); return job;} await wait(600);}
  throw new Error('작업이 아직 진행 중입니다. 대화 상태에서 확인해 주세요.');
}
async function refreshSession(){state.session=await api(base()); $('initial-edit').value=state.session.initial_opinion.text; renderRooms(); renderSaved();}
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
    play.onclick=()=>{const frame=node('iframe');frame.src='https://www.youtube-nocookie.com/embed/'+vid+'?autoplay=1';frame.title=title;frame.allow='autoplay; encrypted-media; picture-in-picture';frame.allowFullscreen=true;$('video-frame').replaceChildren(frame);};
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
function updateSelection(){const count=state.selected.size;$('selection-hint').textContent=count?count+' selected · '+(count===1?'Start a 1:1 conversation.':'Start a group conversation.'):'Choose one perspective for a 1:1 conversation, or up to three for a group.';$('open-room').disabled=!count;}
function renderPerspectives(){
  $('perspectives').replaceChildren();
  for(const p of state.analysis.perspectives){
    const card=node('article',undefined,'card accent-'+indexOf(p.id)%5);card.classList.toggle('selected',state.selected.has(p.id));
    const top=node('header'),choice=node('label',undefined,'card-select'),check=node('input');check.type='checkbox';check.checked=state.selected.has(p.id);check.setAttribute('aria-label','Select '+label(p.id));
    check.onchange=()=>{if(check.checked){if(state.selected.size>=3){check.checked=false;status('한 대화에서 최대 세 관점을 선택할 수 있습니다.');return;}state.selected.add(p.id);}else state.selected.delete(p.id);card.classList.toggle('selected',check.checked);updateSelection();};
    choice.append(check,node('span','✓'));top.append(avatar(p.id),choice);
    const title=node('div',undefined,'card-title'),count=node('span',p.source_count+' source comments','source-badge');title.append(node('strong',label(p.id)),node('small','A viewpoint from the comments'));top.append(title);
    card.append(top,count,node('p','STANCE','card-section-label'),node('p',p.text,'card-stance'));
    const grounds=p.grounds||[];
    if(grounds.length){card.append(node('p','REASONS & CONDITIONS IN THE SOURCES','card-section-label'));for(const g of grounds){const row=node('p',undefined,'card-ground');row.append(node('span',g.role==='essential_condition'?'Condition: ':g.role==='concession'?'Qualification: ':''),node('span',g.text),node('small',' · '+g.source_count+' source'+(g.source_count===1?'':'s'),'ground-count'));card.append(row);}}
    const compare=node('button','Compare with my view','secondary compare-button');compare.type='button';compare.onclick=async()=>{compare.disabled=true;try{await compareWith(p.id);}catch(e){status(e.message);}finally{compare.disabled=false;}};
    card.append(compare);$('perspectives').append(card);
  }
  updateSelection();
}
async function source(id){try{const value=await api(base()+'/sources/'+encodeURIComponent(id));$('source').textContent=value.text+(value.PARENT_CONTEXT_ONLY?'\n\n부모 댓글 · 문맥 참고\n'+value.PARENT_CONTEXT_ONLY.text:'');openDialog('source-dialog');}catch(e){status(e.message);}}
function sourceButtons(container,point){for(const [index,evidence] of (point.citations?.comment_evidence||[]).entries()){const b=node('button','원문 '+(index+1),'source-button');b.type='button';b.onclick=()=>source(evidence.source_id);container.append(b);}}
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
const roomStates={idle:'시작 전',running:'진행 중',pausing:'정지 중',paused:'일시 정지',awaiting_user:'질문 대기',closed:'종료',closing:'종료 중',error:'일부 응답 실패',exhausted:'한도 도달',needs_reconciliation:'확인 필요'};
function roomName(room,index){return(room.mode==='group'?'Group conversation ':'1:1 conversation ')+(index+1);}
async function chooseRoom(id){state.room={room_id:id};await refreshRoom();showStep('converse');}
function renderRooms(){
  const select=$('rooms'),list=$('room-list');select.replaceChildren(node('option','Choose a conversation'));select.firstChild.value='';list.replaceChildren();
  if(!state.session)return;
  const query=$('room-search').value.toLowerCase();
  state.session.rooms.forEach((room,i)=>{if(room.room_id===state.room?.room_id)room=state.room;const title=roomName(room,i),option=node('option',title+' · '+(roomStates[room.state]||room.state));option.value=room.room_id;select.append(option);
    if(state.roomFilter!=='all'&&room.mode!==state.roomFilter||!title.toLowerCase().includes(query))return;
    const button=node('button',undefined,'room-entry');button.type='button';button.classList.toggle('active',state.room?.room_id===room.room_id);button.append(node('strong',title),node('small',roomStates[room.state]||room.state));button.onclick=()=>chooseRoom(room.room_id).catch(e=>status(e.message));list.append(button);
  });
  if(!list.childNodes.length)list.append(node('p','No conversations here yet.','muted'));if(state.room)select.value=state.room.room_id;
}
function renderMessages(){
  $('messages').replaceChildren();
  for(const m of state.room.messages){const box=node('article',undefined,'message '+m.author_kind);box.id='message-'+m.message_id;
    if(m.author_kind==='agent'){const icon=node('div',undefined,'message-avatar');icon.append(avatar(m.agent_id,true));box.append(icon);}
    const bubble=node('div',undefined,'bubble');bubble.append(node('small',m.author_kind==='user'?'You':label(m.agent_id)));
    if(m.reply_to_message_id){const reply=state.room.messages.find(x=>x.message_id===m.reply_to_message_id);if(reply?.author_kind==='agent')bubble.append(node('small',label(reply.agent_id)+'의 앞선 발언에 대한 응답'));}
    if(m.body)bubble.append(node('p',m.body));
    if(m.author_kind==='agent'&&!m.points?.length)bubble.append(node('p',m.evidence_scope==='expired'?'근거 자료의 기한이 지났습니다.':'이 질문에 답할 근거를 자료에서 찾지 못했습니다.'));
    for(const point of m.points||[]){bubble.append(node('p',point.text));sourceButtons(bubble,point);}
    if(m.required_premises?.length){bubble.append(node('small','함께 확인할 전제·조건'));for(const point of m.required_premises){bubble.append(node('p',point.text));sourceButtons(bubble,point);}}
    box.append(bubble);$('messages').append(box);
  }
}
async function refreshRoom(){
  if(!state.room)return;clearTimeout(state.roomTimer);state.room=await api('/rooms/'+state.room.room_id);renderMessages();renderRooms();
  const ids=state.room.participant_ids||[];$('room-avatars').replaceChildren(...ids.map(id=>avatar(id)));
  $('room-title').textContent=ids.map(label).join(' × ')||'Your conversation';$('room-summary').textContent=state.room.mode==='group'?'Different perspectives, in one conversation.':'A conversation with this perspective.';
  const names={idle:'질문으로 시작할 수 있습니다.',running:'관점이 응답하고 있습니다.',pausing:'현재 응답 뒤에 멈춥니다.',paused:'잠시 멈췄습니다. 질문하거나 이어갈 수 있습니다.',awaiting_user:'대화가 끝났습니다. 나의 질문을 이어갈 수 있습니다.',closed:'종료한 대화입니다.',closing:'현재 처리를 마친 뒤 종료합니다.',error:'일부 응답을 완료하지 못했습니다. 이전 발언은 보존됩니다.',exhausted:'대화 한도에 도달했습니다.',needs_reconciliation:'처리 상태 확인이 필요합니다.'};
  $('room-state').textContent=(names[state.room.state]||state.room.state)+' · '+state.room.turn_count+'/18';
  $('opening').hidden=state.room.state!=='idle';$('pause').disabled=!['running','awaiting_user'].includes(state.room.state);$('resume').disabled=state.room.state!=='paused';$('next-round').disabled=!state.room.can_ask;$('close-room').disabled=state.room.state==='closed';
  $('interject').hidden=['idle','closed','closing','exhausted','needs_reconciliation','error'].includes(state.room.state);
  if(['running','pausing','closing'].includes(state.room.state))state.roomTimer=setTimeout(()=>refreshRoom().catch(e=>status(e.message)),700);
}
async function control(action){const rid=requestId();for(let attempt=0;attempt<3;attempt++){await refreshRoom();try{const result=await api('/rooms/'+state.room.room_id+'/control','POST',{action,expected_revision:state.room.revision,request_id:rid});await refreshRoom();return result;}catch(e){if(e.code!=='revision_conflict'||attempt===2)throw e;}}}
async function refreshReflection(){
  await refreshSession();$('initial-copy').textContent=state.session.initial_opinion.text;
  if(!$('current').value)$('current').value=state.session.current_opinion.revision?state.session.current_opinion.text:state.session.initial_opinion.text;
  $('reflection-rooms').replaceChildren();
  state.session.rooms.forEach((room,i)=>{const line=node('div',undefined,'reflection-room'),button=node('button',roomName(room,i)+' · '+(roomStates[room.state]||room.state));button.type='button';button.onclick=async()=>{state.room={room_id:room.room_id};await refreshReflection();};line.append(button);$('reflection-rooms').append(line);});
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
async function enter(){await refreshSession();state.analysis=state.session.analysis;renderAnalysis();$('before').hidden=true;$('workspace').hidden=false;renderPerspectives();showStep('explore');status('관점을 선택하고 나의 의견과 비교해 보세요.');}
$('initial').oninput=()=>{$('initial-count').textContent='Characters: '+[...$('initial').value].length+' / 500';};
$('clear-initial').onclick=()=>{$('initial').value='';$('initial').oninput();$('initial').focus();};
$('begin').onsubmit=async event=>{event.preventDefault();const button=$('begin').querySelector('button[type=submit]');button.disabled=true;const bytes=crypto.getRandomValues(new Uint8Array(32));state.token=btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');try{const value=await api('/sessions','POST',{analysis_id:state.analysis.analysis_id,bundle_revision:state.analysis.bundle_revision,initial_opinion:$('initial').value,request_id:requestId()});state.session=value;localStorage.setItem('commentscope-mvp-session',JSON.stringify({token:state.token,session_id:value.session_id}));await enter();}catch(e){status(e.message);}finally{button.disabled=false;}};
$('edit-initial').onsubmit=async event=>{event.preventDefault();try{await api(base()+'/opinions/initial','PUT',{text:$('initial-edit').value,expected_revision:state.session.initial_opinion.revision,request_id:requestId()});state.comparisons.clear();clearInsights();closeDialog('comparison');await refreshSession();status('초기 의견을 수정했습니다. 현재 의견으로 새 비교를 볼 수 있습니다.');}catch(e){status(e.message);}};
$('open-room').onclick=async()=>{const button=$('open-room');button.disabled=true;try{if(!state.selected.size)throw new Error('대화할 관점을 선택해 주세요.');const ids=[...state.selected];state.room=await api(base()+'/rooms','POST',{mode:ids.length===1?'one_to_one':'group',participant_ids:ids,initial_revision:state.session.initial_opinion.revision,request_id:requestId()});await refreshSession();await refreshRoom();showStep('converse');}catch(e){status(e.message);}finally{updateSelection();}};
$('rooms').onchange=()=>{if($('rooms').value)chooseRoom($('rooms').value).catch(e=>status(e.message));};
$('room-search').oninput=renderRooms;
document.querySelectorAll('[data-room-filter]').forEach(button=>button.onclick=()=>{state.roomFilter=button.dataset.roomFilter;document.querySelectorAll('[data-room-filter]').forEach(b=>b.classList.toggle('active',b===button));renderRooms();});
$('new-chat').onclick=()=>showStep('explore');
$('opening').onsubmit=async event=>{event.preventDefault();try{await api('/rooms/'+state.room.room_id+'/start','POST',{opening_question:$('opening-question').value,expected_revision:state.room.revision,request_id:requestId()});await refreshRoom();}catch(e){status(e.message);}};
for(const [id,action] of [['pause','pause'],['resume','resume'],['next-round','next_round'],['close-room','close']])$(id).onclick=()=>control(action).catch(e=>status(e.message));
$('interject').onsubmit=async event=>{event.preventDefault();try{await refreshRoom();if(state.room.state==='running')await control('pause');while(state.room.state==='pausing'){await wait(600);await refreshRoom();}await api('/rooms/'+state.room.room_id+'/messages','POST',{text:$('question').value,reply_to_message_id:null,expected_revision:state.room.revision,request_id:requestId()});$('question').value='';await refreshRoom();}catch(e){status(e.message);}};
document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{$('question').value=button.dataset.prompt;$('question').focus();});
$('agent-info').onclick=()=>{$('perspective-info').replaceChildren();for(const id of state.room?.participant_ids||[]){const p=perspective(id),entry=node('section',undefined,'perspective-info-entry');entry.append(node('h3',label(id)),node('p',p.text),node('small',p.source_count+' source comments'));$('perspective-info').append(entry);}openDialog('perspective-dialog');};
for(const [button,id] of [['close-comparison','comparison'],['close-source','source-dialog'],['close-perspective','perspective-dialog']])$(button).onclick=()=>closeDialog(id);
$('comparison').addEventListener('close',()=>{$('comparison').hidden=true;});
$('go-reflect').onclick=()=>showStep('reflect');document.querySelectorAll('button[data-step]').forEach(button=>button.onclick=()=>showStep(button.dataset.step));
$('edit-current').onclick=()=>{clearInsights();$('current').focus();};
$('write-manually').onclick=()=>{$('reflection-save-panel').open=true;$('stayed').focus();};
$('analyze').onclick=async()=>{const button=$('analyze');button.disabled=true;try{await saveCurrent();status('나의 의견과 선택한 대화를 정리하고 있습니다.');const value=await api(base()+'/reflection-analyses','POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,context_message_ids:[...state.context],request_id:requestId()});const job=await pollJob(value);if(job.stale){status('의견이 변경됐습니다. 현재 의견으로 다시 분석해 주세요.');return;}state.reflectionJob=job.job_id;state.reflectionResult=job.result;renderSuggestions(job.result);status('제안에서 필요한 내용을 선택하거나 직접 수정해 저장해 주세요.');}catch(e){status(e.message);}finally{button.disabled=false;}};
$('save-reflection').onsubmit=async event=>{event.preventDefault();try{await saveCurrent();const user_items={};for(const key of Object.keys(categories)){const values=$(key).value.split('\n').filter(s=>s.trim());user_items[key]=values.map(value=>{const savedMatches=state.saved&&['initial','current'].every(kind=>state.saved[kind+'_revision']===state.session[kind+'_opinion'].revision);const original=state.reflectionResult?.categories[key].find(i=>i.explanation===value)||(savedMatches?state.saved.user_items[key].find(i=>i.text===value):null);return {text:value,initial_span_ids:original?.initial_span_ids||[],current_span_ids:original?.current_span_ids||[],related_message_ids:original?.related_message_ids||[]};});}const path=base()+'/reflections'+(state.saved?'/'+state.saved.reflection_id:'');const value=await api(path,state.saved?'PUT':'POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,analysis_job_id:state.reflectionJob,user_items,expected_revision:state.saved?.revision||0,request_id:requestId()});state.saved=value;$('save-state').textContent='저장했습니다. '+value.revision+'번째 저장본';await refreshSession();}catch(e){status(e.message);}};
$('new-session').onclick=()=>{clearTimeout(state.roomTimer);localStorage.removeItem('commentscope-mvp-session');location.reload();};
(async()=>{try{const available=await api('/analyses');state.analysis=available.analyses.find(a=>a.status==='experimental'||a.status==='available');if(!state.analysis){status('아직 사용할 수 있는 분석이 없습니다.');$('begin').querySelector('button[type=submit]').disabled=true;return;}renderAnalysis();const previous=localStorage.getItem('commentscope-mvp-session');if(previous){const saved=JSON.parse(previous);state.token=saved.token;state.session={session_id:saved.session_id};try{await enter();return;}catch(_){localStorage.removeItem('commentscope-mvp-session');state.session=null;state.token='';}}status('먼저 나의 초기 의견을 적어 주세요. 비워 두고 관점을 살펴봐도 됩니다.');}catch(e){status(e.message);}})();
