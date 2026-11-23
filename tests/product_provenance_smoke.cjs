// DOM contract test for rendered provenance; no layout or model-quality claim.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
class Element {
  constructor(tag,text=''){this.tagName=tag;this.textContent=text;this.children=[];}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  set innerHTML(_){throw new Error('Unsafe HTML sink');}
}
const flatten=n=>[n,...n.children.flatMap(flatten)];
const text=n=>n.textContent+n.children.map(text).join('');
const appSource = fs.readFileSync(path.join(__dirname,'../src/commentscope/product/mvp.js'),'utf8');
const html = fs.readFileSync(path.join(__dirname,'../src/commentscope/product/mvp.html'),'utf8');
const koreanCopy = JSON.parse(html.match(/<script type="application\/json" id="interface-copy">([\s\S]*?)<\/script>/)[1]);
function installUiStrings(context, language) {
  context.koreanInterface = koreanCopy;
  context.interfaceLanguage = language;
  vm.runInContext(appSource.slice(appSource.indexOf('function msg('),appSource.indexOf('function uiTextNode(')),context);
  vm.runInContext(appSource.slice(appSource.indexOf('function interfaceNotice('),appSource.indexOf('function asset(')),context);
  context.setText = (element,value) => { element.textContent = context.formatText(value); };
}
function render(points,extra={}){
  const js=fs.readFileSync(path.join(__dirname,'../src/commentscope/product/mvp.js'),'utf8');
  const container=new Element('div');
  const context=vm.createContext({URL,state:{room:{messages:[{author_kind:'agent',agent_id:'P1',message_id:'M1',points,...extra}]}},
    $:()=>container,avatar:()=>new Element('img'),label:()=> 'Perspective 1',source:()=>{},perspective:()=>({core_claim_id:'claim',text:'Registered stance',source_ids:['c1']})});
  installUiStrings(context, 'ko');
  context.node = (tag,value) => new Element(tag,context.formatText(value));
  vm.runInContext(js.slice(js.indexOf('function sourceButtons('),js.indexOf('// API span offsets')),context);
  vm.runInContext(js.slice(js.indexOf('function renderMessages('),js.indexOf('async function refreshRoom(')),context);
  vm.runInContext('renderMessages()',context);return container;
}
test('comment, proposed reasoning and external evidence keep distinct labels and links',()=>{
  const result=render([
    {origin:'original_comment',text:'Original stance',citations:{comment_evidence:[{source_id:'c1'}]}},
    {origin:'ai_reasoning',text:'<img src=x onerror=alert(1)>',citations:{comment_evidence:[]}},
    {origin:'external_evidence',text:'Bound report finding',citations:{external_evidence:[
      {url:'https://example.invalid/report',title:'Prepared report',text:'Exact passage'}]}}
  ]);
  assert.match(text(result),/댓글 근거/);assert.match(text(result),/AI 추론/);assert.match(text(result),/외부 자료 기반/);
  assert.match(text(result),/<img src=x onerror=alert\(1\)>/);
  const links=flatten(result).filter(n=>n.tagName==='a');assert.equal(links.length,1);
  assert.equal(links[0].href,'https://example.invalid/report');assert.equal(links[0].title,'Exact passage');
  assert.equal(links[0].rel,'noopener noreferrer');
  assert.equal(flatten(result).filter(n=>n.tagName==='button').length,1);
});
test('unsafe schemes and credential URLs never become external links',()=>{
  const result=render([{origin:'external_evidence',text:'Visible text',citations:{external_evidence:[
    {url:'javascript:alert(1)'},{url:'https://user:secret@example.invalid/'},{url:'not a URL'}]}}]);
  assert.equal(flatten(result).filter(n=>n.tagName==='a').length,0);
});

test('a held live response links its registered stance separately and an expired response does not',()=>{
  const held=render([],{evidence_scope:'seeded_provenance',status:'abstain',limitation:'verification_hold'});
  const detail=flatten(held).find(n=>n.tagName==='details');
  assert.match(text(held),/답변을 검증하지 못/);
  assert.match(text(detail),/기존 입장.*Registered stance/);
  assert.equal(flatten(detail).filter(n=>n.tagName==='button').length,1);
  const expired=render([],{evidence_scope:'expired',status:'abstain'});
  assert.ok(!flatten(expired).some(n=>n.tagName==='details'));
});

test('explanatory abstention is visible even when checked paragraphs are present',()=>{
  const result=render([{origin:'external_evidence',text:'A limited study is not a universal guarantee.'}],{status:'abstain',answerability:'abstain'});
  assert.match(text(result),/요청한 답을 확인할 수 없어/);
  assert.match(text(result),/A limited study/);
});

