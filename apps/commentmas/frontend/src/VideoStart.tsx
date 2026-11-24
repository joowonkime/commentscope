import {useEffect, useRef, useState, type FormEvent} from 'react';
import {request, RequestError} from './api';
import {videoThumbnail, type Catalog} from './types';

type Video = Catalog['video'];
type Options = {demo:Video|null; can_generate:boolean; comment_limit:number};
type Job = {video_id:string; status:'running'|'failed'|'ready'; stage?:string; elapsed_seconds?:number; error?:string};

const stages = [
  {id:'collecting', label:'Collecting public comments'},
  {id:'filtering', label:'Finding comments with a viewpoint'},
  {id:'grouping', label:'Grouping related perspectives'},
  {id:'creating_agents', label:'Creating agents from supporting comments'},
  {id:'preparing_cards', label:'Preparing perspective cards'},
];
const videoLink = (id:string) => '?video=' + encodeURIComponent(id);
const watchLink = (id:string) => 'https://www.youtube.com/watch?v=' + id;

function PreparationProgress({job, checkingUrl}:{job:Job|null; checkingUrl:boolean}) {
  const index = stages.findIndex(stage=>stage.id===job?.stage);
  const current = stages[index];
  const step = current && `Step ${index+1} of ${stages.length}`;
  const label = current?.label ?? (checkingUrl ? 'Checking video…' : 'Checking preparation…');
  const elapsed = job?.elapsed_seconds;

  return <div className="preparation-progress">
    <div className="preparation-heading">
      <div role="status" aria-atomic="true">
        {current && <span className="preparation-step">{step}</span>}
        <strong>{label}</strong>
      </div>
      {elapsed !== undefined && <span className="preparation-time" role="timer" aria-live="off">
        Elapsed {Math.floor(elapsed/60)}:{String(elapsed%60).padStart(2,'0')}
      </span>}
    </div>
    <div className="preparation-track" role="progressbar" aria-label="Agent generation progress"
      aria-valuemin={0} aria-valuemax={stages.length} aria-valuenow={current ? index : undefined}
      aria-valuetext={current ? `${step}. ${label}.` : undefined}>
      {current ? stages.map((stage,i)=><span key={stage.id} aria-hidden="true"
        data-state={i<index ? 'done' : i===index ? 'current' : undefined}/>)
        : <span aria-hidden="true" data-state="current"/>}
    </div>
    {!checkingUrl && <p>Preparing a new video can take a few minutes. You can refresh this page to check progress.</p>}
  </div>;
}

export default function VideoStart() {
  const resume = new URLSearchParams(location.search).get('prepare');
  const [url,setUrl] = useState(resume ? watchLink(resume) : '');
  const [options,setOptions] = useState<Options|null>(null);
  const [loadError,setLoadError] = useState('');
  const [reload,setReload] = useState(0);
  const [pollId,setPollId] = useState<string|null>(resume);
  const [pollError,setPollError] = useState(false);
  const [job,setJob] = useState<Job|null>(null);
  const [error,setError] = useState('');
  const [submitting,setSubmitting] = useState(false);
  const sending = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        let info:Options;
        try {
          info = await request<Options>('/videos',undefined,'GET',controller.signal);
        } catch (e) {
          if (!(e instanceof RequestError && e.status === 404)) throw e;
          // An older backend still serves the original prepared presentation during a rollout.
          const catalog = await request<Catalog>('/bootstrap',undefined,'GET',controller.signal);
          info = {demo:catalog.video,can_generate:false,comment_limit:0};
        }
        if (!controller.signal.aborted) {setOptions(info);setLoadError('');}
      } catch (e) {
        if (!controller.signal.aborted) setLoadError((e as Error).message);
      }
    }
    void load();
    return () => controller.abort();
  },[reload]);

  useEffect(() => {
    if (!pollId || pollError) return;
    const controller = new AbortController();
    let timer:number;
    async function check() {
      try {
        const result = await request<Job>('/videos/'+encodeURIComponent(pollId!),undefined,'GET',controller.signal);
        if (controller.signal.aborted) return;
        setJob(result);
        if (result.status === 'ready') {location.replace(videoLink(result.video_id));return;}
        if (result.status === 'failed') {
          setError(result.error || 'Preparation failed. Try again.');
          setPollId(null);
          return;
        }
        timer = window.setTimeout(check,1800);
      } catch (e) {
        if (controller.signal.aborted) return;
        setError((e as Error).message);
        if (e instanceof RequestError && [400,404].includes(e.status)) setPollId(null);
        else setPollError(true);
      }
    }
    void check();
    return () => {controller.abort();window.clearTimeout(timer);};
  },[pollId,pollError]);

  async function submit(event:FormEvent) {
    event.preventDefault();
    if (sending.current || !url.trim()) return;
    sending.current = true;
    setSubmitting(true);setError('');setJob(null);
    try {
      const result = await request<Job>('/videos',{url:url.trim()});
      if (result.status === 'ready') {location.assign(videoLink(result.video_id));return;}
      if (result.status === 'failed') {setError(result.error || 'Preparation failed. Try again.');return;}
      history.replaceState(null,'','?prepare='+encodeURIComponent(result.video_id));
      setJob(result);setPollError(false);setPollId(result.video_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {sending.current=false;setSubmitting(false);}
  }

  return <main className="video-start">
    <header className="wordmark"><img src="/assets/perspectiveglyph.svg" width="32" height="32" alt=""/>Re.View</header>
    <section className="video-intake" aria-labelledby="choose-video">
      <h1 id="choose-video">Explore a YouTube discussion</h1>
      <p>Choose a video to turn perspectives in its comments into agents you can talk to.</p>
      <form onSubmit={submit}>
        <label htmlFor="video-url">YouTube video URL</label>
        <input id="video-url" type="text" inputMode="url" autoComplete="url" placeholder="https://www.youtube.com/watch?v=…"
          value={url} onChange={e=>setUrl(e.target.value)} maxLength={2048} disabled={!!pollId || submitting} required/>
        {options?.can_generate && <small>New videos use up to {options.comment_limit} comments, including replies. Previously prepared videos open immediately.</small>}
        {options && !options.can_generate && <small>New video generation is unavailable on this server. Open a prepared video to continue.</small>}
        {!pollId && <button className="primary" disabled={!url.trim() || submitting || !options || (!options.can_generate && !options.comment_limit)}>
          {submitting?'Checking video…':options?.can_generate?'Generate agents':'Open video'}</button>}
      </form>
      {(submitting || pollId) && !pollError && <PreparationProgress job={job} checkingUrl={!pollId}/>}
      {loadError && <div role="alert">{loadError} <button className="text-button" onClick={()=>setReload(n=>n+1)}>Reload video options</button></div>}
      {error && <div className="intake-error" role="alert">{error} {pollError &&
        <button className="text-button" onClick={()=>{setError('');setPollError(false);}}>Check progress</button>}</div>}
      {pollId && <a className="intake-reset" href="/">Choose another video</a>}
    </section>
    {options?.demo && <section className="prepared-video" aria-label="Prepared example">
      <img src={videoThumbnail(options.demo.video_id)} alt=""/>
      <div><p>Prepared example</p><h2>{options.demo.title}</h2>
        <a className="video-choice-link" href={videoLink(options.demo.video_id)}>Open prepared video <span aria-hidden="true">→</span></a>
      </div>
    </section>}
  </main>;
}
