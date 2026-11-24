import {useEffect,useRef,useState} from 'react';
import {accountKey,request,task} from './api';
import {Avatar,Spinner} from './components';
import type {Catalog,ReflectionAnalysis,ReflectionCategory,RoomSummary} from './types';

// Figma: "Redesign · User Feedback 11.18" → 03 · Reflect / Write your view, 04 · Reflect / Review your changes.
const CATEGORIES:{key:ReflectionCategory;tab:string;eyebrow:string}[]=[
  {key:'stayed',tab:'Stayed',eyebrow:'STAYED'},
  {key:'changed',tab:'Changed',eyebrow:'CHANGED'},
  {key:'new',tab:'New considerations',eyebrow:'NEW CONSIDERATION'},
  {key:'open',tab:'Open questions',eyebrow:'OPEN QUESTION'},
];
const PROMPTS=['What I still believe','What I see differently','A question I still have'];
type Feedback=Record<number,{verdict:'fits'|'not'|null;title?:string;explanation?:string}>;
interface Stored {current:string;basis?:{initial:string;current:string};analysis?:ReflectionAnalysis;feedback?:Feedback;saved_at?:string}

interface Props {catalog:Catalog;rooms:RoomSummary[];initial:string;onOpenRoom:(id:string)=>void;onMoment:(room:string,message:string)=>void;onEditInitial:()=>void;onConverse:()=>void}

export default function Reflect({catalog,rooms,initial,onOpenRoom,onMoment,onEditInitial,onConverse}:Props){
  const key=accountKey()==='local'?`review:${catalog.fingerprint}:reflection`:`review:${accountKey()}:${catalog.fingerprint}:reflection`;
  const [stored,setStored]=useState<Stored>(()=>{try{return JSON.parse(localStorage.getItem(key)||'')}catch{return {current:''};}});
  // Reflect always opens on the writing page; an unchanged view reopens its saved analysis instantly.
  const [phase,setPhase]=useState<'write'|'review'>('write');
  const [pending,setPending]=useState(false),[error,setError]=useState('');
  useEffect(()=>{try{localStorage.setItem(key,JSON.stringify(stored));}catch{/* drafts still work for this visit */}},[key,stored]);
  const update=(patch:Partial<Stored>)=>setStored(old=>({...old,...patch}));
  async function review(){
    const current=stored.current.trim();if(!current||pending)return;
    if(stored.analysis&&stored.basis?.initial===initial&&stored.basis?.current===current){setPhase('review');return;}
    setPending(true);setError('');
    try{const analysis=await task<ReflectionAnalysis>('/reflect',{initial_opinion:initial,current_view:current});update({analysis,basis:{initial,current},feedback:{},saved_at:undefined});setPhase('review');window.scrollTo(0,0);}
    catch(e){setError((e as Error).message);}finally{setPending(false);}
  }
  const active=rooms.filter(r=>r.message_count>0);
  return phase==='write'||!stored.analysis
    ?<WriteView catalog={catalog} rooms={active} initial={initial} value={stored.current} onChange={current=>update({current})} onReview={()=>void review()} pending={pending} error={error} onOpenRoom={onOpenRoom} onEditInitial={onEditInitial} onConverse={onConverse}/>
    :<ReviewView initial={initial} current={stored.current} analysis={stored.analysis} feedback={stored.feedback??{}} savedAt={stored.saved_at}
      onFeedback={feedback=>update({feedback,saved_at:undefined})} onSaved={saved_at=>update({saved_at})} onEdit={()=>{setPhase('write');window.scrollTo(0,0);}} onMoment={onMoment}/>;
}

