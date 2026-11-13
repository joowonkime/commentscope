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
function render(points){
  const js=fs.readFileSync(path.join(__dirname,'../src/commentscope/product/mvp.js'),'utf8');
  const container=new Element('div');
  const context=vm.createContext({URL,state:{room:{messages:[{author_kind:'agent',agent_id:'P1',message_id:'M1',points}]}},
    $:()=>container,node:(tag,t)=>new Element(tag,t),avatar:()=>new Element('img'),label:()=> 'Perspective 1',source:()=>{}});
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