async function restoreRoom(navigateWhileLoading) {
  const js = fs.readFileSync(path.join(__dirname, '../src/commentscope/product/mvp.js'), 'utf8');
  const document = {body: {dataset: {step: 'before'}}};
  const state = {session: {rooms: [{room_id: 'room-1'}]}};
  let finish;
  const loading = new Promise(resolve => { finish = resolve; });
  const context = vm.createContext({
    document, state,
    setRoom: room => { state.room = room; },
    refreshRoom: () => loading,
    showStep: step => { document.body.dataset.step = step; },
  });
  vm.runInContext(js.slice(js.indexOf('async function chooseRoom('), js.indexOf('function renderRooms(')), context);
  const restore = vm.runInContext('chooseRoom("room-1")', context);
  if (navigateWhileLoading) document.body.dataset.step = 'reflect';
  finish();
  await restore;
  assert.equal(state.room.room_id, 'room-1');
  return document.body.dataset.step;
}

test('a restored discussion does not override a later navigation to Reflect', async () => {
  assert.equal(await restoreRoom(true), 'reflect');
});

test('a discussion still opens when the user stays on the loading step', async () => {
  assert.equal(await restoreRoom(false), 'converse');
});

function memoryStorage() {
  const entries = new Map();
  return {
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, String(value)),
    removeItem: key => entries.delete(key),
  };
}

function browserTab(sharedStorage = memoryStorage(), api = undefined) {
  const context = vm.createContext({crypto: require('node:crypto').webcrypto, api, btoa, TextEncoder,
    sessionStorage: memoryStorage(), localStorage: sharedStorage, lastRoomKey: 'last-room'});
  vm.runInContext(appSource.slice(0, appSource.indexOf('function node(')), context);
  vm.runInContext(appSource.slice(appSource.indexOf('async function retryableWrite('), appSource.indexOf('function indexOf(')), context);
  vm.runInContext(appSource.slice(appSource.indexOf('function readStored('), appSource.indexOf('function availableAnalysis(')), context);
  return context;
}

test('retrying a lost write reuses its request ID and session credential until acknowledged', async () => {
  const cases = [
    ['begin', '/sessions', 'POST'], ['chat', '/sessions/S/rooms', 'POST'],
    ['chat', '/synthesis-agents/A/rooms', 'POST'], ['initial', '/sessions/S/opinions/initial', 'PUT'],
    ['current', '/sessions/S/opinions/current', 'PUT'], ['reflection', '/sessions/S/reflections', 'POST'],
    ['reflection', '/sessions/S/reflections/R', 'PUT'],
  ];
  for (const [slot, path, method] of cases) {
    const attempts = [];
    const tab = browserTab(undefined, async (_path, _method, fields, token) => {
      attempts.push({id: fields.request_id, token});
      if (attempts.length === 1) throw Error('response lost');
      return 'acknowledged';
    });
    const key = 'commentscope-mvp-pending-' + slot;
    const write = vm.runInContext('retryableWrite', tab);
    const fields = {text: 'a private draft'};
    await assert.rejects(write(slot, path, method, fields), /response lost/);
    assert.ok(tab.sessionStorage.getItem(key));
    assert.ok(!tab.sessionStorage.getItem(key).includes(fields.text));
    assert.equal(await write(slot, path, method, fields), 'acknowledged');
    assert.deepEqual(attempts[1], attempts[0]);
    assert.equal(tab.sessionStorage.getItem(key), null);
    if (path === '/sessions') assert.match(attempts[0].token, /^[A-Za-z0-9_-]{43}$/);
    await write(slot, path, method, fields);
    assert.notEqual(attempts[2].id, attempts[0].id);
  }
});

test('a changed pending opinion starts a distinct write', async () => {
  const attempts = [];
  const tab = browserTab(undefined, async (_path, _method, fields) => {
    attempts.push(fields.request_id);
    throw Error('response lost');
  });
  const write = vm.runInContext('retryableWrite', tab);
  for (const text of ['first draft', 'second draft', 'second draft']) {
    await assert.rejects(write('current', '/opinions/current', 'PUT', {text}), /response lost/);
  }
  assert.notEqual(attempts[0], attempts[1]);
  assert.equal(attempts[1], attempts[2]);
});

