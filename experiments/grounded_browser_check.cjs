'use strict';
// Optional installed-Chromium check. Uses only synthetic fixtures, not an LLM.
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const {spawn} = require('node:child_process');
const WebSocket = require('ws');
const [python, chrome, destination] = process.argv.slice(2);
if (!python || !chrome || !destination) throw Error('Usage: node grounded_browser_check.cjs PYTHON CHROME NEW_PRIVATE_OUTPUT');
const output = path.resolve(destination);
fs.mkdirSync(output, {recursive: false});
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'commentscope-browser-'));
const checks = {synthetic_only:true, model_calls:0, semantic_quality_measured:false, checks:{}, page_errors:[], external_requests:[]};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, timeout=10000) {
  const end=Date.now()+timeout;
  while(Date.now()<end) {const value=await fn();if(value)return value;await sleep(100);}
  throw Error('Browser check deadline');
}
let server, browser, socket;
(async () => {
  let serverOut='';
  server=spawn(python,['-m','experiments.grounded_browser_fixture',path.join(output,'sessions')],{stdio:['ignore','pipe','pipe']});
  server.stdout.on('data',chunk=>serverOut+=chunk.toString());
  server.stderr.on('data',chunk=>fs.appendFileSync(path.join(output,'fixture.log'),chunk));
  const origin=await until(()=>{
    if(server.exitCode!==null)throw Error('Fixture exited');
    return serverOut.includes('\n') ? JSON.parse(serverOut.split('\n')[0]).origin : null;
  });
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
    if(result.exceptionDetails)throw Error('Page expression failed');
    return result.result.value;
  };
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:origin+'/'});
  await until(()=>evaluate("document.querySelector('#profiles')?.children.length===2 && !document.querySelector('#submit').disabled"));
  checks.checks.two_synthetic_profiles=true;
  checks.checks.textarea_contrast=await evaluate("getComputedStyle(document.querySelector('#question')).color!==getComputedStyle(document.querySelector('#question')).backgroundColor");
  const screenshot=async name=>{const image=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});fs.writeFileSync(path.join(output,name),Buffer.from(image.data,'base64'),{flag:'wx'});};
  await screenshot('initial.png');
  for(const [index,question] of ['What is your position?','Why?','What exact amount?'].entries()) {
    await evaluate(`document.querySelector('#question').value=${JSON.stringify(question)}; document.querySelector('#ask').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));`);
    await until(()=>evaluate(`document.querySelectorAll('#rounds > section').length===${index+1} && document.querySelector('#status').textContent.includes('완료')`));
  }
  checks.checks.three_rounds=await evaluate("document.querySelectorAll('#rounds .answer').length===6");
  checks.checks.abstentions_visible=await evaluate("document.querySelector('#rounds').lastElementChild.textContent.includes('보류합니다')");
  await evaluate("document.querySelector('#rounds button').click()");
  checks.checks.source_visible=await until(()=>evaluate("!document.querySelector('#source').textContent.includes('버튼을 누르세요')"));
  await screenshot('comparison.png');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  checks.checks.no_mobile_overflow=await evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth');
  await screenshot('mobile.png');
  checks.passed=Object.values(checks.checks).every(Boolean)&&checks.page_errors.length===0&&checks.external_requests.length===0;
  if(!checks.passed)throw Error('Browser assertions failed');
})().catch(error=>{checks.error=error.message;process.exitCode=1;}).finally(async()=>{
  if(socket)socket.close();
  for(const child of [browser,server])if(child&&child.exitCode===null&&child.signalCode===null){child.kill('SIGTERM');await until(()=>child.exitCode!==null||child.signalCode!==null,5000).catch(()=>child.kill('SIGKILL'));}
  fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify(checks,null,2),{flag:'wx'});
  console.log(JSON.stringify({output,...checks},null,2));
  // Keep the unique temporary profile for diagnosis; never delete a user's browser profile.
});
