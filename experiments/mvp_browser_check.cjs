'use strict';
// Real browser product-flow check with synthetic provider responses only.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process');
const WebSocket=require('ws');
const [python,chrome,destination,mode,debateResult='consensus']=process.argv.slice(2);
const automatic=mode==='--automatic-debate';
if(!python||!chrome||!destination)throw Error('Usage: node mvp_browser_check.cjs PYTHON CHROME NEW_PRIVATE_OUTPUT');
if(mode&&!['--seeded','--automatic-debate'].includes(mode))throw Error('Unknown browser fixture mode');
if(!['consensus','no-consensus','hold'].includes(debateResult))throw Error('Unknown debate fixture result');
const output=path.resolve(destination);fs.mkdirSync(output,{recursive:false});
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'commentscope-mvp-browser-'));
const report={synthetic_only:true,seeded_mode:mode==='--seeded',paid_calls:0,semantic_quality_measured:false,checks:{},page_errors:[],external_requests:[]};
const requests=[];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,timeout=12000){const end=Date.now()+timeout;while(Date.now()<end){const value=await fn();if(value)return value;await sleep(80);}throw Error('Browser assertion deadline');}
let server,browser,socket;
(async()=>{
  let stdout='';
  server=spawn(python,['-m','experiments.mvp_browser_fixture',path.join(output,'fixture'),...(mode?[mode]:[]),...(automatic?['--debate-result',debateResult]:[])],{
    stdio:['ignore','pipe','pipe'],env:{...process.env,PYTHONPATH:[path.resolve('src'),process.cwd()].join(path.delimiter)}});
  server.stdout.on('data',chunk=>stdout+=chunk.toString());server.stderr.on('data',chunk=>fs.appendFileSync(path.join(output,'fixture.log'),chunk));
  const origin=await until(()=>{if(server.exitCode!==null)throw Error('Fixture exited');return stdout.includes('\n')?JSON.parse(stdout.split('\n')[0]).origin:null;});
  browser=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-background-networking',
    '--disable-component-update','--disable-sync','--no-first-run','--no-default-browser-check',
    '--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
  browser.stderr.on('data',chunk=>fs.appendFileSync(path.join(output,'chromium.log'),chunk));
  const port=await until(()=>{if(browser.exitCode!==null)throw Error('Chromium exited');const file=path.join(profile,'DevToolsActivePort');return fs.existsSync(file)?Number(fs.readFileSync(file,'utf8').split('\n')[0]):null;});
  const pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.once('open',resolve);socket.once('error',reject);});
  let sequence=0;const pending=new Map();
  socket.on('message',bytes=>{const value=JSON.parse(bytes.toString());if(value.id&&pending.has(value.id)){const target=pending.get(value.id);pending.delete(value.id);clearTimeout(target.timer);value.error?target.reject(Error(value.error.message)):target.resolve(value.result);}
    if(value.method==='Runtime.exceptionThrown')report.page_errors.push(value.params.exceptionDetails.text);
    if(automatic&&value.method==='Network.requestWillBeSent'&&value.params.request.url.startsWith(origin+'/api/v1/')){
      const {method,url}=value.params.request;
      requests.push({method,path:new URL(url).pathname});
    }
    if(value.method==='Network.requestWillBeSent'&&/^https?:/.test(value.params.request.url)&&!value.params.request.url.startsWith(origin+'/')){
      const url=value.params.request.url;
      if(report.media_fixture_mode&&(/^https:\/\/i\.ytimg\.com\/vi\/ABCDEFGHIJK\//.test(url)||/^https:\/\/www\.youtube-nocookie\.com\/embed\/ABCDEFGHIJK\?/.test(url)))report.media_fixture_requests.push(url);
      else report.external_requests.push(url);
    }
    if(value.method==='Fetch.requestPaused'){
      const request=value.params.request,isVideo=request.url.startsWith('https://www.youtube-nocookie.com/');
      if(isVideo)report.media_referer=request.headers.Referer||request.headers.referer||'';
      const body=isVideo?Buffer.from('<!doctype html><title>Intercepted media fixture</title>').toString('base64'):'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6N8AAAAASUVORK5CYII=';
      command('Fetch.fulfillRequest',{requestId:value.params.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:isVideo?'text/html':'image/png'}],body}).catch(error=>report.page_errors.push(error.message));
    }
  });
  const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout'));},12000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error('Page expression failed: '+expression.slice(0,80));return result.result.value;};
  const screenshot=async name=>{const result=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});fs.writeFileSync(path.join(output,name),Buffer.from(result.data,'base64'),{flag:'wx'});};
  const submit=id=>evaluate(`document.getElementById(${JSON.stringify(id)}).dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))`);
  await command('Page.enable');await command('Runtime.enable');await command('Network.enable');
  await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await command('Page.navigate',{url:origin+'/mvp'});
  await until(()=>evaluate("document.querySelector('#status')?.textContent.includes('먼저')"));
  if(automatic){
    await verifyAutomaticDebate({command,evaluate,screenshot});
    report.passed=Object.values(report.checks).every(Boolean)&&report.page_errors.length===0&&
      report.external_requests.length===0&&report.metrics.paid_calls===0;
    if(!report.passed)throw Error('Automatic debate browser checks failed');
    return;
  }
  await evaluate("document.querySelector('[data-step=reflect]').click()");
  report.checks.opinion_step_precedes_workspace=await evaluate("document.querySelector('#workspace').hidden&&!document.querySelector('#before').hidden");
  await evaluate("document.querySelector('#initial').value='😀';document.querySelector('#initial').dispatchEvent(new Event('input'))");
  report.checks.unicode_character_counter=await evaluate("document.querySelector('#initial-count').textContent.includes('1 / 500')");
  await screenshot('before.png');
  await evaluate("document.querySelector('#initial').value='<img src=x onerror=globalThis.xssExecuted=true> Safety reviews should be required.'");
  await submit('begin');await until(()=>evaluate("!document.querySelector('#workspace').hidden&&document.querySelectorAll('.card').length===2"));
  report.checks.session_and_two_perspectives=true;
  report.checks.no_start_over_button=await evaluate("!document.querySelector('#new-session')&&!document.querySelector('.card .compare-button')");
  await until(()=>evaluate("document.querySelectorAll('.card-relation').length>0&&!Array.from(document.querySelectorAll('.relation-note')).some(x=>x.textContent.startsWith('Comparing'))"));
  report.checks.cards_show_relation_summary=await evaluate("Array.from(document.querySelectorAll('.card-relation')).every(x=>x.querySelector('.relation-bar')||x.querySelector('.relation-note'))");
  report.checks.single_viewer_ratio_note=await evaluate("!Array.from(document.querySelectorAll('.card')).some(c=>c.textContent.includes('전체 시청자'))");
  await evaluate("document.querySelector('.card').click()");
  await until(()=>evaluate("!document.querySelector('#comparison').hidden&&document.querySelectorAll('.comparison-item').length===1"));
  report.checks.explore_comparison=true;
  report.checks.untrusted_text_is_text=await evaluate("!document.querySelector('#comparison-items img')&&!globalThis.xssExecuted&&document.querySelector('#comparison-items').textContent.includes('<img')");
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await until(()=>evaluate("!document.querySelector('#comparison').open&&document.querySelector('#comparison').hidden"));
  report.checks.comparison_keyboard_dismissal=true;
  const comparisonCalls=JSON.parse(fs.readFileSync(path.join(output,'fixture/metrics.json'),'utf8')).synthetic_provider_calls;
  await evaluate("document.querySelector('.card').click()");
  await until(()=>evaluate("document.querySelector('#comparison').open"));
  report.checks.repeat_comparison_does_not_generate=comparisonCalls===JSON.parse(fs.readFileSync(path.join(output,'fixture/metrics.json'),'utf8')).synthetic_provider_calls;
  await evaluate('document.fonts.ready');
  report.checks.packaged_font_and_images_load=await evaluate("document.fonts.check('14px Inter')&&document.fonts.check('14px Geologica')&&Array.from(document.querySelectorAll('img')).every(i=>i.complete&&i.naturalWidth>0)");
  await screenshot('explore.png');
  await evaluate("document.querySelectorAll('.card input').forEach(x=>x.click());document.querySelector('#open-room').click()");
  await until(()=>evaluate("!document.querySelector('#opening').hidden&&!document.querySelector('#converse').hidden"));
  await submit('opening');
  await until(()=>evaluate("document.querySelectorAll('.message.agent').length>=1"));
  await evaluate("document.querySelector('#pause').click()");
  await until(()=>evaluate("document.querySelector('#room-state').textContent.includes('잠시 멈췄습니다')"));
  report.checks.pause_control=true;
  await evaluate("document.querySelector('#resume').click()");
  await until(()=>evaluate("document.querySelectorAll('.message.agent').length===4&&document.querySelector('#room-state').textContent.includes('대화가 끝났습니다')"));
  report.checks.group_opening_and_reply=true;
  if(report.seeded_mode){
    report.checks.seeded_provenance_labels=await evaluate("['댓글 근거','AI 추론 · 원작성자의 발언이 아닙니다','외부 자료 기반 주장'].every(label=>document.querySelector('#messages').textContent.includes(label))");
    report.checks.seeded_external_reference_link=await evaluate("Array.from(document.querySelectorAll('.message.agent a.source-button')).some(a=>a.protocol==='https:'&&a.rel.includes('noopener'))");
    report.checks.seeded_typed_calls=JSON.parse(fs.readFileSync(path.join(output,'fixture/metrics.json'),'utf8')).synthetic_typed_calls===4;
  }
  report.checks.peer_reply_links=await evaluate("document.querySelector('#messages').textContent.split('앞선 발언에 대한 응답').length===3");
  await evaluate("document.querySelector('.message.agent .source-button').click()");
  await until(()=>evaluate("document.querySelector('#source').textContent.includes('Safety reviews')"));
  report.checks.source_lookup=await evaluate("document.querySelector('#source-dialog').open");await screenshot('source.png');
  await evaluate("document.querySelector('#close-source').click()");
  report.checks.source_drawer_dismissal=await evaluate("!document.querySelector('#source-dialog').open");await screenshot('conversation.png');
  await evaluate("document.querySelector('#go-reflect').click()");
  await until(()=>evaluate("document.querySelectorAll('#context-messages input').length===5"));
  await evaluate("document.querySelector('#current').value='I still support safety reviews.';document.querySelectorAll('#context-messages input')[1].click();document.querySelector('#analyze').click()");
  await until(()=>evaluate("document.querySelectorAll('#suggestions .suggestion').length===4"));
  report.checks.reflection_four_categories=true;
  await evaluate("document.querySelector('#suggestions button.secondary').click()");
  await submit('save-reflection');
  await until(()=>evaluate("document.querySelector('#save-state').textContent.includes('저장했습니다')&&document.querySelector('#saved-reflections button')"));
  const beforeSave=JSON.parse(fs.readFileSync(path.join(output,'fixture/metrics.json'),'utf8')).synthetic_provider_calls;
  await evaluate("document.querySelector('#suggestions .source-button').click()");
  await until(()=>evaluate("!document.querySelector('#converse').hidden"));report.checks.related_conversation_navigation=true;
  await evaluate("document.querySelector('[data-step=reflect]').click()");
  await until(()=>evaluate("!document.querySelector('#reflect').hidden"));
  await evaluate("document.querySelector('#stayed').value='내가 직접 수정한 성찰입니다.'");
  await submit('save-reflection');await until(()=>evaluate("document.querySelector('#save-state').textContent.includes('2번째')"));
  await screenshot('reflection.png');
  await command('Page.reload');
  await until(()=>evaluate("!document.querySelector('#workspace').hidden"));
  await evaluate("document.querySelector('[data-step=reflect]').click()");
  await until(()=>evaluate("document.querySelector('#saved-reflections button')?.textContent.includes('저장본 2')"));
  await evaluate("document.querySelector('#saved-reflections button').click()");
  await until(()=>evaluate("document.querySelector('#saved-view').textContent.includes('내가 직접 수정한 성찰입니다.')"));
  report.checks.edited_reflection_survives_reload=true;
  const afterSave=JSON.parse(fs.readFileSync(path.join(output,'fixture/metrics.json'),'utf8')).synthetic_provider_calls;
  report.checks.save_reload_and_reads_do_not_generate=beforeSave===afterSave;
  report.synthetic_provider_calls=afterSave;
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  report.checks.no_mobile_overflow=await evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth');
  await screenshot('mobile.png');
  await evaluate("document.querySelector('[data-step=explore]').click();document.querySelector('.card input').click();document.querySelector('#open-room').click()");
  await until(()=>evaluate("!document.querySelector('#opening').hidden&&!document.querySelector('#converse').hidden"));
  await submit('opening');
  await until(()=>evaluate("document.querySelectorAll('.message.agent').length===1&&document.querySelector('#room-state').textContent.includes('대화가 끝났습니다')"));
  await evaluate("document.querySelector('#question').value='What supports this position?'");
  await submit('interject');
  await until(()=>evaluate("document.querySelectorAll('.message.agent').length===2&&document.querySelectorAll('.message.user').length===2"));
  report.checks.one_to_one_and_followup=true;
  // Intercept media before dispatch. This checks browser request identity and layout, not YouTube playback.
  report.media_fixture_mode=true;report.media_fixture_requests=[];report.youtube_playback_measured=false;
  await command('Fetch.enable',{patterns:[{urlPattern:'https://i.ytimg.com/vi/ABCDEFGHIJK/*'},{urlPattern:'https://www.youtube-nocookie.com/embed/ABCDEFGHIJK*'}]});
  await evaluate("state.analysis.video={video_id:'ABCDEFGHIJK',title:'Registered video fixture'};renderAnalysis();document.querySelector('#before').hidden=false;document.querySelector('#workspace').hidden=true;document.body.dataset.step='before'");
  report.checks.registered_video_metadata=await evaluate("document.querySelector('#video-title').textContent==='Registered video fixture'&&document.querySelector('#original-video').href==='https://www.youtube.com/watch?v=ABCDEFGHIJK'");
  await evaluate("document.querySelector('.video-play').click()");
  await until(()=>report.media_referer);
  report.checks.embedded_video_origin_referrer=report.media_referer===origin+'/';
  report.checks.mobile_video_minimum_viewport=await evaluate("document.querySelector('#video-frame iframe').getBoundingClientRect().height>=200");
  await command('Fetch.disable');
  report.synthetic_provider_calls=JSON.parse(fs.readFileSync(path.join(output,'fixture/metrics.json'),'utf8')).synthetic_provider_calls;
  report.passed=Object.values(report.checks).every(Boolean)&&report.page_errors.length===0&&report.external_requests.length===0;
  if(!report.passed)throw Error('Product browser checks failed');
})().catch(error=>{report.error=error.message;process.exitCode=1;}).finally(async()=>{
  if(socket)socket.close();
  for(const child of [browser,server])if(child&&child.exitCode===null&&child.signalCode===null){child.kill('SIGTERM');await until(()=>child.exitCode!==null||child.signalCode!==null,4000).catch(()=>child.kill('SIGKILL'));}
  fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify(report,null,2),{flag:'wx'});
  console.log(JSON.stringify({output,...report},null,2));
});