function WriteView({catalog,rooms,initial,value,onChange,onReview,pending,error,onOpenRoom,onEditInitial,onConverse}:{catalog:Catalog;rooms:RoomSummary[];initial:string;value:string;onChange:(v:string)=>void;onReview:()=>void;pending:boolean;error:string;onOpenRoom:(id:string)=>void;onEditInitial:()=>void;onConverse:()=>void}){
  const editor=useRef<HTMLTextAreaElement>(null);
  const titles=Object.fromEntries(catalog.agents.map(a=>[a.agent_id,a.title]));
  function prompt(label:string){const lead=value.trim()?value.replace(/\s+$/,'')+'\n\n':'';const next=`${lead}${label}: `;onChange(next);requestAnimationFrame(()=>{const el=editor.current;if(el){el.focus();el.setSelectionRange(next.length,next.length);}});}
  return <main className="reflect"><div className="reflect-title"><p className="eyebrow">STEP 03 · REFLECTION ON ONE'S OWN VIEWPOINT</p><h1>What do you think now?</h1><p>After exploring different views, write what you believe now. You can keep your original opinion, revise it, or add a new consideration. There is no right answer.</p></div>
    <div className="reflect-columns"><section className="reflect-context">
      <h2 className="reflect-label">📌 YOUR INITIAL VIEW</h2>
      <div className="initial-box"><p>{initial}</p><button className="inline-link" onClick={onEditInitial}>Edit initial view</button></div>
      <h2 className="reflect-label conversations-label">💬 YOUR CONVERSATIONS</h2>
      <p className="reflect-help">The system will read these together with your initial and current views.</p>
      <div className="reflect-rooms">{rooms.map(r=>{const group=r.participants.length>1;return <button key={r.room_id} className="reflect-room" onClick={()=>onOpenRoom(r.room_id)} title="Open this conversation"><span className={`room-avatars ${group?'group':''}`}>{r.participants.slice(0,3).map(id=><Avatar key={id} id={id} size={32}/>)}</span><span className="room-text"><strong>{group?`Group chat · ${r.participants.length} agents`:`1:1 · ${titles[r.participants[0]]}`}</strong><small>{r.message_count} messages · {group&&!r.title?r.participants.map(id=>titles[id]).join(', '):r.title}</small></span></button>;})}
        {!rooms.length&&<div className="reflect-empty"><p>No conversations yet. You can still reflect on your view, or talk with the perspectives first.</p><button className="inline-link" onClick={onConverse}>Go to conversations →</button></div>}</div>
    </section>
    <section className="reflect-write"><h2 className="reflect-label">✍️ YOUR CURRENT VIEW</h2>
      <div className="reflect-editor"><textarea ref={editor} aria-label="Your current view" maxLength={12000} placeholder="Write what you believe now, in your own words." value={value} onChange={e=>onChange(e.target.value)}/>
        <div className="reflect-prompts"><strong>NEED A STARTING POINT?</strong><p>Optional prompts. Your own words come first.</p><div>{PROMPTS.map(p=><button key={p} type="button" onClick={()=>prompt(p)}>{p}</button>)}</div></div></div>
      {error&&<div className="inline-error" role="alert"><p>{error}</p></div>}
      <div className="reflect-actions">{pending&&<Spinner label="Reading your reflection and conversations…"/>}<button className="primary reflect-cta" disabled={!value.trim()||pending} onClick={onReview}>Review what changed <img src="/assets/rightarrow.svg" alt="" width="22" height="22"/></button></div>
    </section></div></main>;
}

