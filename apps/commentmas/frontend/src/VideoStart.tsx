import {useEffect, useRef, useState, type FormEvent} from 'react';
import {request, RequestError} from './api';
import {Spinner} from './components';
import {videoThumbnail, type Catalog} from './types';

type Video = Catalog['video'];
type Options = {demo:Video|null; can_generate:boolean; comment_limit:number};
type Job = {video_id:string; status:'running'|'failed'|'ready'; stage?:string; error?:string};

const stages:Record<string,string> = {
  collecting:'Collecting public comments',
  filtering:'Finding comments with a viewpoint',
  grouping:'Grouping related perspectives',
  creating_agents:'Creating agents from supporting comments',
  preparing_cards:'Preparing perspective cards',
};
const videoLink = (id:string) => '?video=' + encodeURIComponent(id);
const watchLink = (id:string) => 'https://www.youtube.com/watch?v=' + id;

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
      {pollId && !pollError && <Spinner label={(job?.stage && stages[job.stage]) || 'Checking preparation…'}/>}
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
