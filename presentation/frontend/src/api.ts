import type {Job} from './types';
export async function request<T>(path:string,body?:unknown,method=body?'POST':'GET',signal?:AbortSignal):Promise<T>{
  const response=await fetch(`/api${path}`,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'The request could not be completed.');
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
  const key=path+JSON.stringify(body);
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
