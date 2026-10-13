'use strict';
// Connect only to the owned loopback app. Real model calls are budgeted by Python.
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const {spawn} = require('node:child_process');
const WebSocket = require('ws');
const [origin, chrome, destination, planPath] = process.argv.slice(2);
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin || '') || !chrome || !destination || !planPath)
  throw Error('Usage: node actual_agent_browser.cjs LOOPBACK_ORIGIN CHROME NEW_OUTPUT FROZEN_PLAN');
const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
const output = path.resolve(destination); fs.mkdirSync(output, {recursive: false});
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'commentscope-actual-browser-'));
const checks = {synthetic_only: false, actual_input_ids: plan.all_profile_ids,
  comparison_pair: plan.comparison_pair, quality_gate_passed: false,
  checks: {}, page_errors: [], external_requests: []};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, timeout=10000) {
  const end = Date.now()+timeout;
  while (Date.now()<end) { const value=await fn(); if(value)return value; await sleep(150); }
  throw Error('Browser check deadline');
}
let browser, socket;
(async () => {
  browser=spawn(chrome,['--headless=new','--disable-gpu','--disable-background-networking','--disable-component-update',
    '--disable-sync','--no-first-run','--no-default-browser-check','--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
  browser.stderr.on('data',chunk=>fs.appendFileSync(path.join(output,'chromium.log'),chunk));
  const port=await until(()=>{
    if(browser.exitCode!==null)throw Error('Chromium exited');
    const file=path.join(profile,'DevToolsActivePort');
    return fs.existsSync(file)?Number(fs.readFileSync(file,'utf8').split('\n')[0]):null;
  });
  const pages=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.once('open',resolve);socket.once('error',reject);});
  let id=0;const pending=new Map();
  socket.on('message',bytes=>{
    const msg=JSON.parse(bytes.toString());
    if(msg.id&&pending.has(msg.id)){const cb=pending.get(msg.id);pending.delete(msg.id);clearTimeout(cb.timer);msg.error?cb.reject(Error(msg.error.message)):cb.resolve(msg.result);}
    if(msg.method==='Runtime.exceptionThrown')checks.page_errors.push(msg.params.exceptionDetails.text);
    if(msg.method==='Network.requestWillBeSent'&&/^https?:/.test(msg.params.request.url)&&!msg.params.request.url.startsWith(origin+'/'))checks.external_requests.push(msg.params.request.url);
  });
  const call=(method,params={})=>new Promise((resolve,reject)=>{
    const key=++id;const timer=setTimeout(()=>{pending.delete(key);reject(Error('CDP timeout: '+method));},10000);
    pending.set(key,{resolve,reject,timer});socket.send(JSON.stringify({id:key,method,params}));
  });
  const evaluate=async expression=>{
    const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails)throw Error('Page expression failed');return result.result.value;
  };
  const screenshot=async name=>{const image=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});fs.writeFileSync(path.join(output,name),Buffer.from(image.data,'base64'),{flag:'wx'});};
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:origin+'/'});
  await until(()=>evaluate(`document.querySelector('#profiles')?.children.length===${plan.all_profile_ids.length} && !document.querySelector('#submit').disabled`));
  const initial=await evaluate("api('/api/state')");
  checks.checks.all_automatic_inputs_visible=JSON.stringify(initial.profiles.map(p=>p.candidate_id))===JSON.stringify(plan.all_profile_ids);
  checks.checks.no_automatic_quality_approval=initial.quality_gate_passed===false && !!initial.notice;
  checks.checks.fixed_pair=JSON.stringify(initial.selected)===JSON.stringify(plan.comparison_pair);
  await screenshot('initial.png');
  for(const [index,question] of ['What is the central position represented here?','Why?','What exact monthly UBI amount does this perspective recommend?'].entries()) {
    await evaluate(`document.querySelector('#question').value=${JSON.stringify(question)}; document.querySelector('#ask').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));`);
    await until(()=>evaluate(`document.querySelectorAll('#rounds > section').length===${index+1} && document.querySelector('#status').textContent.includes('완료')`),75000);
  }
  const state=await evaluate("api('/api/state')");
  fs.writeFileSync(path.join(output,'state.json'),JSON.stringify(state,null,2),{flag:'wx'});
  checks.checks.three_rounds=state.rounds.length===3 && state.rounds.every(r=>r.answers.length===2);
  checks.checks.core_answers=state.rounds[0].answers.every(a=>a.status==='answered' && a.points.some(p=>plan.references[a.candidate_id].core.includes(p.claim_id)));
  checks.checks.followup_reasons=state.rounds[1].answers.every(a=>a.status==='answered' && a.points.some(p=>plan.references[a.candidate_id].reason.includes(p.claim_id)));
  checks.checks.abstentions=state.rounds[2].answers.every(a=>a.status==='abstain' && a.points.length===0);
  checks.checks.abstentions_visible=await evaluate("document.querySelector('#rounds').lastElementChild.textContent.includes('보류합니다')");
  // Click every distinct cited source, not just the first easy source.
  const citations=await evaluate("Array.from(document.querySelectorAll('#rounds button')).map(b=>b.title)");
  const sources=new Map(plan.bundle.sources.map(s=>[s.id,s.text]));
  for(const sid of new Set(citations)) {
    await evaluate(`Array.from(document.querySelectorAll('#rounds button')).find(b=>b.title===${JSON.stringify(sid)}).click()`);
    await until(()=>evaluate(`document.querySelector('#source').textContent===${JSON.stringify(sid+'\n'+sources.get(sid))}`));
  }
  checks.checks.cited_sources_match_originals=citations.length>0;
  checks.distinct_sources_opened=new Set(citations).size;
  await screenshot('comparison.png');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  checks.checks.no_mobile_overflow=await evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth');
  await screenshot('mobile.png');
  checks.passed=Object.values(checks.checks).every(Boolean)&&checks.page_errors.length===0&&checks.external_requests.length===0;
  if(!checks.passed)throw Error('Browser assertions failed');
})().catch(error=>{checks.error=error.message;checks.passed=false;process.exitCode=1;}).finally(async()=>{
  if(socket)socket.close();
  if(browser&&browser.exitCode===null&&browser.signalCode===null){browser.kill('SIGTERM');await until(()=>browser.exitCode!==null||browser.signalCode!==null,5000).catch(()=>browser.kill('SIGKILL'));}
  fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify(checks,null,2),{flag:'wx'});
  console.log(JSON.stringify(checks,null,2));
});
