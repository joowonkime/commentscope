import type {User} from 'firebase/auth';
let account:User|null=null;
export const accountKey=()=>account?.uid||'local';
export function setAccount(user:User|null){if(user?.uid!==account?.uid)tasks.clear();account=user;}
import type {Job} from './types';
export const selectedVideo = () => new URLSearchParams(location.search).get('video');
export class RequestError extends Error {
  constructor(message:string, public status:number) {super(message);}
}
export async function request<T>(path:string,body?:unknown,method=body?'POST':'GET',signal?:AbortSignal):Promise<T>{
  const uid=accountKey();
  const token=account?await account.getIdToken():null;
  const headers:Record<string,string>={};
  const video = selectedVideo();
  if (video && !path.startsWith('/videos')) headers['X-Review-Video'] = video;
  if(body)headers['Content-Type']='application/json';
  if(token)headers.Authorization=`Bearer ${token}`;
  const response=await fetch(`/api${path}`,{method,headers,body:body?JSON.stringify(body):undefined,signal});
  if(uid!==accountKey())throw new DOMException('Account changed','AbortError');
  const data=await response.json();
  if(!response.ok)throw new RequestError(data.error||'The request could not be completed.',response.status);
  return data;
}
export async function waitJob<T>(job:Job<T>,signal?:AbortSignal):Promise<T>{
  let current=job;
  while(current.status==='running'){
    await new Promise<void>((resolve,reject)=>{const timer=window.setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},700);const abort=()=>{window.clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();});
    current=await request<Job<T>>(`/jobs/${job.job_id}`,undefined,'GET',signal);
  }
  if(current.status==='failed')throw new Error(current.error||'The request failed. Please retry.');
  return current.result as T;
}
const tasks=new Map<string,Promise<unknown>>();
export async function task<T>(path:string,body:Record<string,unknown>,signal?:AbortSignal):Promise<T>{
  const key=JSON.stringify([accountKey(),selectedVideo(),path,body]);
  if(!tasks.has(key)){
    const promise=request<Job<T>>(path,{...body,request_id:crypto.randomUUID()}).then(job=>waitJob(job));
    tasks.set(key,promise);
    promise.catch(()=>tasks.delete(key));
  }
  const pending=tasks.get(key) as Promise<T>;
  if(!signal)return pending;
  return new Promise<T>((resolve,reject)=>{
    const abort=()=>reject(new DOMException('Aborted','AbortError'));
    signal.addEventListener('abort',abort,{once:true});
    if(signal.aborted)abort();
    pending.then(value=>{signal.removeEventListener('abort',abort);if(!signal.aborted)resolve(value);},error=>{signal.removeEventListener('abort',abort);reject(error);});
  });
}
