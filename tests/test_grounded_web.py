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
