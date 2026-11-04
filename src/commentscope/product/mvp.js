'use strict';
const $=id=>document.getElementById(id);
const categories={stayed:'유지한 생각',changed:'달라진 생각',newly_learned:'새로 알게 된 점',worth_more_thought:'더 생각해 볼 점'};
const state={analysis:null,session:null,token:'',room:null,roomTimer:null,selected:new Set(),context:new Set(),comparisons:new Map(),reflectionJob:null,reflectionResult:null,saved:null};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const requestId=()=>crypto.randomUUID();
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function status(text){$('status').textContent=text;}
function errorText(code){return ({revision_conflict:'내용이 갱신됐습니다. 최신 화면을 확인한 뒤 다시 눌러 주세요.',opinion_revision_conflict:'의견이 갱신됐습니다. 다시 확인해 주세요.',analysis_revision_conflict:'의견 또는 분석 버전이 달라졌습니다. 제안을 다시 확인하거나 직접 저장해 주세요.',room_not_ready:'현재 응답이 끝나거나 대화가 정지한 뒤 질문할 수 있습니다.',budget_exhausted:'현재 AI 사용 한도에 도달했습니다. 기존 대화 읽기와 직접 저장은 가능합니다.',cycle_deadline:'이번 AI 실행 시간이 끝났습니다. 읽기와 직접 저장은 가능합니다.',reconcile_required:'AI 처리가 중단돼 확인이 필요합니다. 기존 기록은 보존됩니다.',source_expired:'근거 자료의 사용 기한이 지났습니다.',session_expired:'세션 기한이 지났습니다. 새로 시작해 주세요.',invalid_participants:'대화할 수 있는 관점을 하나 이상 선택해 주세요.',turn_limit:'이 대화의 발화 한도에 도달했습니다.',context_capacity:'관련 대화는 최대 24개까지 선택할 수 있습니다.',queue_capacity:'다른 작업을 처리하고 있습니다. 잠시 뒤 다시 눌러 주세요.',model_or_validation_failed:'AI 응답을 완료하지 못했습니다. 입력과 기존 기록은 보존됐습니다.'})[code]||'요청을 완료하지 못했습니다. 입력과 이전 기록을 확인해 주세요.';}
async function api(path,method='GET',body){
  const headers={};if(state.token)headers['X-Session-Token']=state.token;
  if(body!==undefined)headers['Content-Type']='application/json';
  const response=await fetch('/api/v1'+path,{method,headers,...(body===undefined?{}:{body:JSON.stringify(body)})});
  const value=await response.json();
  if(!response.ok){const e=new Error(errorText(value.error?.code||value.error));e.code=value.error?.code||value.error;throw e;}
  return value;
}
function base(){return '/sessions/'+state.session.session_id;}
function perspective(id){return state.analysis.perspectives.find(p=>p.id===id);}
function label(id){const index=state.analysis.perspectives.findIndex(p=>p.id===id);return index<0?'관점':'관점 '+(index+1);}
function showStep(step){for(const name of ['explore','converse','reflect'])$(name).hidden=name!==step;document.querySelectorAll('[data-step]').forEach(b=>b.classList.toggle('active',b.dataset.step===step));if(step==='reflect')refreshReflection().catch(e=>status(e.message));}
async function pollJob(value){
  const end=Date.now()+300000;
  while(Date.now()<end){const job=await api('/jobs/'+value.job_id);if(!['queued','running'].includes(job.state)){if(job.state!=='succeeded')throw new Error(errorText(job.error?.code));return job;}await wait(600);}
  throw new Error('작업이 아직 진행 중입니다. 대화 상태에서 확인해 주세요.');
}
async function refreshSession(){state.session=await api(base());$('initial-edit').value=state.session.initial_opinion.text;renderRooms();renderSaved();}
function renderPerspectives(){
  $('perspectives').replaceChildren();
  for(const p of state.analysis.perspectives){
    const card=node('article',undefined,'card');card.classList.toggle('selected',state.selected.has(p.id));
    const top=node('header'),choice=node('label'),check=document.createElement('input');check.type='checkbox';check.checked=state.selected.has(p.id);
    check.onchange=()=>{if(check.checked){if(state.selected.size>=3){check.checked=false;return;}state.selected.add(p.id);}else state.selected.delete(p.id);card.classList.toggle('selected',check.checked);};
    choice.append(check,node('span',label(p.id)));top.append(choice);card.append(top,node('p',p.text),node('p','연결된 댓글 '+p.source_count+'개','meta'));
    const compare=node('button','내 의견과 비교','secondary');compare.onclick=async()=>{compare.disabled=true;try{await compareWith(p.id);}catch(e){status(e.message);}finally{compare.disabled=false;}};
    card.append(compare);$('perspectives').append(card);
  }
}
async function source(id){try{const value=await api(base()+'/sources/'+encodeURIComponent(id));$('source').textContent=value.text+(value.PARENT_CONTEXT_ONLY?'\n\n부모 댓글 · 문맥 참고\n'+value.PARENT_CONTEXT_ONLY.text:'');showStep('converse');}catch(e){status(e.message);}}
function sourceButtons(container,point){for(const [index,evidence] of (point.citations?.comment_evidence||[]).entries()){const b=node('button','원문 '+(index+1),'source-button');b.type='button';b.onclick=()=>source(evidence.source_id);container.append(b);}}
async function compareWith(pid){
  status('나의 의견과 관점을 비교하고 있습니다.');const key=state.session.initial_opinion.revision+':'+pid;
  let value=state.comparisons.get(key);
  if(!value){value=await api(base()+'/comparisons','POST',{perspective_id:pid,initial_revision:state.session.initial_opinion.revision,request_id:requestId()});state.comparisons.set(key,value);}
  const job=await pollJob(value);$('comparison').hidden=false;$('comparison-items').replaceChildren();
  if(job.stale){status('초기 의견이 바뀌어 이전 비교가 됐습니다. 현재 의견으로 다시 비교해 주세요.');return;}
  if(!job.result.available){$('comparison-items').append(node('p','초기 의견을 적으면 이 관점과 비교할 수 있습니다.'));return;}
  const names={agreement:'공통점',difference:'차이점',additional_condition:'추가로 살펴볼 조건',unclear:'더 확인할 부분'};
  for(const item of job.result.items){const row=node('article',undefined,'comparison-item');row.append(node('h3',names[item.relation]),node('p',item.explanation));
    row.append(node('blockquote','나의 의견: '+item.user_spans.map(s=>s.text).join(' ')));
    for(const claim of [...item.perspective_claims,...item.required_premises]){row.append(node('blockquote',claim.text));sourceButtons(row,claim);}
    if(item.consideration_question)row.append(node('p',item.consideration_question));$('comparison-items').append(row);
  }
  if(!job.result.items.length)$('comparison-items').append(node('p','두 입력에서 분명한 공통점이나 차이를 확인하지 못했습니다.'));
  status('비교 제안을 확인했습니다. 관점의 원문도 함께 살펴보세요.');
}
function renderRooms(){const select=$('rooms');select.replaceChildren(node('option','대화 선택'));select.firstChild.value='';for(const room of state.session.rooms){const option=node('option',(room.mode==='group'?'그룹':'1:1')+' 대화 · '+({idle:'시작 전',running:'진행 중',pausing:'정지 중',paused:'일시 정지',awaiting_user:'질문 대기',closed:'종료',closing:'종료 중',error:'일부 응답 실패',exhausted:'한도 도달',needs_reconciliation:'확인 필요'}[room.state]||'대기'));option.value=room.room_id;select.append(option);}if(state.room)select.value=state.room.room_id;}
function renderMessages(){
  $('messages').replaceChildren();
  for(const m of state.room.messages){const box=node('article',undefined,'message '+m.author_kind);box.id='message-'+m.message_id;box.append(node('small',m.author_kind==='user'?'나의 질문':label(m.agent_id)));
    if(m.reply_to_message_id){const reply=state.room.messages.find(x=>x.message_id===m.reply_to_message_id);if(reply&&reply.author_kind==='agent')box.append(node('small',label(reply.agent_id)+'의 앞선 발언에 대한 응답'));}
    if(m.body)box.append(node('p',m.body));
    if(m.author_kind==='agent'&&!m.points?.length)box.append(node('p',m.evidence_scope==='expired'?'근거 자료의 기한이 지났습니다.':'이 질문에 답할 근거를 자료에서 찾지 못했습니다.'));
    for(const point of m.points||[]){box.append(node('p',point.text));sourceButtons(box,point);}
    if(m.required_premises?.length){box.append(node('small','함께 확인할 전제·조건'));for(const point of m.required_premises){box.append(node('p',point.text));sourceButtons(box,point);}}
    $('messages').append(box);
  }
}
async function refreshRoom(){
  if(!state.room)return;clearTimeout(state.roomTimer);
  state.room=await api('/rooms/'+state.room.room_id);renderMessages();renderRooms();
  const names={idle:'질문으로 시작할 수 있습니다.',running:'관점이 응답하고 있습니다.',pausing:'현재 응답 뒤에 멈춥니다.',paused:'잠시 멈췄습니다. 질문하거나 이어갈 수 있습니다.',awaiting_user:'대화가 끝났습니다. 나의 질문을 이어갈 수 있습니다.',closed:'종료한 대화입니다.',closing:'현재 처리를 마친 뒤 종료합니다.',error:'일부 응답을 완료하지 못했습니다. 이전 발언은 보존됩니다.',exhausted:'대화 한도에 도달했습니다.',needs_reconciliation:'처리 상태 확인이 필요합니다.'};
  $('room-state').textContent=(names[state.room.state]||state.room.state)+' · '+state.room.turn_count+'/18';
  $('opening').hidden=state.room.state!=='idle';$('pause').disabled=!['running','awaiting_user'].includes(state.room.state);
  $('resume').disabled=state.room.state!=='paused';$('next-round').disabled=!state.room.can_ask;$('close-room').disabled=state.room.state==='closed';
  $('interject').hidden=['idle','closed','closing','exhausted','needs_reconciliation','error'].includes(state.room.state);
  if(['running','pausing','closing'].includes(state.room.state))state.roomTimer=setTimeout(()=>refreshRoom().catch(e=>status(e.message)),700);
}
async function control(action){
  const rid=requestId();
  for(let attempt=0;attempt<3;attempt++){
    await refreshRoom();
    try{const result=await api('/rooms/'+state.room.room_id+'/control','POST',{action,expected_revision:state.room.revision,request_id:rid});await refreshRoom();return result;}
    catch(e){if(e.code!=='revision_conflict'||attempt===2)throw e;}
  }
}
async function refreshReflection(){
  await refreshSession();$('initial-copy').textContent=state.session.initial_opinion.text;
  if(!$('current').value)$('current').value=state.session.current_opinion.revision?state.session.current_opinion.text:state.session.initial_opinion.text;
  $('context-messages').replaceChildren();
  if(state.room){await refreshRoom();for(const message of state.room.messages){const line=node('label',undefined,'context-item'),check=document.createElement('input');check.type='checkbox';check.checked=state.context.has(message.message_id);check.onchange=()=>{if(check.checked)state.context.add(message.message_id);else state.context.delete(message.message_id);};line.append(check,node('span',(message.author_kind==='user'?'나':label(message.agent_id))+': '+(message.body||message.points?.map(p=>p.text).join(' ')||'근거 없음').slice(0,160)));$('context-messages').append(line);}}
}
async function saveCurrent(){const value=$('current').value;if(!state.session.current_opinion.revision||value!==state.session.current_opinion.text){await api(base()+'/opinions/current','PUT',{text:value,expected_revision:state.session.current_opinion.revision,request_id:requestId()});state.reflectionJob=null;state.reflectionResult=null;$('suggestions').replaceChildren();await refreshSession();}return state.session.current_opinion.revision;}
async function jumpTo(mid,refs){const ref=refs?.find(m=>m.message_id===mid);if(ref){state.room={room_id:ref.room_id};await refreshRoom();showStep('converse');document.getElementById('message-'+mid)?.scrollIntoView({block:'center'});}}
function renderSuggestions(result){$('suggestions').replaceChildren();for(const [key,title] of Object.entries(categories)){const group=node('section',undefined,'suggestion');group.append(node('h3',title));for(const item of result.categories[key]){group.append(node('p',item.explanation));for(const mid of item.related_message_ids){const button=node('button','관련 대화','source-button');button.onclick=()=>jumpTo(mid,result.context_message_refs).catch(e=>status(e.message));group.append(button);}}
    if(!result.categories[key].length)group.append(node('p','제안 없음','hint'));
    const adopt=node('button','이 범주의 제안 채택','secondary');adopt.type='button';adopt.onclick=()=>{$(key).value=result.categories[key].map(i=>i.explanation).join('\n');};group.append(adopt);$('suggestions').append(group);}}