async function verifyAutomaticDebate({command,evaluate,screenshot}){
  const checks=report.checks;
  const click=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const fill=(selector,value)=>evaluate(`document.querySelector(${JSON.stringify(selector)}).value=${JSON.stringify(value)}`);
  const postCount=pattern=>requests.filter(item=>item.method==='POST'&&pattern.test(item.path)).length;
  const metrics=()=>JSON.parse(fs.readFileSync(path.join(output,'fixture/metrics.json'),'utf8'));
  const reload=async()=>{
    const originalPage=await evaluate('performance.timeOrigin');
    await command('Page.reload');
    await until(()=>evaluate(`performance.timeOrigin!==${originalPage}&&document.querySelector('#workspace')?.hidden===false&&document.querySelectorAll('.card').length===2`));
  };
  report.mode='automatic_debate';
  report.expected_outcome=debateResult;
  await fill('#initial','Safety checks matter, but their cost depends on the risk.');
  await click('#begin button[type=submit]');
  await until(()=>evaluate("document.querySelectorAll('.card').length===2"));
  await until(()=>evaluate("document.querySelectorAll('.card-relation').length>0&&!Array.from(document.querySelectorAll('.relation-note')).some(x=>x.textContent.startsWith('Comparing'))"));
  const callsBeforeSources=fs.existsSync(path.join(output,'fixture/metrics.json'))?metrics():null;
  await evaluate("document.querySelector('.card').click()");
  await until(()=>evaluate("document.querySelector('#comparison')?.open"));
  checks.compare_selected_perspective=true;
  await click('#comparison-sources .card-sources .source-button');
  await until(()=>evaluate("document.querySelector('#source-dialog').open"));
  checks.explore_stance_original_visible=await evaluate("document.querySelector('#source').textContent.includes('Safety reviews should be required.')");
  await click('#close-source');
  await click('#comparison-sources .card-ground-sources .source-button');
  await until(()=>evaluate("document.querySelector('#source-dialog').open"));
  checks.explore_ground_uses_own_original=await evaluate("document.querySelector('#source').textContent.includes('12 of 100 devices failed.')");
  await click('#close-source');
  checks.explore_source_access_does_not_generate=!callsBeforeSources ||
    (metrics().synthetic_provider_calls===callsBeforeSources.synthetic_provider_calls && metrics().synthetic_typed_calls===callsBeforeSources.synthetic_typed_calls);
  await click('#close-comparison');
  await click('.card:nth-child(2) input');
  await click('.card:nth-child(1) input');
  await click('#open-room');
  await until(()=>evaluate("!document.querySelector('#converse').hidden&&!document.querySelector('#opening').hidden"));
  checks.automatic_offered_for_two=await evaluate("document.querySelector('#opening-submit-label').textContent==='자동 토론 시작'");
  await click('#opening button[type=submit]');
  checks.blank_question_does_not_start=postCount(/\/debates$/)===0;
  const question='어떤 위험에서는 안전 검토가 필요하며 어떤 예외를 둘 수 있나요?';
  await fill('#opening-question',question);
  await evaluate("document.querySelector('#opening button[type=submit]').click();document.querySelector('#opening').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))");
  await until(()=>postCount(/\/debates\/[^/]+\/start$/)===1);
  const debatePath=requests.find(item=>item.method==='POST'&&/\/debates\/[^/]+\/start$/.test(item.path)).path.replace(/\/start$/,'');
  await reload();
  await until(()=>evaluate("document.body.dataset.step==='converse'"));
  checks.reopens_conversation_after_reload=true;
  if(debateResult==='no-consensus'){
    await until(()=>evaluate("!document.querySelector('#pause').disabled"));
    await click('#pause');
    await until(()=>evaluate("!document.querySelector('#resume').disabled"));
    const saved=JSON.stringify(metrics());
    await sleep(800);
    checks.paused_debate_cost_stays_fixed=JSON.stringify(metrics())===saved;
    await click('#resume');
  }

  const stateLabels={consensus:'완료','no-consensus':'합의 없음',hold:'검증 보류'};
  await until(()=>evaluate(`!document.querySelector('#debate-conclusion').hidden&&document.querySelector('#debate-conclusion h2').textContent===${JSON.stringify('토론 결론 · '+stateLabels[debateResult])}`));
  checks.single_start=postCount(/\/debates$/)===1&&postCount(/\/debates\/[^/]+\/start$/)===1;
  checks.no_additional_turn_or_merge_clicks=!requests.some(item=>item.method==='POST'&&/\/syntheses\b|\/ratif/.test(item.path));
  checks.debate_path_polled=requests.some(item=>item.method==='GET'&&item.path===debatePath);
  checks.question_and_four_visible_turns=await evaluate(`document.querySelector('.message.user').textContent.includes(${JSON.stringify(question)})&&document.querySelectorAll('.message.agent').length===4&&document.querySelector('#room-state').textContent.endsWith('4/4')`);
  checks.selected_order=await evaluate("Array.from(document.querySelectorAll('.message.agent .bubble>small:first-child')).map(x=>x.textContent.split(' · ')[0]).join(',')==='Perspective 2,Perspective 1,Perspective 2,Perspective 1'");
  checks.visible_reply_links=await evaluate("Array.from(document.querySelectorAll('.message.agent .source-button')).filter(x=>x.textContent.startsWith('응답 대상')).length===2");
  checks.pending_request_count_unchanged=metrics().synthetic_provider_calls===8&&metrics().synthetic_typed_calls===7;
  await click('#show-debate-result');
  checks.conclusion_reachable=await evaluate("document.activeElement?.id==='debate-conclusion'");
  await screenshot('debate-result.png');

  if(debateResult==='consensus'){
    checks.shared_claim_conditions_and_agent_card=await evaluate("document.querySelector('.debate-claim h3')?.textContent.includes('Consider the risks and costs')&&document.querySelector('.debate-claim').innerText.includes('조건 ·')&&!!document.querySelector('.synthesis-card #ask-synthesis-agent')");
    await click('.debate-claim .debate-references button');
    checks.claim_links_to_posted_turn=await evaluate("document.activeElement?.classList.contains('bubble')");
    await click('.synthesis-card .source-button');
    await until(()=>evaluate("document.querySelector('#source-dialog')?.open&&document.querySelector('#source').textContent.includes('Safety reviews')"));
    checks.derived_agent_source_drawer=requests.some(item=>item.method==='GET'&&/\/synthesis-agents\/[^/]+\/sources\//.test(item.path));
    await click('#close-source');
    await click('#ask-synthesis-agent');
    await until(()=>evaluate("document.querySelector('#room-title').textContent==='합의 Agent'&&!document.querySelector('#opening').hidden"));
    checks.opened_derived_room=postCount(/\/synthesis-agents\/[^/]+\/rooms$/)===1;
    await fill('#opening-question','What exactly was agreed and what remains uncertain?');
    await click('#opening button[type=submit]');
    await until(()=>evaluate("document.querySelector('.message.agent')?.innerText.includes('sets no mandatory threshold')"));
    checks.derived_answer_boundary=await evaluate("document.querySelector('.message.agent')?.innerText.includes('합의 Agent')&&document.querySelector('.message.agent')?.innerText.includes('AI 추론')");
    await click('#agent-info');
    await until(()=>evaluate("document.querySelector('#perspective-dialog').open&&document.querySelector('#perspective-info').innerText.includes('Perspective 2, Perspective 1')"));
    checks.agent_parent_lineage_visible=true;
    await click('#close-perspective');
    await screenshot('synthesis-agent-followup.png');
  }else{
    checks.explanation_and_no_synthesis=await evaluate("!!document.querySelector('#debate-conclusion>p')&&!document.querySelector('.synthesis-card')&&!document.querySelector('#go-reflect').disabled");
  }

  await click('#go-reflect');
  await until(()=>evaluate("!document.querySelector('#reflect').hidden&&document.querySelectorAll('#context-messages input').length>=2"));
  await click('#context-messages .context-item:nth-child(2) input');
  if(debateResult==='consensus'){
    await click('#reflection-rooms .reflection-room:first-child button');
    await until(()=>evaluate("document.querySelectorAll('#context-messages input').length===5"));
    await click('#context-messages .context-item:nth-child(2) input');
  }
  await fill('#current','I would separate justified review from a universal requirement.');
  await click('#analyze');
  await until(()=>evaluate("document.querySelectorAll('#suggestions .suggestion').length===4"));
  checks.reflection_analysis_works=true;
  await click('#insight-stayed button.secondary');
  await fill('#worth_more_thought','비용과 위험을 나누어 보는 것이 중요하다는 생각은 유지했습니다.');
  await click('#save-reflection button[type=submit]');
  await until(()=>evaluate("document.querySelector('#save-state').textContent.includes('저장했습니다')"));
  const beforeReload=metrics();
  await reload();
  await click('[data-step=reflect]');
  await until(()=>evaluate("document.querySelector('#saved-reflections button')"));
  await click('#saved-reflections button');
  await until(()=>evaluate("document.querySelector('#saved-view').textContent.includes('비용과 위험을 나누어 보는 것이 중요')"));
  checks.reflect_reopens_without_inference=JSON.stringify(beforeReload)===JSON.stringify(metrics());
  await screenshot('reflected-after-reload.png');
  if(debateResult==='consensus'){
    await click('#saved-view .source-button');
    await until(()=>evaluate("document.body.dataset.step==='converse'&&document.querySelector('#room-title').textContent==='합의 Agent'"));
    checks.saved_reflection_links_to_derived_reply=true;
    await click('#room-list .room-entry:first-child');
  }
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await click('[data-step=converse]');
  await until(()=>evaluate("document.body.dataset.step==='converse'&&!document.querySelector('#debate-conclusion').hidden"));
  checks.mobile_conclusion_fits=await evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth');
  await screenshot('mobile-debate-result.png');
  if(debateResult==='consensus'){
    const savedSession=await evaluate("JSON.parse(localStorage.getItem('commentscope-mvp-session')).session_id");
    const beforeRestore=metrics();
    const inject=await command('Page.addScriptToEvaluateOnNewDocument',{source:`
      const realFetch=window.fetch;
      window.fetch=(url, options)=>
        /^\\/api\\/v1\\/sessions\\/[^/]+$/.test(url)&&options?.method==='GET'
          ? Promise.resolve(new Response(JSON.stringify({error:{code:'temporarily_unavailable'}}),{status:503}))
          : realFetch(url,options);
    `});
    const timeOrigin=await evaluate('performance.timeOrigin');
    await command('Page.reload');
    await until(()=>evaluate(`performance.timeOrigin!==${timeOrigin}&&document.readyState==='complete'`));
    await until(()=>evaluate("!document.querySelector('#status').textContent.startsWith('Loading')"));
    checks.temporary_restore_error_keeps_session=await evaluate(`
      JSON.parse(localStorage.getItem('commentscope-mvp-session'))?.session_id===${JSON.stringify(savedSession)}
      &&document.querySelector('#begin button[type=submit]').disabled
    `);
    await command('Page.removeScriptToEvaluateOnNewDocument',{identifier:inject.identifier});
    if(!checks.temporary_restore_error_keeps_session)throw Error('A temporary session read failure discarded saved access');
    await reload();
    await until(()=>evaluate("document.body.dataset.step==='converse'&&!document.querySelector('#debate-conclusion').hidden"));
    checks.recovers_same_session_and_debate=await evaluate(`state.session.session_id===${JSON.stringify(savedSession)}`)
      &&JSON.stringify(beforeRestore)===JSON.stringify(metrics());
  }
  await click('#close-room');
  await until(()=>evaluate("document.querySelector('#room-state').textContent.includes('종료한 대화')"));
  checks.close_uses_debate_and_keeps_conclusion=postCount(/\/debates\/[^/]+\/control$/)>0&&
    await evaluate("!document.querySelector('#debate-conclusion').hidden");
  report.metrics=metrics();
}
