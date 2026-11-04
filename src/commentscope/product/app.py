"""Explore, bounded conversations and user-owned reflection revisions."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import base64
import hashlib
import json
import re
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4

from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.agents.web import WebError
from commentscope.factory.automatic_contract import digest
from commentscope.providers.budget import BudgetExhausted
from commentscope.product import contracts as contract
from commentscope.product.store import Store, encode, decode


def now(): return datetime.now(timezone.utc)
def uid(prefix): return prefix+uuid4().hex


def text(value, maximum, *, empty=True):
    if not isinstance(value,str) or len(value)>maximum or not empty and not value.strip():
        raise WebError(400,'invalid_input')
    return value


def integer(value, minimum=0):
    if type(value) is not int or value<minimum: raise WebError(400,'invalid_revision')
    return value


def token_hash(token):
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
        raise WebError(401,'session_token_required')
    try:
        raw=base64.urlsafe_b64decode(token+'=')
        if len(raw)!=32 or base64.urlsafe_b64encode(raw).decode().rstrip('=')!=token:raise ValueError()
    except ValueError:raise WebError(401,'session_token_required') from None
    return hashlib.sha256(token.encode()).hexdigest()


class RoomAgent(GroundedSession):
    def __init__(self,*args,peer=None,**kwargs):
        super().__init__(*args,**kwargs);self.peer=peer

    def invocation(self,question):
        value=super().invocation(question)
        if self.peer is not None:
            value['system']+='''\nPEER_CONTEXT_ONLY identifies a discussion point, not evidence.
Respond using only this perspective's ALLOWED_ENTRIES. Another speaker cannot
supply your facts, reasons, citations, or a newly agreed solution. If your own
entries cannot address the point, select not_in_evidence.'''
            value['data']['PEER_CONTEXT_ONLY']=deepcopy(self.peer)
        return value


class ProductApp:
    def __init__(self,path,analyses,model,*,session_ttl_seconds,room_maximum_usd,reservation,
                 revalidate=None,generation_status=None):
        if type(session_ttl_seconds) is not int or not 0<session_ttl_seconds<=86400:
            raise ValueError('Explicit session lifetime required')
        self.analyses={a.id:a for a in analyses}
        if not self.analyses:raise ValueError('Registered analyses required')
        self.ttl=session_ttl_seconds;self.room_limit=Decimal(room_maximum_usd)
        if not self.room_limit.is_finite() or self.room_limit<=0:raise ValueError('Explicit room limit required')
        self.store=Store(path);self.model=model;self.reservation=reservation
        self.revalidate=revalidate or (lambda:None)
        self.generation_status=generation_status or (lambda:'ready')
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='commentscope-product')

    def close(self): self.pool.shutdown(wait=True)

    def _analysis(self,session,*,live=True):
        value=self.analyses.get(session['analysis_id'])
        if value is None or value.revision!=session['bundle_revision']:raise WebError(409,'analysis_revision_conflict')
        if live:
            try:self.revalidate();value.live()
            except ValueError:raise WebError(410,'source_expired') from None
        return value

    def _session(self,db,token,sid=None):
        hashed=token_hash(token)
        row=db.execute('SELECT * FROM app_sessions WHERE token_hash=?'+(' AND id=?' if sid else ''),
                       (hashed,sid) if sid else (hashed,)).fetchone()
        if row is None:raise WebError(404,'resource_missing')
        value=decode(row)
        if now()>=datetime.fromisoformat(value['expires_at']):raise WebError(401,'session_expired')
        return value

    def _internal_session(self,db,sid):
        row=db.execute('SELECT data FROM app_sessions WHERE id=?',(sid,)).fetchone()
        if row is None:raise WebError(404,'resource_missing')
        value=decode(row)
        if now()>=datetime.fromisoformat(value['expires_at']):raise WebError(401,'session_expired')
        return value

    def _opinion(self,db,sid,kind,revision=None):
        if revision is not None:integer(revision)
        row=db.execute('SELECT data FROM opinions WHERE session_id=? AND kind=?'+
                       (' AND revision=?' if revision is not None else ' ORDER BY revision DESC LIMIT 1'),
                       (sid,kind,revision) if revision is not None else (sid,kind)).fetchone()
        if row is None:
            if kind=='current' and revision in (None,0):return {'revision':0,'text':'','segments':[]}
            raise WebError(409,'opinion_revision_conflict')
        return decode(row)

    def _room(self,db,token,rid):
        row=db.execute('SELECT * FROM rooms WHERE id=?',(rid,)).fetchone()
        if row is None:raise WebError(404,'resource_missing')
        session=self._session(db,token,row['session_id'])
        return session,decode(row)

    def _messages(self,db,rid):
        return [decode(r) for r in db.execute('SELECT data FROM messages WHERE room_id=? ORDER BY seq',(rid,))]

    def _message_public(self,value,analysis):
        result={k:deepcopy(v) for k,v in value.items() if not k.startswith('_')}
        if analysis.public()['status']=='expired' and result['author_kind']=='agent':
            result.update(points=[],required_premises=[],body=None,evidence_scope='expired')
        return result

    def _room_public(self,db,value,analysis,after=0):
        public={k:deepcopy(value[k]) for k in ('room_id','mode','participant_ids','initial_revision',
                'state','revision','last_seq','turn_count','analysis_revision')}
        public['messages']=[self._message_public(m,analysis) for m in self._messages(db,value['room_id']) if m['seq']>after]
        public['partial_round']=bool(value.get('round_failed')) or 0<value['cursor']<len(value['schedule'])
        public['rounds']=deepcopy(value.get('rounds',[]))
        if value['round_id']:
            public['rounds'].append({'round_id':value['round_id'],
                'completed':value['cursor']>=len(value['schedule']) and not value.get('round_failed'),
                'committed_turns':value['turn_count']-value.get('round_start_turn',0)})
        public['can_ask']=value['state'] in ('paused','awaiting_user') and value['turn_count']<18
        public['turn_limit']=18
        return public

    def _mutate(self,db,sid,operation,body,action):
        rid=body.get('request_id')
        if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',rid):raise WebError(400,'invalid_request_id')
        identity=digest({'operation':operation,'body':body})
        previous=db.execute('SELECT * FROM requests WHERE session_id=? AND operation=? AND request_id=?',
                            (sid,operation,rid)).fetchone()
        if previous is not None:
            if previous['body_sha']!=identity:raise WebError(409,'request_id_conflict')
            return 200,decode(previous)
        status,result=action()
        db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?)',(sid,operation,rid,identity,status,encode(result)))
        return status,result

    def _job(self,db,session,operation,args,room=None):
        if operation in ('comparison','reflection'):
            for previous in db.execute("SELECT data FROM jobs WHERE session_id=? AND operation=? AND state='succeeded'",(session['session_id'],operation)):
                candidate=decode(previous)
                if candidate['args']==args:return 200,{'job_id':candidate['job_id'],'state':'succeeded','room_id':None}
        status=self.generation_status()
        if status not in ('ready','busy'):raise WebError(503,status)
        if db.execute("SELECT 1 FROM jobs WHERE state='needs_reconciliation' LIMIT 1").fetchone():
            raise WebError(503,'reconcile_required')
        if db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]>=8:
            raise WebError(429,'queue_capacity')
        if room and room.get('job_id'):
            active=db.execute('SELECT state FROM jobs WHERE id=?',(room['job_id'],)).fetchone()
            if active and active['state'] in ('queued','running'):raise WebError(409,'room_busy')
        value={'job_id':uid('J'),'session_id':session['session_id'],'operation':operation,
               'state':'queued','args':deepcopy(args),'result':None,'error':None,
               'room_id':room['room_id'] if room else None}
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(value['job_id'],session['session_id'],operation,'queued',encode(value)))
        if room is not None:room['job_id']=value['job_id'];self._save_room(db,room)
        return 202,{'job_id':value['job_id'],'state':'queued','room_id':value['room_id']}

    def _save_room(self,db,room):
        db.execute('UPDATE rooms SET data=? WHERE id=?',(encode(room),room['room_id']))

    def _append_message(self,db,room,author,*,body=None,agent_id=None,reply_to=None,turn=None,history=None):
        room['last_seq']+=1;room['revision']+=1
        value={'message_id':uid('M'),'room_id':room['room_id'],'seq':room['last_seq'],
               'round_id':room['round_id'],'author_kind':author,'agent_id':agent_id,
               'reply_to_message_id':reply_to,'body':body,'analysis_revision':room['analysis_revision'],
               'created_at':now().isoformat()}
        if turn is not None:
            value.update({key:deepcopy(turn[key]) for key in
                          ('points','required_premises','answerability','limitation','status')})
            value['evidence_scope']='full_allowlist';value['_history']=deepcopy(history)
        db.execute('INSERT INTO messages VALUES(?,?,?,?)',
                   (value['message_id'],room['room_id'],value['seq'],encode(value)))
        return value

    def _session_public(self,db,session):
        analysis=self._analysis(session,live=False);sid=session['session_id']
        return {**deepcopy(session),'analysis':analysis.public(),
                'initial_opinion':self._opinion(db,sid,'initial'),
                'current_opinion':self._opinion(db,sid,'current'),
                'rooms':[{'room_id':r['room_id'],'mode':r['mode'],'state':r['state'],'revision':r['revision']}
                         for r in [decode(x) for x in db.execute('SELECT data FROM rooms WHERE session_id=?',(sid,))]],
                'reflections':[{'reflection_id':r['id'],'revision':r['revision']} for r in db.execute(
                    'SELECT id,max(revision) AS revision FROM reflections WHERE session_id=? GROUP BY id',(sid,))],
                'capabilities':{'explore_comparison':True,'one_to_one':True,'group':True,'reflection':True}}

    def handle(self,method,path,token,body=None):
        parsed=urlsplit(path);parts=parsed.path.strip('/').split('/');schedule=None
        if parts[:2]!=['api','v1']:raise WebError(404,'not_found')
        if method=='GET' and parts==['api','v1','analyses']:
            return 200,{'analyses':[a.public() for a in self.analyses.values()],
                        'generation_status':self.generation_status()}
        if method!='GET' and not isinstance(body,dict):raise WebError(400,'invalid_body')
        try:
            with self.store.transaction() as db:
                if method=='POST' and parts==['api','v1','sessions']:
                    self._fields(body,'analysis_id bundle_revision initial_opinion request_id')
                    hashed=token_hash(token);analysis=self.analyses.get(body['analysis_id'])
                    if analysis is None or analysis.revision!=body['bundle_revision']:raise WebError(409,'analysis_revision_conflict')
                    try:analysis.live()
                    except ValueError:raise WebError(410,'source_expired') from None
                    text(body['initial_opinion'],500)
                    row=db.execute('SELECT data FROM app_sessions WHERE token_hash=?',(hashed,)).fetchone()
                    if row:session=self._session(db,token)
                    else:
                        active=sum(datetime.fromisoformat(decode(x)['expires_at'])>now() for x in db.execute('SELECT data FROM app_sessions'))
                        if active>=8:raise WebError(429,'session_capacity')
                        session={'session_id':uid('S'),'analysis_id':analysis.id,'bundle_revision':analysis.revision,
                                 'expires_at':(now()+timedelta(seconds=self.ttl)).isoformat()}
                        db.execute('INSERT INTO app_sessions VALUES(?,?,?)',(session['session_id'],hashed,encode(session)))
                    def create():
                        if row is not None:raise WebError(409,'session_already_exists')
                        opinion={'revision':1,'text':body['initial_opinion'],'segments':contract.segments(body['initial_opinion'],'I')}
                        db.execute('INSERT INTO opinions VALUES(?,?,?,?)',(session['session_id'],'initial',1,encode(opinion)))
                        return 201,self._session_public(db,session)
                    result=self._mutate(db,session['session_id'],'create-session',body,create)
                elif len(parts)>=4 and parts[2]=='sessions':
                    session=self._session(db,token,parts[3]);result=self._session_route(db,method,parts[4:],session,body)
                elif len(parts)>=4 and parts[2]=='rooms':
                    session,room=self._room(db,token,parts[3]);result=self._room_route(db,method,parts[4:],session,room,body,parse_qs(parsed.query))
                elif method=='GET' and len(parts)==4 and parts[2]=='jobs':
                    row=db.execute('SELECT * FROM jobs WHERE id=?',(parts[3],)).fetchone()
                    if row is None:raise WebError(404,'resource_missing')
                    session=self._session(db,token,row['session_id']);job=decode(row)
                    public={k:deepcopy(job[k]) for k in ('job_id','state','room_id','result','error')}
                    public['stale']=any(job['args'].get(kind+'_revision',self._opinion(db,session['session_id'],kind)['revision'])!=
                        self._opinion(db,session['session_id'],kind)['revision'] for kind in ('initial','current')) if job['operation']!='room' else False
                    if self._analysis(session,live=False).public()['status']=='expired':public['result']={'available':False,'reason':'source_expired'}
                    result=200,public
                else:raise WebError(404,'not_found')
                if result[0]==202:schedule=result[1]['job_id']
            if schedule:self.pool.submit(self._work,schedule)
            return result
        except (KeyError,TypeError,ValueError):raise WebError(400,'invalid_input') from None

    def _fields(self,value,fields):
        if set(value)!=set(fields.split()):raise WebError(400,'invalid_request')

    def _session_route(self,db,method,tail,session,body):
        sid=session['session_id'];analysis=self._analysis(session,live=False)
        if method=='GET' and not tail:return 200,self._session_public(db,session)
        if method=='GET' and len(tail)==2 and tail[0]=='sources':
            self._analysis(session)
            try:return 200,analysis.source(tail[1])
            except ValueError:raise WebError(404,'source_missing') from None
        if method=='PUT' and len(tail)==2 and tail[0]=='opinions' and tail[1] in ('initial','current'):
            self._fields(body,'text expected_revision request_id');kind=tail[1]
            text(body['text'],500 if kind=='initial' else 2000);integer(body['expected_revision'])
            def save_opinion():
                previous=self._opinion(db,sid,kind)
                if previous['revision']!=body['expected_revision']:raise WebError(409,'revision_conflict')
                value={'revision':previous['revision']+1,'text':body['text'],
                       'segments':contract.segments(body['text'],'I' if kind=='initial' else 'C')}
                db.execute('INSERT INTO opinions VALUES(?,?,?,?)',(sid,kind,value['revision'],encode(value)))
                return 200,value
            return self._mutate(db,sid,'opinion-'+kind,body,save_opinion)
        if method=='POST' and tail==['comparisons']:
            self._fields(body,'perspective_id initial_revision request_id')
            def compare():
                self._analysis(session);opinion=self._opinion(db,sid,'initial',body['initial_revision'])
                if body['perspective_id'] not in {p['candidate_id'] for p in analysis.compiled['profiles']}:raise WebError(404,'perspective_missing')
                return self._job(db,session,'comparison',{'perspective_id':body['perspective_id'],
                    'initial_revision':opinion['revision']})
            return self._mutate(db,sid,'comparison',body,compare)
        if method=='POST' and tail==['rooms']:
            self._fields(body,'mode participant_ids initial_revision request_id')
            def create_room():
                self._analysis(session);self._opinion(db,sid,'initial',body['initial_revision'])
                ids=body['participant_ids'];available={p['candidate_id'] for p in analysis.compiled['profiles']}
                if (body['mode'] not in ('one_to_one','group') or not isinstance(ids,list)
                        or len(ids)!=len(set(ids)) or any(i not in available for i in ids)
                        or body['mode']=='one_to_one' and len(ids)!=1
                        or body['mode']=='group' and not 2<=len(ids)<=3):raise WebError(422,'invalid_participants')
                room={'room_id':uid('R'),'mode':body['mode'],'participant_ids':ids,
                    'initial_revision':body['initial_revision'],'analysis_revision':analysis.revision,
                    'state':'idle','revision':1,'epoch':0,'cursor':0,'last_seq':0,'turn_count':0,
                    'schedule':[],'round_id':0,'rounds':[],'round_failed':False,'round_start_turn':0,
                    'question':'','cost_usd':'0','maximum_cost_usd':str(self.room_limit),'job_id':None}
                db.execute('INSERT INTO rooms VALUES(?,?,?)',(room['room_id'],sid,encode(room)))
                return 201,self._room_public(db,room,analysis)
            return self._mutate(db,sid,'create-room',body,create_room)
        if method=='POST' and tail==['reflection-analyses']:
            self._fields(body,'initial_revision current_revision context_message_ids request_id')
            def reflect():
                self._analysis(session);self._opinion(db,sid,'initial',body['initial_revision']);self._opinion(db,sid,'current',body['current_revision'])
                messages=self._context(db,sid,body['context_message_ids'])
                return self._job(db,session,'reflection',{'initial_revision':body['initial_revision'],
                    'current_revision':body['current_revision'],'messages':messages})
            return self._mutate(db,sid,'reflection',body,reflect)
        if tail and tail[0]=='reflections':
            return self._reflection_route(db,method,tail[1:],session,body)
        raise WebError(404,'not_found')

    def _context(self,db,sid,ids):
        if not isinstance(ids,list) or len(ids)>24 or len(set(ids))!=len(ids):raise WebError(422,'context_capacity')
        values=[]
        for mid in ids:
            row=db.execute('SELECT m.data FROM messages m JOIN rooms r ON r.id=m.room_id WHERE m.id=? AND r.session_id=?',(mid,sid)).fetchone()
            if row is None:raise WebError(404,'resource_missing')
            values.append({k:v for k,v in decode(row).items() if not k.startswith('_')})
        return values

    def _reflection_route(self,db,method,tail,session,body):
        sid=session['session_id'];rid=tail[0] if len(tail)==1 else None
        existing=db.execute('SELECT * FROM reflections WHERE id=? AND session_id=? ORDER BY revision DESC LIMIT 1',(rid,sid)).fetchone() if rid else None
        if rid and existing is None:raise WebError(404,'resource_missing')
        if method=='GET' and rid:
            value=decode(existing)
            value['stale']=any(value[kind+'_revision']!=self._opinion(db,sid,kind)['revision'] for kind in ('initial','current'))
            value['source_status']=self._analysis(session,live=False).public()['status']
            return 200,value
        if not (method=='POST' and not tail or method=='PUT' and rid):raise WebError(404,'not_found')
        self._fields(body,'initial_revision current_revision analysis_job_id user_items expected_revision request_id')
        def save():
            expected=0 if existing is None else existing['revision'];integer(body['expected_revision'])
            if expected!=body['expected_revision']:raise WebError(409,'revision_conflict')
            initial=self._opinion(db,sid,'initial',body['initial_revision']);current=self._opinion(db,sid,'current',body['current_revision'])
            jid=body['analysis_job_id']
            if jid is not None:
                row=db.execute('SELECT * FROM jobs WHERE id=? AND session_id=?',(jid,sid)).fetchone()
                if row is None:raise WebError(404,'resource_missing')
                job=decode(row)
                if (job['operation']!='reflection' or job['state']!='succeeded'
                        or any(job['args'][kind+'_revision']!=body[kind+'_revision'] for kind in ('initial','current'))):
                    raise WebError(409,'analysis_revision_conflict')
            owned_ids=[r['id'] for r in db.execute('SELECT m.id FROM messages m JOIN rooms r ON r.id=m.room_id WHERE r.session_id=?',(sid,))]
            items=contract.user_items(body['user_items'],initial['segments'],current['segments'],owned_ids)
            mids=[]
            for rows in items.values():
                for row in rows:mids.extend(row['related_message_ids'])
            messages=self._context(db,sid,list(dict.fromkeys(mids)))
            value={'reflection_id':rid or uid('F'),'revision':expected+1,
                   'initial_revision':initial['revision'],'current_revision':current['revision'],
                   'initial_opinion':initial['text'],'current_opinion':current['text'],
                   'analysis_job_id':jid,'user_items':items,'authored_by':'user','created_at':now().isoformat(),
                   'context_message_refs':[{k:m[k] for k in ('message_id','room_id','seq')} for m in messages]}
            db.execute('INSERT INTO reflections VALUES(?,?,?,?)',(value['reflection_id'],sid,value['revision'],encode(value)))
            return (201 if existing is None else 200),value
        return self._mutate(db,sid,'save-reflection-'+str(rid),body,save)

    def _room_route(self,db,method,tail,session,room,body,query):
        analysis=self._analysis(session,live=False);rid=room['room_id']
        if method=='GET' and not tail:
            if set(query)-{'after_seq'} or any(len(v)!=1 for v in query.values()):raise WebError(400,'invalid_cursor')
            after=int(query.get('after_seq',['0'])[0]);integer(after)
            return 200,self._room_public(db,room,analysis,after)
        if method!='POST' or len(tail)!=1:raise WebError(404,'not_found')
        action=tail[0]
        if action=='control':self._fields(body,'action expected_revision request_id')
        elif action=='start':self._fields(body,'opening_question expected_revision request_id')
        elif action=='messages':self._fields(body,'text reply_to_message_id expected_revision request_id')
        else:raise WebError(404,'not_found')
        def mutate():
            integer(body['expected_revision'])
            if room['revision']!=body['expected_revision']:raise WebError(409,'revision_conflict')
            control=body.get('action')
            if action=='control' and control in ('pause','close','acknowledge_error'):
                if control=='pause':
                    if room['state']=='running':room['state']='pausing'
                    elif room['state'] in ('idle','awaiting_user'):room['state']='paused'
                    elif room['state']!='paused':raise WebError(409,'room_not_ready')
                elif control=='close':
                    room['epoch']+=1;room['state']='closing' if room['state'] in ('running','pausing') else 'closed'
                else:
                    if room['state']!='error':raise WebError(409,'room_not_ready')
                    room['state']='paused';room['cursor']=len(room['schedule'])
                room['revision']+=1;self._save_room(db,room)
                return 200,self._room_public(db,room,analysis)
            self._analysis(session)
            if room['turn_count']>=18:raise WebError(409,'turn_limit')
            if action=='start':
                if room['state']!='idle':raise WebError(409,'room_not_ready')
                question=text(body['opening_question'],1000,empty=False)
                phases=['opening','reply'] if room['mode']=='group' else ['opening']
            elif action=='messages':
                if room['state'] not in ('paused','awaiting_user'):raise WebError(409,'room_not_ready')
                question=text(body['text'],1000,empty=False);phases=['answer']
                mid=body['reply_to_message_id']
                if mid is not None and not any(m['message_id']==mid for m in self._messages(db,rid)):
                    raise WebError(404,'resource_missing')
            elif control=='resume':
                if room['state']!='paused':raise WebError(409,'room_not_ready')
                room['state']='running';room['revision']+=1
                return self._job(db,session,'room',{'epoch':room['epoch']},room)
            elif control=='next_round':
                if room['state'] not in ('paused','awaiting_user'):raise WebError(409,'room_not_ready')
                question=room['question'];phases=['reply']
            else:raise WebError(400,'invalid_control')
            if room['round_id']:
                room['rounds'].append({'round_id':room['round_id'],
                    'completed':room['cursor']>=len(room['schedule']) and not room.get('round_failed'),
                    'committed_turns':room['turn_count']-room.get('round_start_turn',0)})
            room.update(epoch=room['epoch']+1,round_id=room['round_id']+1,cursor=0,state='running',question=question,
                        round_failed=False,round_start_turn=room['turn_count'])
            room['schedule']=[{'agent_id':cid,'phase':phase} for phase in phases for cid in room['participant_ids']]
            if action in ('start','messages'):
                message=self._append_message(db,room,'user',body=question,reply_to=body.get('reply_to_message_id'))
                room['user_message_id']=message['message_id']
            room['revision']+=1
            return self._job(db,session,'room',{'epoch':room['epoch']},room)
        return self._mutate(db,session['session_id'],action+'-'+rid,body,mutate)

    def _finish_job(self,db,job,state,result=None,error=None):
        job.update(state=state,result=result,error=error)
        db.execute('UPDATE jobs SET state=?,data=? WHERE id=?',(state,encode(job),job['job_id']))

    def _work(self,jid):
        job=None
        try:
            with self.store.transaction() as db:
                row=db.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone();job=decode(row)
                if job['state']!='queued':return
                session=self._internal_session(db,job['session_id']);analysis=self._analysis(session)
                self._finish_job(db,job,'running')
                initial=self._opinion(db,session['session_id'],'initial',job['args'].get('initial_revision'))
                current=self._opinion(db,session['session_id'],'current',job['args'].get('current_revision'))
            if job['operation']=='room':return self._work_room(job,session,analysis)
            if job['operation']=='comparison':
                if not initial['segments']:result={'available':False,'items':[],'reason':'empty_initial_opinion'}
                else:
                    allowed=analysis.allowed(job['args']['perspective_id'])
                    request=contract.comparison_request(initial['segments'],allowed)
                    response=self.model('comparison',request)
                    result={'available':True,'items':contract.bind_comparison(request,response,initial['segments'],allowed)}
                result.update(initial_revision=initial['revision'],perspective_id=job['args']['perspective_id'])
            else:
                if not current['segments']:categories={k:[] for k in contract.CATEGORIES}
                else:
                    request,aliases=contract.reflection_request(initial['segments'],current['segments'],job['args']['messages'])
                    categories=contract.bind_reflection(request,self.model('reflection',request),aliases)
                result={'categories':categories,'initial_revision':initial['revision'],'current_revision':current['revision'],
                        'context_message_ids':[m['message_id'] for m in job['args']['messages']],
                        'context_message_refs':[{k:m[k] for k in ('message_id','room_id','seq')} for m in job['args']['messages']]}
            result.update(analysis_revision=analysis.revision,semantic_reliability='not_assessed')
            self._analysis(session)
            with self.store.transaction() as db:
                self._internal_session(db,session['session_id']);self._finish_job(db,job,'succeeded',result)
        except Exception as exc:
            if job is None:return
            code=exc.code if isinstance(exc,WebError) else 'reconcile_required' if isinstance(exc,BudgetExhausted) else 'model_or_validation_failed'
            state='needs_reconciliation' if code=='reconcile_required' else 'failed'
            with self.store.transaction() as db:
                self._finish_job(db,job,state,error={'code':code,'retryable':False})
                if job.get('room_id'):
                    room=decode(db.execute('SELECT data FROM rooms WHERE id=?',(job['room_id'],)).fetchone())
                    if room['epoch']!=job['args']['epoch'] or room['state'] in ('closing','closed'):
                        room['state']='closed'
                        if state!='needs_reconciliation':self._finish_job(db,job,'cancelled',error={'code':code,'retryable':False})
                    else:
                        room['state']='needs_reconciliation' if state=='needs_reconciliation' else 'exhausted' if code=='budget_exhausted' else 'error'
                    room['round_failed']=True
                    room['revision']+=1;self._save_room(db,room)

    def _work_room(self,job,session,analysis):
        rid=job['room_id']
        while True:
            with self.store.transaction() as db:
                room=decode(db.execute('SELECT data FROM rooms WHERE id=?',(rid,)).fetchone())
                if room['epoch']!=job['args']['epoch'] or room['state'] in ('closing','closed'):
                    room['state']='closed';self._save_room(db,room)
                    self._finish_job(db,job,'cancelled',{'room_id':rid,'completed':False});return
                if room['state']=='pausing':room['state']='paused'
                if room['state']=='paused':
                    self._save_room(db,room);self._finish_job(db,job,'succeeded',{'room_id':rid,'completed':False});return
                if room['cursor']>=len(room['schedule']) or room['turn_count']>=18:
                    room['state']='exhausted' if room['turn_count']>=18 else 'awaiting_user'
                    room['revision']+=1;self._save_room(db,room)
                    self._finish_job(db,job,'succeeded',{'room_id':rid,'completed':room['cursor']>=len(room['schedule']) and not room.get('round_failed')});return
                task=room['schedule'][room['cursor']];messages=self._messages(db,rid)
                peer=next((m for m in reversed(messages) if m['author_kind']=='agent' and m['agent_id']!=task['agent_id']),None) if task['phase']=='reply' else None
                history=[m['_history'] for m in messages if m.get('agent_id')==task['agent_id']][-2:]
                question=room['question'] if task['phase']!='reply' else 'Respond to the preceding perspective using your own position and explicit grounds.'
                cost_before=Decimal(room['cost_usd']);limit=Decimal(room['maximum_cost_usd'])
            charged=Decimal(0)
            def provider(system,data,schema,*,max_tokens):
                nonlocal charged
                request={'system':system,'data':data,'schema':schema,'max_tokens':max_tokens}
                if cost_before+Decimal(self.reservation(request))>limit:raise WebError(503,'budget_exhausted')
                response=self.model('room',request)
                charged=Decimal(str(response.get('new_cost_usd',response.get('usage',{}).get('cost',0))))
                if not charged.is_finite() or charged<0:raise ValueError('Unknown room charge')
                if response.get('errors'):raise ValueError('Invalid model response')
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(response['output'])}}]}
            self._analysis(session)
            context=None if peer is None else {'message_id':peer['message_id'],'agent_id':peer['agent_id'],
                                              'points':peer.get('points',[]),'body':peer.get('body')}
            agent=RoomAgent(analysis.bundle,task['agent_id'],provider=provider,peer=context);agent.history=deepcopy(history)
            try:
                turn=agent.ask(question)
                if turn['status']=='error':raise ValueError('Invalid grounded turn')
                self._analysis(session)
            except Exception:
                with self.store.transaction() as db:
                    failed=decode(db.execute('SELECT data FROM rooms WHERE id=?',(rid,)).fetchone())
                    failed['cost_usd']=str(Decimal(failed['cost_usd'])+charged)
                    self._save_room(db,failed)
                raise
            with self.store.transaction() as db:
                self._internal_session(db,session['session_id'])
                current=decode(db.execute('SELECT data FROM rooms WHERE id=?',(rid,)).fetchone())
                current['cost_usd']=str(Decimal(current['cost_usd'])+charged)
                if current['epoch']!=job['args']['epoch'] or current['state'] in ('closing','closed'):
                    current['state']='closed';current['revision']+=1;self._save_room(db,current)
                    self._finish_job(db,job,'cancelled',{'room_id':rid,'completed':False});return
                self._append_message(db,current,'agent',agent_id=task['agent_id'],
                    reply_to=peer['message_id'] if peer else current.get('user_message_id'),turn=turn,history=agent.history[-1])
                current['turn_count']+=1;current['cursor']+=1
                if current['state']=='pausing':
                    current['state']='paused';self._save_room(db,current)
                    self._finish_job(db,job,'succeeded',{'room_id':rid,
                        'completed':current['cursor']>=len(current['schedule']) and not current.get('round_failed')})
                    return
                self._save_room(db,current)
