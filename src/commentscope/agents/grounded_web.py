"""Local-only grounded comparison UI. Input screening is not quality approval."""
import argparse
from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from uuid import uuid4

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.agents.web import ComparisonHandler, WebError
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write

ROOT = Path(__file__).parent


class GroundedApp:
    def __init__(self, bundle, session_dir, *, provider, revalidate=None):
        self.bundle=deepcopy(bundle); self.compiled=compile_inputs(bundle)
        self.session_dir=Path(session_dir); self.provider=provider
        self.revalidate=revalidate or (lambda: compile_inputs(self.bundle))
        self.lock=threading.RLock(); self.sessions={}; self.busy=False

    def live(self):
        try:
            self.revalidate()
            if compile_inputs(self.bundle) != self.compiled: raise ValueError('Changed input')
        except Exception: raise WebError(409,'source_validation_failed') from None

    def get(self,token):
        self.live()
        item=self.sessions.get(token)
        if item is None or (time.monotonic()-item['touched']>3600 and not item['running']):
            raise WebError(401,'session_missing_or_expired')
        item['touched']=time.monotonic()
        return item

    def public(self,item):
        return {'profiles':deepcopy(self.compiled['profiles']),'deferred':deepcopy(self.compiled['deferred']),
                'rounds':deepcopy(item['rounds']),'selected':list(item['agents']),
                'job':item['job'],'remaining_questions':6-len(item['requests']),
                'can_ask':bool(item['agents']) and not self.busy and len(item['requests'])<6,
                'quality_gate_passed':False,'human_approved':False,
                'notice':'Development only. Source judgments and claim types remain fallible; screened inputs are not certified agents.'}

    def create(self,ids=None):
        with self.lock:
            self.live()
            available=[p['candidate_id'] for p in self.compiled['profiles']]
            if ids is None: ids=available[:2]
            if not isinstance(ids,list) or len(ids)>2 or len(set(ids))!=len(ids) or any(i not in available for i in ids):
                raise WebError(400,'invalid_perspective_selection')
            self.sessions={k:v for k,v in self.sessions.items() if v['running'] or time.monotonic()-v['touched']<3600}
            if len(self.sessions)>=8: raise WebError(429,'session_capacity')
            token=secrets.token_urlsafe(32); folder=self.session_dir/str(uuid4())
            write(folder/'manifest.json',{'bundle_sha256':digest(self.bundle),'compiled':self.compiled,'selected':ids})
            item={'agents':{i:GroundedSession(self.bundle,i,provider=self.provider) for i in ids},
                  'rounds':[],'requests':{},'touched':time.monotonic(),'folder':folder,'running':False,'job':'idle'}
            self.sessions[token]=item
            return {'token':token,**self.public(item)}

    def state(self,token):
        with self.lock: return self.public(self.get(token))

    def source(self,token,sid):
        with self.lock:
            self.get(token)
            row=next((s for s in self.bundle['sources'] if s['id']==sid),None)
            if row is None: raise WebError(404,'source_missing')
            return deepcopy(row)

    def ask(self,token,question,rid):
        if not isinstance(question,str) or not question.strip() or len(question)>1000:
            raise WebError(400,'invalid_question')
        if not isinstance(rid,str) or not 1<=len(rid)<=80 or not rid.isascii() or not all(c.isalnum() or c=='-' for c in rid):
            raise WebError(400,'invalid_request_id')
        with self.lock:
            item=self.get(token)
            if rid in item['requests']:
                if item['requests'][rid]!=question: raise WebError(409,'request_id_conflict')
                return self.public(item)
            if self.busy: raise WebError(409,'inference_busy')
            if not item['agents']: raise WebError(409,'no_screened_inputs')
            if len(item['requests'])>=6: raise WebError(409,'question_limit')
            write(item['folder']/(rid+'.request.json'),{'question':question,'bundle_sha256':digest(self.bundle)})
            item['requests'][rid]=question; item['running']=True; item['job']='running'; self.busy=True
            threading.Thread(target=self.run,args=(item,question,rid),daemon=True).start()
            return self.public(item)

    def run(self,item,question,rid):
        previous={i:deepcopy(a.history) for i,a in item['agents'].items()}
        turns=[]; started=time.perf_counter()
        try:
            for cid,agent in item['agents'].items():
                self.live(); turn=agent.ask(question)
                write(item['folder']/(rid+'.'+digest(cid)+'.json'),turn)
                # Only host-rendered content, never raw model text, enters live UI.
                turns.append({k:deepcopy(turn[k]) for k in ['candidate_id','status','answerability','limitation','points','required_premises']})
            self.live()
            row={'question':question,'answers':turns,'seconds':time.perf_counter()-started}
            write(item['folder']/(rid+'.round.json'),row)
            with self.lock: item['rounds'].append(row); item['job']='done'
        except Exception:
            with self.lock:
                for cid,agent in item['agents'].items(): agent.history=previous[cid]
                item['job']='error'
            try: write(item['folder']/(rid+'.failure.json'),{'error':'round_failed','completed':[t['candidate_id'] for t in turns]})
            except OSError: pass
        finally:
            with self.lock: self.busy=False; item['running']=False; item['touched']=time.monotonic()


