from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from commentscope.agents.grounded_web import GroundedApp, GroundedServer
from commentscope.agents.web import WebError
from experiments.grounding_contract_demo import fixture


def provider(system,data,schema,**kw):
    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
        'answerability':'grounded','claim_ids':[data['PERSPECTIVE']['core_claim_id']],'limitation':'none'})}}]}


class GroundedWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app=GroundedApp(fixture(),self.tmp.name,provider=provider)
        self.token=self.app.create()['token']

    def finish(self):
        deadline=time.monotonic()+5
        while self.app.busy and time.monotonic()<deadline: time.sleep(.01)
        self.assertFalse(self.app.busy)
        return self.app.state(self.token)

    def test_round_source_followup_and_no_raw_model_text(self):
        self.app.ask(self.token,'Your position?','q1'); state=self.finish()
        self.assertEqual(state['job'],'done')
        turn=state['rounds'][0]['answers'][0]
        self.assertEqual(turn['points'][0]['claim_id'],'position')
        self.assertNotIn('result',turn)
        self.assertFalse(state['quality_gate_passed'])
        source=turn['points'][0]['citations']['comment_evidence'][0]['source_id']
        self.assertTrue(self.app.source(self.token,source)['text'])
        self.app.ask(self.token,'Why that?','q2'); self.finish()
        self.assertEqual(len(self.app.sessions[self.token]['agents']['P1'].history),2)

    def test_initial_opinion_is_preserved_but_not_agent_evidence(self):
        opinion='  Initial user view: conditional support.\nKeep this exact.  '
        seen=[]
        def recording(system,data,schema,**kw):
            seen.append(deepcopy(data))
            return provider(system,data,schema,**kw)
        self.app.provider=recording
        before=deepcopy(self.app.compiled)
        first=self.app.create(initial_opinion=opinion)
        second=self.app.create(initial_opinion='A different user opinion.')
        self.assertEqual(self.app.state(first['token'])['initial_opinion'],opinion)
        self.assertEqual(self.app.state(second['token'])['initial_opinion'],'A different user opinion.')
        self.assertEqual(self.app.state(self.token)['initial_opinion'],'')
        manifest=self.app.sessions[first['token']]['folder']/'manifest.json'
        self.assertEqual(json.loads(manifest.read_text())['initial_opinion'],opinion)
        self.assertEqual(self.app.compiled,before)
        self.token=first['token']
        self.app.ask(self.token,'Your position?','opinion-q1');self.finish()
        self.assertTrue(seen)
        self.assertNotIn(opinion,json.dumps(seen))
        self.assertEqual(self.app.compiled,before)

    def test_invalid_initial_opinion_does_not_create_a_session(self):
        sessions=set(self.app.sessions);folders=set(Path(self.tmp.name).iterdir())
        for value in [None,[],{},0,False,'x'*501]:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(WebError) as exc:self.app.create(initial_opinion=value)
                self.assertEqual(exc.exception.code,'invalid_initial_opinion')
                self.assertEqual(set(self.app.sessions),sessions)
                self.assertEqual(set(Path(self.tmp.name).iterdir()),folders)
        boundary='한'*500
        self.assertEqual(self.app.create(initial_opinion=boundary)['initial_opinion'],boundary)

    def test_idempotence_limit_and_no_foreign_source(self):
        for i in range(6):
            self.app.ask(self.token,'Position?',f'q{i}'); self.finish()
        self.app.ask(self.token,'Position?','q0')
        self.assertEqual(len(self.app.state(self.token)['rounds']),6)
        for fn in [lambda:self.app.ask(self.token,'Seventh','q6'),
                   lambda:self.app.ask(self.token,'Changed','q0'),
                   lambda:self.app.source(self.token,'unknown')]:
            with self.assertRaises(WebError):fn()

    def test_failed_round_not_published_or_history_retained(self):
        def broken(*a,**k):raise RuntimeError('private failure')
        self.app.sessions[self.token]['agents']['P1'].provider=broken
        self.app.ask(self.token,'question','q1'); state=self.finish()
        self.assertEqual(state['job'],'error'); self.assertEqual(state['rounds'],[])
        self.assertEqual(self.app.sessions[self.token]['agents']['P1'].history,[])

    def test_expiry_or_mutation_blocks(self):
        self.app.bundle['sources'][0]['text']='Changed'
        with self.assertRaises(WebError):self.app.state(self.token)

    def test_empty_profiles_visible_without_model_call(self):
        b=fixture(); b['relations']=[]
        app=GroundedApp(b,self.tmp.name,provider=provider)
        state=app.create(); self.assertFalse(state['can_ask']); self.assertTrue(state['deferred'])
        with self.assertRaises(WebError):app.ask(state['token'],'question','q1')

    def test_loopback_http_guards_and_assets(self):
        server=GroundedServer(self.app,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            port=server.server_address[1]; conn=HTTPConnection('127.0.0.1',port)
            conn.request('GET','/'); response=conn.getresponse()
            self.assertEqual(response.status,200); self.assertIn('Content-Security-Policy',dict(response.getheaders()))
            self.assertIn(b'/app.js',response.read())
            conn.request('POST','/api/session',body='{}',headers={'Content-Type':'application/json','Origin':'http://evil.example'})
            response=conn.getresponse(); self.assertEqual(response.status,403); response.read()
            conn.request('GET','/api/state',headers={'X-Session-Token':self.token})
            response=conn.getresponse(); self.assertEqual(response.status,200); response.read();conn.close()
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_http_initial_opinion_roundtrip_and_validation(self):
        server=GroundedServer(self.app,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        conn=HTTPConnection('127.0.0.1',server.server_address[1])
        headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{server.server_address[1]}'}
        try:
            body={'ids':['P1'],'initial_opinion':'My original view.'}
            conn.request('POST','/api/session',body=json.dumps(body),headers=headers)
            response=conn.getresponse();self.assertEqual(response.status,201)
            session=json.loads(response.read());self.assertEqual(session['initial_opinion'],body['initial_opinion'])
            conn.request('GET','/api/state',headers={'X-Session-Token':session['token']})
            response=conn.getresponse();self.assertEqual(response.status,200)
            state=json.loads(response.read());self.assertEqual(state['initial_opinion'],body['initial_opinion'])
            self.assertFalse(state['quality_gate_passed'])
            for value in [None,'x'*501]:
                conn.request('POST','/api/session',body=json.dumps({'initial_opinion':value}),headers=headers)
                response=conn.getresponse();self.assertEqual(response.status,400)
                self.assertEqual(json.loads(response.read())['error'],'invalid_initial_opinion')
        finally:
            conn.close();server.shutdown();server.server_close();thread.join(2)
