"""Offline faults in actual web comparison rounds; no paid model calls."""
from copy import deepcopy
from pathlib import Path
import json,tempfile,time,unittest
from urllib.error import URLError
from commentscope.agents.grounded_web import GroundedApp
from experiments.grounding_contract_demo import fixture

class FailedRoundTests(unittest.TestCase):
    def app(self,provider,two=False):
        temp=tempfile.TemporaryDirectory(dir='runs');self.addCleanup(temp.cleanup)
        bundle=fixture()
        if two:
            candidate=deepcopy(bundle['candidates'][0]);candidate['id']='P2';bundle['candidates'].append(candidate)
        app=GroundedApp(bundle,temp.name,provider=provider);token=app.create()['token']
        return app,token,Path(temp.name)
    def finish(self,app,token):
        end=time.monotonic()+5
        while app.busy and time.monotonic()<end:time.sleep(.01)
        self.assertFalse(app.busy);return app.state(token)
    def assert_rolled_back(self,app,token,state):
        self.assertEqual(state['job'],'error');self.assertFalse(state['rounds'])
        for agent in app.sessions[token]['agents'].values():self.assertEqual(agent.history,[])
    def test_invalid_json_is_saved_but_not_published_or_retained(self):
        app,token,folder=self.app(lambda *a,**kw:{'choices':[{'finish_reason':'stop','message':{'content':'invalid-json'}}]})
        app.ask(token,'Position?','q1');self.assert_rolled_back(app,token,self.finish(app,token))
        turns=[p for p in folder.glob('*/q1.*.json') if not p.name.endswith(('failure.json','round.json','request.json'))]
        self.assertEqual(len(turns),1);self.assertEqual(json.loads(turns[0].read_text())['status'],'error')
    def test_transport_error_is_not_a_successful_abstention_round(self):
        def broken(*a,**kw):raise URLError('authored offline failure')
        app,token,_=self.app(broken);app.ask(token,'Position?','q1')
        self.assert_rolled_back(app,token,self.finish(app,token))

    def test_valid_json_with_a_claim_for_the_wrong_question_role_is_still_an_error(self):
        def wrong_role(system,data,schema,**kwargs):
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
                'answerability':'grounded','claim_ids':[data['PERSPECTIVE']['core_claim_id']],
                'limitation':'none'})}}]}
        app,token,_=self.app(wrong_role);app.ask(token,'Why that?','q1')
        self.assert_rolled_back(app,token,self.finish(app,token))
    def test_second_agent_failure_restores_all_histories_without_automatic_retry(self):
        calls=[]
        def provider(system,data,schema,**kwargs):
            calls.append(data)
            out={'answerability':'grounded','claim_ids':[data['PERSPECTIVE']['core_claim_id']],'limitation':'none'}
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(out) if len(calls)==1 else 'invalid-json'}}]}
        app,token,_=self.app(provider,two=True);app.ask(token,'Position?','q1')
        self.assert_rolled_back(app,token,self.finish(app,token));self.assertEqual(len(calls),2)
        app.ask(token,'Position?','q1');self.assertEqual(len(calls),2)

    def test_failed_followup_keeps_successful_round_and_allows_a_new_request(self):
        calls=[]
        def provider(system,data,schema,**kwargs):
            calls.append(data)
            out={'answerability':'grounded','claim_ids':[data['PERSPECTIVE']['core_claim_id']],'limitation':'none'}
            return {'choices':[{'finish_reason':'stop','message':{
                'content':'invalid-json' if len(calls)==2 else json.dumps(out)}}]}
        app,token,_=self.app(provider)
        app.ask(token,'Position?','q1');first=self.finish(app,token)
        histories={cid:deepcopy(a.history) for cid,a in app.sessions[token]['agents'].items()}
        app.ask(token,'Why?','q2');failed=self.finish(app,token)
        self.assertEqual(failed['job'],'error');self.assertEqual(failed['rounds'],first['rounds'])
        self.assertEqual({cid:a.history for cid,a in app.sessions[token]['agents'].items()},histories)
        app.ask(token,'Why?','q2');self.assertEqual(len(calls),2)
        app.ask(token,'Position?','q3');last=self.finish(app,token)
        self.assertEqual(last['job'],'done');self.assertEqual(len(last['rounds']),2)
        self.assertEqual(len(calls),3)

if __name__=='__main__':unittest.main()