function ReviewView({initial,current,analysis,feedback,savedAt,onFeedback,onSaved,onEdit,onMoment}:{initial:string;current:string;analysis:ReflectionAnalysis;feedback:Feedback;savedAt?:string;onFeedback:(f:Feedback)=>void;onSaved:(at:string)=>void;onEdit:()=>void;onMoment:(room:string,message:string)=>void}){
  const items=analysis.items.map((item,index)=>({...item,index,title:feedback[index]?.title??item.title,explanation:feedback[index]?.explanation??item.explanation}));
  const order=(c:ReflectionCategory)=>CATEGORIES.findIndex(x=>x.key===c);
  const sorted=[...items].sort((a,b)=>order(a.category)-order(b.category)||a.index-b.index);
  // Tabs pick a category; every item in it is shown as a full card, no collapsing.
  const [category,setCategory]=useState<ReflectionCategory>(()=>(sorted.find(i=>i.category==='changed')??sorted[0]).category);
  const [fullInitial,setFullInitial]=useState(false),[editing,setEditing]=useState<{index:number;title:string;explanation:string}|null>(null),[saving,setSaving]=useState(false),[error,setError]=useState('');
  const shown=sorted.filter(i=>i.category===category);
  const meta=CATEGORIES.find(c=>c.key===category)!;
  const setVerdict=(index:number,v:'fits'|'not')=>onFeedback({...feedback,[index]:{...feedback[index],verdict:feedback[index]?.verdict===v?null:v}});
  useEffect(()=>setEditing(null),[category]);
  async function save(){setSaving(true);setError('');try{const result=await request<{saved_at:string}>('/reflections',{initial_opinion:initial,current_view:current,analysis,feedback});onSaved(result.saved_at);}catch(e){setError((e as Error).message);}finally{setSaving(false);}}
  const chats=[analysis.one_to_one&&`${analysis.one_to_one} one-to-one chat${analysis.one_to_one>1?'s':''}`,analysis.group&&`${analysis.group} group discussion${analysis.group>1?'s':''}`].filter(Boolean).join(' + ');
  return <main className="reflect review"><div className="reflect-title"><p className="eyebrow">STEP 03 · REFLECTION ON ONE'S OWN VIEWPOINT</p><h1>Your reflection, in context</h1><p>These are AI-suggested observations based on what you wrote and discussed. Explore the links and decide which interpretations feel accurate.</p></div>
    <div className="review-columns"><aside className="review-view">
      <h2 className="review-label">YOUR VIEW</h2><p className="reflect-help">Your opinion stays in your own words. These excerpts help you compare where you began and where you are now.</p>
      <section className="view-card"><h3>BEFORE DISCUSSING</h3><p>{fullInitial?initial:`“${analysis.before_excerpt}”`}</p><button className="inline-link" onClick={()=>setFullInitial(!fullInitial)}>{fullInitial?'Show excerpt ↑':'Read full initial view →'}</button></section>
      <section className="view-card"><h3>AFTER DISCUSSING</h3><p>“{analysis.after_excerpt}”</p><button className="inline-link" onClick={onEdit}>Edit my current view →</button></section>
      {chats&&<p className="reflect-help">Your discussions: {chats}</p>}
    </aside>
    <section className="review-panel"><h2>Possible changes in your thinking</h2><p className="reflect-help">Select a theme to see related wording and conversation moments.</p>
      <div className="review-tabs" role="tablist">{CATEGORIES.map(c=>{const count=sorted.filter(i=>i.category===c.key).length;return <button key={c.key} role="tab" aria-selected={category===c.key} className={category===c.key?'active':''} disabled={!count} onClick={()=>setCategory(c.key)}>{c.tab} · {count}</button>;})}</div>
      <div className="review-items" role="tabpanel">{shown.map((item,n)=>{const verdict=feedback[item.index]?.verdict??null;const edit=editing?.index===item.index?editing:null;return <article key={item.index} className={`review-item ${item.category} ${verdict==='not'?'dismissed':''}`}>
        <p className="item-eyebrow">{meta.eyebrow} &nbsp;·&nbsp; {n+1} OF {shown.length}</p>
        {edit?<div className="item-edit"><input aria-label="Interpretation title" value={edit.title} onChange={e=>setEditing({...edit,title:e.target.value})}/><textarea aria-label="Interpretation" value={edit.explanation} onChange={e=>setEditing({...edit,explanation:e.target.value})}/><div><button className="primary small" disabled={!edit.title.trim()} onClick={()=>{onFeedback({...feedback,[item.index]:{...feedback[item.index],verdict:'fits',title:edit.title.trim(),explanation:edit.explanation.trim()}});setEditing(null);}}>Save interpretation</button><button className="text-button" onClick={()=>setEditing(null)}>Cancel</button></div></div>
          :<><h3>{item.title}</h3><p className="item-explanation">{item.explanation}</p></>}
        {(item.before_quote||item.now_quote)&&<div className="item-quotes"><div><span>BEFORE</span><p>{item.before_quote?`“${item.before_quote}”`:'Not in your initial view'}</p></div><div className="now"><span>NOW</span><p>{item.now_quote?`“${item.now_quote}”`:'Not in your current view'}</p></div></div>}
        {item.moment&&<div className="item-moment"><div><span>RELATED DISCUSSION &nbsp;·&nbsp; {item.moment.room_type.toUpperCase()}</span><button className="inline-link" onClick={()=>onMoment(item.moment!.room_id,item.moment!.message_id)}>View this moment →</button></div><p>{item.moment.speaker}: “{item.moment.quote}”</p>{item.moment.user_quote&&<p className="you">You: “{item.moment.user_quote}”</p>}</div>}
        <p className="item-question">{verdict==='not'?'Marked as not quite. It won’t be kept as part of your reflection.':'AI-suggested interpretation. Does this fit your experience?'}</p>
        <div className="item-actions"><button className={`pill-button ${verdict==='fits'?'filled':''}`} aria-pressed={verdict==='fits'} onClick={()=>setVerdict(item.index,'fits')}>{verdict==='fits'?'✓ This fits':'Yes, this fits'}</button><button className="pill-button" onClick={()=>setEditing({index:item.index,title:item.title,explanation:item.explanation})}>Edit interpretation</button><button className={`text-button ${verdict==='not'?'active':''}`} aria-pressed={verdict==='not'} onClick={()=>setVerdict(item.index,'not')}>{verdict==='not'?'Undo':'Not quite →'}</button></div>
      </article>;})}</div>
    </section></div>
    <footer className="review-footer">{error&&<p className="inline-error" role="alert">{error}</p>}{savedAt&&<p className="saved-note">Saved {new Date(savedAt).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'})}. You can come back and revise anytime.</p>}<button className="primary reflect-cta" disabled={saving} onClick={()=>void save()}>{saving?'Saving…':savedAt?'✓ Saved · Save again':'✓ Save my reflection'}</button></footer>
  </main>;
}