class GroundedHandler(ComparisonHandler):
    def _handle(self,mutation=False):
        try:
            self._guard(mutation)
            app=self.server.app; token=self.headers.get('X-Session-Token','')
            if not mutation:
                assets={'/':('grounded.html','text/html; charset=utf-8'),
                        '/app.js':('grounded.js','text/javascript; charset=utf-8'),
                        '/app.css':('comparison.css','text/css; charset=utf-8')}
                if self.path in assets:
                    name,kind=assets[self.path]; return self.reply(200,(ROOT/name).read_bytes(),kind)
                if self.path=='/api/state': return self.reply(200,app.state(token))
                raise WebError(404,'not_found')
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type')!='application/json':
                raise WebError(415,'json_required')
            try:
                size=int(self.headers.get('Content-Length','-1'))
                if not 0<size<=8192: raise ValueError()
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict): raise ValueError()
            except (ValueError,UnicodeError): raise WebError(400,'invalid_body') from None
            if self.path=='/api/session' and set(body)<= {'ids'}: return self.reply(201,app.create(body.get('ids')))
            if self.path=='/api/ask' and set(body)=={'question','request_id'}:
                return self.reply(202,app.ask(token,body['question'],body['request_id']))
            if self.path=='/api/source' and set(body)=={'source_id'}: return self.reply(200,app.source(token,body['source_id']))
            raise WebError(400,'invalid_request')
        except WebError as exc: self.reply(exc.status,{'error':exc.code})
        except (BrokenPipeError,ConnectionResetError,TimeoutError): pass
        except Exception: self.reply(500,{'error':'local_server_error'})


class GroundedServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,app,port):
        self.app=app
        super().__init__(('127.0.0.1',port),GroundedHandler)
        actual=self.server_address[1]; self.hosts={f'127.0.0.1:{actual}',f'localhost:{actual}'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('bundle',type=Path)
    p.add_argument('--experimental',action='store_true',required=True,help='Explicitly use unapproved screened inputs for local development')
    p.add_argument('--port',type=int,default=8766)
    p.add_argument('--session-dir',type=Path,default=Path('runs/grounded-ui'))
    p.add_argument('--budget',type=Path,default=Path('runs/mvp-agreed-20261013/inference.sqlite'))
    p.add_argument('--cycle-id',default='mvp-agreed-20261013')
    a=p.parse_args(); bundle=read_json(a.bundle); original=sha(a.bundle)
    def revalidate():
        if sha(a.bundle)!=original: raise ValueError('Bundle file changed')
    budget=InferenceBudget(a.budget,a.cycle_id)
    app=GroundedApp(bundle,a.session_dir,provider=budget.provider(original,timeout_seconds=30),revalidate=revalidate)
    server=GroundedServer(app,a.port)
    print(f'Grounded development UI: http://127.0.0.1:{server.server_address[1]}',flush=True)
    print('Needs the configured local llama server on port 8091. Not a quality-approved MVP.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
