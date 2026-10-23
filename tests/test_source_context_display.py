from copy import deepcopy
from dataclasses import replace
from http.client import HTTPConnection
import json
import tempfile
import threading
import unittest

from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.agents.grounded_runtime import GroundedSession
from commentscope.agents.grounded_web import GroundedApp, GroundedServer
from commentscope.factory.automatic_contract import digest
from experiments.grounding_contract_demo import fixture
import test_minimal_pipeline as pipeline_fixture

MARKER='PARENT_REASON_MARKER_not_the_reply_author_reason'


class SourceContextDisplay(unittest.TestCase):
    def bundle(self):
        bundle=fixture();sid=bundle['sources'][0]['id']
        parent={'id':'parent_context','text':MARKER}
        bundle['source_contexts']={sid:{'source_sha256':digest(bundle['sources'][0]['text']),
            'parent_sha256':digest(parent),'parent':parent}}
        return bundle,sid,parent

    def test_parent_context_never_becomes_another_vote_or_model_evidence(self):
        bundle,sid,parent=self.bundle();plain=deepcopy(bundle);plain.pop('source_contexts')
        before=compile_inputs(plain);after=compile_inputs(bundle)
        self.assertEqual(before['profiles'],after['profiles'])
        self.assertEqual(before['claim_decisions'],after['claim_decisions'])
        self.assertNotEqual(before['input_sha256'],after['input_sha256'])
        agent=GroundedSession(bundle,'P1',provider=lambda *a,**kw:None)
        self.assertNotIn(MARKER,json.dumps(agent.invocation('What is your position?')))
        self.assertNotIn(parent['id'],[s['id'] for s in bundle['sources']])

    def test_changed_parent_unknown_child_and_self_parent_fail_before_session(self):
        bundle,sid,parent=self.bundle()
        changed=deepcopy(bundle);changed['source_contexts'][sid]['parent']['text']='changed'
        with self.assertRaises(ValueError):compile_inputs(changed)
        changed=deepcopy(bundle);changed['source_contexts']['unknown']=changed['source_contexts'].pop(sid)
        with self.assertRaises(ValueError):compile_inputs(changed)
        changed=deepcopy(bundle);changed['source_contexts'][sid]['parent']['id']=sid
        changed['source_contexts'][sid]['parent_sha256']=digest(changed['source_contexts'][sid]['parent'])
        with self.assertRaises(ValueError):compile_inputs(changed)

    def test_http_source_returns_own_text_and_separately_labeled_parent(self):
        bundle,sid,parent=self.bundle()
        with tempfile.TemporaryDirectory() as directory:
            app=GroundedApp(bundle,directory,provider=lambda *a,**kw:None)
            session=app.create();server=GroundedServer(app,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            connection=HTTPConnection('127.0.0.1',server.server_address[1])
            try:
                connection.request('POST','/api/source',body=json.dumps({'source_id':sid}),headers={
                    'Content-Type':'application/json','Origin':f'http://127.0.0.1:{server.server_address[1]}',
                    'X-Session-Token':session['token']})
                response=connection.getresponse();self.assertEqual(response.status,200)
                source=json.loads(response.read());self.assertEqual(source['PARENT_CONTEXT_ONLY'],parent)
                self.assertEqual(source['text'],bundle['sources'][0]['text'])
                self.assertNotIn('parent_sha256',source)
            finally:connection.close();server.shutdown();server.server_close();thread.join(2)

    def test_factory_preserves_reply_parent_without_counting_it_as_support(self):
        case=pipeline_fixture.MinimalPipelineTests();case.setUp()
        original=case.snapshot.comments
        parent=replace(original[0],comment_id='parent_context',text_original=MARKER,parent_id=None)
        case.snapshot=replace(case.snapshot,comments=(replace(original[0],parent_id='parent_context'),*original[1:],parent))
        output=case.process(pipeline_fixture.ScriptedRunner(),scope_ids=[c.comment_id for c in original])
        bundle=output['agent_inputs']['bundle'];compiled=output['agent_inputs']['compiled']
        self.assertEqual(bundle['source_contexts']['0']['parent'],{'id':'parent_context','text':MARKER})
        self.assertNotIn('parent_context',[s['id'] for s in bundle['sources']])
        self.assertEqual(len(compiled['profiles']),2)
        self.assertTrue(all(p['model_core_support_count']==3 for p in compiled['profiles']))
        self.assertNotIn(MARKER,json.dumps(compiled['profiles']))


if __name__=='__main__':unittest.main()
