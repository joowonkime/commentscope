// Dependency-free DOM contract smoke test, NOT a browser/layout test.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.listeners={}; this.textContent=''; this.value=''; this.hidden=false; this.disabled=false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  addEventListener(event, fn) { this.listeners[event]=fn; }
  set innerHTML(_) { throw new Error('Unsafe HTML sink'); }
  focus() {}
}
const text = n => n.textContent + n.children.map(text).join('');
const elements = n => [n, ...n.children.flatMap(elements)];
const settle = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  const ids = Object.fromEntries(['profiles','scope','metadata','rounds','ask','reset','export-html','export-json',
    'remaining','progress','error','reconnect','question','counter','question-form'].map(id => [id,new Element('div')]));
  const source = {evidence_id:'A-0', original_text:'<img src=x onerror=alert(1)>', reviewer_reading_ko:'review', cautions_ko:'caution',
    source_url:'javascript:alert(1)', parent_context:{text:null,comment_id:null}};
  const state = {bundle:{agents:[{agent_id:'A',title:'관점 A',constraints:['own evidence'],evidence:[source]}],
    dataset:{sample_size:1000,reviewed_sources:21},non_agents:[],expires_at:'2099-01-01'},
    runtime:{model:'synthetic'},rounds:[],job:{status:'idle'},can_ask:true,remaining_questions:6};
  const requests=[];
  const env={document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag),querySelectorAll:()=>[]},
    URL,crypto:{randomUUID:()=> 'unique-1'},confirm:()=>true, setTimeout:()=>1,clearTimeout:()=>{},
    fetch:async (route,options)=>{requests.push({route,options}); return {ok:true,json:async()=>({...state,token:'test-session'})};}};
  const context=vm.createContext(env);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/commentscope/agents/comparison.js'),'utf8'),context);
  return {ids,state,source,requests,context};
}

test('initial profile loads; untrusted text stays text and unsafe URL is omitted',async()=>{
  const h=harness(); await settle();
  assert.equal(h.ids.ask.disabled,false);
  assert.match(text(h.ids.profiles),/<img src=x onerror=alert\(1\)>/);
  assert.equal(elements(h.ids.profiles).filter(n=>n.tagName==='a').length,0);
  assert.match(text(h.ids.metadata),/1000/);
});

test('submit uses session header; status polling renders only published citations',async()=>{
  const h=harness(); await settle();
  h.ids.question.value='a question';
  h.state.job={status:'running',request_id:'unique-1',agent_id:'A',stage:'auditing',model_calls:2};
  h.state.can_ask=false;
  await h.ids['question-form'].listeners.submit({preventDefault(){}});
  const req=h.requests.at(-1);
  assert.equal(req.route,'/api/ask');
  assert.equal(req.options.headers['X-Session-Token'],'test-session');
  assert.deepEqual(JSON.parse(req.options.body),{question:'a question',request_id:'unique-1'});
  assert.equal(h.ids.question.value,'');
  assert.equal(h.ids.ask.disabled,true);
  assert.match(text(h.ids.progress),/인용 원문 검사/);
  h.state.can_ask=true; h.state.job={status:'done'}; h.state.remaining_questions=5;
  h.state.rounds=[{question:'a question',answers:[{agent_id:'A',status:'model_audit_passed_development_only',
    points:[{text:'published point',citation:h.source}],answerability:'partial',generation_attempts:2,audit_requests:3,
    attempts:[{raw:'SECRET_REJECTED'}],model_reported_limit:'SECRET_LIMIT'}]}];
  await vm.runInContext('refresh()',h.context);
  assert.match(text(h.ids.rounds),/published point/);
  assert.doesNotMatch(text(h.ids.rounds),/SECRET/);
  assert.equal(h.ids['export-json'].disabled,false);
});

test('abstention and reset remain distinct from a successful answer',async()=>{
  const h=harness(); await settle();
  h.state.rounds=[{question:'test',answers:[{agent_id:'A',status:'abstain',reason:'generation_or_contract_error',
    points:[],generation_attempts:1,audit_requests:0}]}];
  await vm.runInContext('refresh()',h.context);
  assert.match(text(h.ids.rounds),/모델 연결/);
  h.state.rounds=[];
  await h.ids.reset.listeners.click();
  assert.equal(h.requests.at(-1).route,'/api/reset');
  assert.match(text(h.ids.rounds),/질문을 보내면/);
});