test('a lost follow-up preserves the first room revision, then permits a deliberate repeat', async () => {
  const attempts = [];
  const tab = browserTab(undefined, async (_path, _method, payload) => {
    attempts.push({...payload});
    if (attempts.length === 1) throw Error('response lost');
  });
  const write = vm.runInContext('retryableWrite', tab);
  let preparations = 0;
  const send = target => write('message-R', '/rooms/R/messages', 'POST', {text:'Why?', target_agent_id:target},
    async () => 8 + 4 * preparations++);
  await assert.rejects(send('first'), /response lost/);
  await send('first');
  assert.equal(preparations, 1);
  assert.deepEqual(attempts[0], attempts[1]);
  assert.equal(attempts[1].expected_revision, 8);
  await send('first');
  await send('second');
  assert.equal(preparations, 3);
  assert.notEqual(attempts[2].request_id, attempts[1].request_id);
  assert.equal(attempts[2].expected_revision, 12);
  assert.equal(attempts[3].target_agent_id, 'second');
});

test('a confirmed room revision conflict lets the next send prepare against the current room', async () => {
  const attempts = [];
  const tab = browserTab(undefined, async (_path, _method, payload) => {
    attempts.push({...payload});
    if (attempts.length === 1) throw Object.assign(Error('room changed'), {code:'revision_conflict'});
  });
  const write = vm.runInContext('retryableWrite', tab);
  const send = () => write('message-R', '/rooms/R/messages', 'POST', {text:'Why?'}, async () => attempts.length + 1);
  await assert.rejects(send(), /room changed/);
  await send();
  assert.notEqual(attempts[1].request_id, attempts[0].request_id);
  assert.equal(attempts[1].expected_revision, 2);
});

test('independent tabs restore their own reviews and the shared Library retains both', () => {
  const shared = memoryStorage();
  const first = browserTab(shared), second = browserTab(shared);
  first.rememberSession('first', 'one');
  assert.equal(second.activeAccess().session_id, 'first');
  second.rememberSession('second', 'two');
  assert.equal(first.activeAccess().session_id, 'first');
  assert.equal(second.activeAccess().session_id, 'second');
  first.leaveSession();
  assert.equal(first.activeAccess(), null);
  assert.equal(second.activeAccess().session_id, 'second');
  assert.equal(browserTab(shared).activeAccess().session_id, 'second');
  assert.deepEqual(Array.from(first.browserRecords(), record => record.session_id).sort(), ['first', 'second']);
});

test('restoring a saved reflection clears the startup message and preserves newer feedback', async () => {
  const session = {analysis: {}, analysis_id: 'analysis', reflections: [{reflection_id: 'reflection'}]};
  const elements = new Map();
  const document = {body: {dataset: {step: 'before'}}, querySelectorAll: () => []};
  const context = vm.createContext({
    state: {}, selectedAnalysisKey: 'analysis', sessionStorage: memoryStorage(), document,
    $: id => {
      if (!elements.has(id)) elements.set(id, {});
      return elements.get(id);
    },
    setSession() {}, renderAnalysis() {}, renderPerspectives() {},
    showStep: step => { document.body.dataset.step = step; },
  });
  installUiStrings(context, 'en');
  vm.runInContext(appSource.slice(appSource.indexOf('function status('), appSource.indexOf('function errorText(')), context);
  vm.runInContext(appSource.slice(appSource.indexOf('async function enter('), appSource.indexOf("$('initial').oninput")), context);
  context.status('Loading the registered discussion…');
  let complete;
  context.openSavedReflection = () => new Promise(resolve => { complete = resolve; });
  const restore = context.enter(session, {reflection_id: 'reflection'});
  assert.equal(document.body.dataset.step, 'reflect');
  assert.equal(context.$('status').textContent, '');
  context.status('A newer action is in progress');
  complete();
  await restore;
  assert.equal(context.$('status').textContent, 'A newer action is in progress');
});

test('generated evidence aliases explain the registered claim without renumbering original comments', () => {
  const citations = {anchor_claim_ids: ['claim'], comment_evidence: [{source_id: 'comment'}]};
  const point = {origin: 'ai_reasoning', text: 'E1 supports the pilot.', citations};
  const message = render([point], {evidence_scope: 'seeded_provenance'});
  assert.match(text(message), /E1 · 참조한 주장/);
  assert.match(text(flatten(message).find(n => n.tagName === 'details')), /Registered stance/);
  assert.match(text(message), /E1 supports the pilot\./);
  assert.equal(flatten(message).filter(n => n.tagName === 'button').length, 1);
  assert.doesNotMatch(text(render([{...point, origin: 'original_comment'}], {evidence_scope: 'seeded_provenance'})), /참조한 주장/);
  assert.doesNotMatch(text(render([{...point, citations: {}}], {evidence_scope: 'seeded_provenance'})), /참조한 주장/);
});
