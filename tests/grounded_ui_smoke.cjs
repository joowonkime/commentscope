// DOM contract only, not a browser/layout test.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.textContent=''; this.value=''; }
  append(...items) { this.children.push(...items); }
  prepend(...items) { this.children.unshift(...items); }
  replaceChildren(...items) { this.children=items; }
  querySelectorAll() { return all(this).filter(n=>n.tagName==='input'&&n.checked); }
  set innerHTML(_) { throw new Error('Unsafe HTML'); }
}
const all = n => [n,...n.children.flatMap(all)];
const text = n => n.textContent+n.children.map(text).join('');
const settle = () => new Promise(resolve=>setImmediate(resolve));
function harness() {
  const ids=Object.fromEntries(['status','profiles','select','ask','question','submit','rounds','source','deferred','initial-opinion'].map(id=>[id,new Element('div')]));
  const state={profiles:[{candidate_id:'A',model_core_support_count:3,prompt_entries:[{text:'<script>not executable</script>',kind:'value'}]}],
    selected:['A'],deferred:[],rounds:[],remaining_questions:6,can_ask:true,job:'idle'};
  const requests=[];
  const context=vm.createContext({URL,crypto:{randomUUID:()=> 'q1'},setTimeout:()=>1,
    document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag)},
    fetch:async(route,options)=>{requests.push({route,options});return {ok:true,json:async()=>route==='/api/source'?{text:'<img onerror=evil> source'}:{...state,token:'session'}};}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/commentscope/agents/grounded.js'),'utf8'),context);
  return {ids,state,requests,context};
}
test('profile strings are text and no-quality-approval UI retains support count',async()=>{
  const h=harness();await settle();
  assert.match(text(h.ids.profiles),/<script>not executable/);
  assert.match(text(h.ids.profiles),/3개 \(모델 판정\)/);
  assert.equal(h.ids.submit.disabled,false);
});
test('question and follow-up use same session and unanswerable stays abstention',async()=>{
  const h=harness();await settle();h.ids.question.value='Why?';
  await h.ids.ask.onsubmit({preventDefault(){}});
  assert.equal(h.requests.at(-1).options.headers['X-Session-Token'],'session');
  assert.equal(JSON.parse(h.requests.at(-1).options.body).question,'Why?');
  h.state.rounds=[{question:'Why?',answers:[{candidate_id:'A',status:'abstain',points:[],required_premises:[],result:{raw:'HIDDEN'}}]}];
  await vm.runInContext('poll()',h.context);
  assert.match(text(h.ids.rounds),/보류/);assert.doesNotMatch(text(h.ids.rounds),/HIDDEN/);
});
test('source inspection uses bounded API and rejected raw text is never rendered',async()=>{
  const h=harness();await settle();
  h.state.rounds=[{question:'Position?',answers:[{candidate_id:'A',status:'answered',required_premises:[],result:{raw:'SECRET'},
    points:[{text:'Position',epistemic_status:'attributed_value_not_verified_fact',member_source_count:3,
      citations:{comment_evidence:[{source_id:'id'}],verification_evidence:[{title:'Unsafe',url:'javascript:alert(1)'}]}}]}]}];
  await vm.runInContext('poll()',h.context);
  assert.equal(all(h.ids.rounds).filter(n=>n.tagName==='a').length,0);
  assert.doesNotMatch(text(h.ids.rounds),/SECRET/);
  await all(h.ids.rounds).find(n=>n.tagName==='button').onclick();
  assert.equal(h.ids.source.textContent,'id\n<img onerror=evil> source');
  assert.match(text(h.ids.rounds),/댓글의 가치 판단/);
  assert.doesNotMatch(text(h.ids.rounds),/attributed_value_not_verified_fact/);
});