function renderSaved(){const list=$('saved-reflections');list.replaceChildren();for(const item of state.session.reflections){const button=node('button','성찰 보기 · 저장본 '+item.revision,'secondary');button.onclick=async()=>{try{const value=await api(base()+'/reflections/'+item.reflection_id);state.saved=value;state.reflectionJob=null;state.reflectionResult=null;$('suggestions').replaceChildren();const view=$('saved-view');view.replaceChildren(node('h3',value.stale?'이전 의견으로 저장한 성찰':'저장한 성찰'));for(const [key,title] of Object.entries(categories)){view.append(node('h3',title));$(key).value=value.user_items[key].map(i=>i.text).join('\n');for(const entry of value.user_items[key]){view.append(node('p',entry.text));for(const mid of entry.related_message_ids){const link=node('button','관련 대화','source-button');link.onclick=()=>jumpTo(mid,value.context_message_refs).catch(e=>status(e.message));view.append(link);}}}$('save-state').textContent='이 저장본을 수정할 수 있습니다. 이전 저장본은 보존됩니다.';}catch(e){status(e.message);}};list.append(button);}}
async function enter(){await refreshSession();state.analysis=state.session.analysis;$('before').hidden=true;$('workspace').hidden=false;renderPerspectives();showStep('explore');status('관점을 선택하고 나의 의견과 비교해 보세요.');}
$('begin').onsubmit=async event=>{event.preventDefault();const bytes=crypto.getRandomValues(new Uint8Array(32));state.token=btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');try{const value=await api('/sessions','POST',{analysis_id:state.analysis.analysis_id,bundle_revision:state.analysis.bundle_revision,initial_opinion:$('initial').value,request_id:requestId()});state.session=value;localStorage.setItem('commentscope-mvp-session',JSON.stringify({token:state.token,session_id:value.session_id}));await enter();}catch(e){status(e.message);}};
$('edit-initial').onsubmit=async event=>{event.preventDefault();try{await api(base()+'/opinions/initial','PUT',{text:$('initial-edit').value,expected_revision:state.session.initial_opinion.revision,request_id:requestId()});state.comparisons.clear();state.reflectionJob=null;state.reflectionResult=null;$('suggestions').replaceChildren();$('comparison').hidden=true;await refreshSession();status('초기 의견을 수정했습니다. 현재 의견으로 새 비교를 볼 수 있습니다.');}catch(e){status(e.message);}};
$('open-room').onclick=async()=>{try{if(!state.selected.size)throw new Error('대화할 관점을 선택해 주세요.');const ids=[...state.selected];state.room=await api(base()+'/rooms','POST',{mode:ids.length===1?'one_to_one':'group',participant_ids:ids,initial_revision:state.session.initial_opinion.revision,request_id:requestId()});await refreshSession();await refreshRoom();showStep('converse');}catch(e){status(e.message);}};
$('rooms').onchange=async()=>{if($('rooms').value){state.room={room_id:$('rooms').value};try{await refreshRoom();}catch(e){status(e.message);}}};
$('opening').onsubmit=async event=>{event.preventDefault();try{await api('/rooms/'+state.room.room_id+'/start','POST',{opening_question:$('opening-question').value,expected_revision:state.room.revision,request_id:requestId()});await refreshRoom();}catch(e){status(e.message);}};
for(const [id,action] of [['pause','pause'],['resume','resume'],['next-round','next_round'],['close-room','close']])$(id).onclick=()=>control(action).catch(e=>status(e.message));
$('interject').onsubmit=async event=>{event.preventDefault();try{await refreshRoom();if(state.room.state==='running')await control('pause');while(state.room.state==='pausing'){await wait(600);await refreshRoom();}await api('/rooms/'+state.room.room_id+'/messages','POST',{text:$('question').value,reply_to_message_id:null,expected_revision:state.room.revision,request_id:requestId()});$('question').value='';await refreshRoom();}catch(e){status(e.message);}};
$('go-reflect').onclick=()=>showStep('reflect');document.querySelectorAll('[data-step]').forEach(button=>button.onclick=()=>showStep(button.dataset.step));
$('analyze').onclick=async()=>{const button=$('analyze');button.disabled=true;try{await saveCurrent();status('나의 의견과 선택한 대화를 정리하고 있습니다.');const value=await api(base()+'/reflection-analyses','POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,context_message_ids:[...state.context],request_id:requestId()});const job=await pollJob(value);state.reflectionJob=job.job_id;state.reflectionResult=job.result;renderSuggestions(job.result);status('제안에서 필요한 내용을 선택하거나 직접 수정해 저장해 주세요.');}catch(e){status(e.message);}finally{button.disabled=false;}};
$('save-reflection').onsubmit=async event=>{event.preventDefault();try{await saveCurrent();const user_items={};for(const key of Object.keys(categories)){const values=$(key).value.split('\n').filter(s=>s.trim());user_items[key]=values.map(value=>{const savedMatches=state.saved&&['initial','current'].every(kind=>state.saved[kind+'_revision']===state.session[kind+'_opinion'].revision);const original=state.reflectionResult?.categories[key].find(i=>i.explanation===value)||(savedMatches?state.saved.user_items[key].find(i=>i.text===value):null);return {text:value,initial_span_ids:original?.initial_span_ids||[],current_span_ids:original?.current_span_ids||[],related_message_ids:original?.related_message_ids||[]};});}const path=base()+'/reflections'+(state.saved?'/'+state.saved.reflection_id:'');const value=await api(path,state.saved?'PUT':'POST',{initial_revision:state.session.initial_opinion.revision,current_revision:state.session.current_opinion.revision,analysis_job_id:state.reflectionJob,user_items,expected_revision:state.saved?.revision||0,request_id:requestId()});state.saved=value;$('save-state').textContent='저장했습니다. '+value.revision+'번째 저장본';await refreshSession();}catch(e){status(e.message);}};
$('new-session').onclick=()=>{clearTimeout(state.roomTimer);localStorage.removeItem('commentscope-mvp-session');location.reload();};
(async()=>{try{const available=await api('/analyses');state.analysis=available.analyses.find(a=>a.status==='experimental'||a.status==='available');if(!state.analysis){status('아직 사용할 수 있는 분석이 없습니다.');$('begin').querySelector('button').disabled=true;return;}const previous=localStorage.getItem('commentscope-mvp-session');if(previous){const saved=JSON.parse(previous);state.token=saved.token;state.session={session_id:saved.session_id};try{await enter();return;}catch(_){localStorage.removeItem('commentscope-mvp-session');state.session=null;state.token='';}}status('먼저 나의 초기 의견을 적어 주세요. 비워 두고 관점을 살펴봐도 됩니다.');}catch(e){status(e.message);}})();
