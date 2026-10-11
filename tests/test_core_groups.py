from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from commentscope.factory import core_groups as g
from commentscope.factory.automatic import bind_claims
from commentscope.factory.automatic import Calls
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive
from commentscope.agents.runtime import AgentSession
from experiments.shared_core_integration import profiles
from experiments.shared_core_probe import reuse_checkpoints
from experiments.verify_shared_core import no_model
from commentscope.factory.automatic_contract import digest


class CoreGroupTests(unittest.TestCase):
    def test_read_only_replay_missing_call_cannot_write_error_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            calls=Calls(d,{'expires_at':'2099-01-01T00:00:00Z'},no_model)
            with self.assertRaises(RuntimeError):calls('system',{}, {})
            self.assertEqual([p.name for p in Path(d).iterdir()],['manifest.json'])

    def data(self,n=4):
        units=[{'claim_id':str(i),'source_comment_id':'s'+str(i),'mode':'normative',
                'statement':'Claim '+str(i),'spans':[{'text':'Source '+str(i)}]} for i in range(n)]
        links={u['claim_id']:[{'claim_id':v['claim_id']} for v in units if v!=u] for u in units}
        return units,links

    def seed(self,*args):return {'selected_core':'Shared core'}
    def attach(self,*args):return {'allowed':True}

    def test_seed_core_stays_fixed_every_extra_member_has_direct_check(self):
        units,links=self.data()
        calls=[]
        def attach(unit,core):calls.append((unit['claim_id'],core));return {'allowed':True}
        result=g.assemble(units,links,self.seed,attach)
        self.assertEqual(len(result['groups']),1)
        self.assertEqual(result['groups'][0]['member_ids'],['0','1','2','3'])
        self.assertEqual(calls,[('2','Shared core'),('3','Shared core')])
        self.assertEqual(g.replay(units,links,result,self.seed,self.attach),result)
        bad=deepcopy(result);bad['groups'][0]['common_claim']='Changed'
        with self.assertRaises(ValueError):g.replay(units,links,bad,self.seed,self.attach)

    def test_no_transitive_attachment_or_two_source_agent(self):
        units,links=self.data(3)
        result=g.assemble(units,links,self.seed,lambda *args:{'allowed':False})
        self.assertFalse(result['groups'])
        self.assertEqual(result['unassigned_ids'],['0','1','2'])
        units,links=self.data(2)
        def forbidden(*args):self.fail('Insufficient sources should not invoke inference')
        self.assertFalse(g.assemble(units,links,forbidden,forbidden)['groups'])

    def test_budget_and_source_deduplication(self):
        units,links=self.data(3)
        result=g.assemble(units,links,self.seed,self.attach,budget=1)
        self.assertTrue(result['budget_exhausted']);self.assertFalse(result['groups'])
        units[1]['source_comment_id']=units[0]['source_comment_id']
        with self.assertRaises(ValueError):g.assemble(units,links,self.seed,self.attach)

    def test_source_bound_profile_connects_to_existing_agent_session(self):
        raw=json.loads(Path('tests/fixtures/synthetic-snapshot.json').read_text())
        raw['usage']['expires_at']='2099-01-01T00:00:00Z'
        raw['comments']=raw['comments'][:3]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.json';write_json_exclusive(path,raw)
            snapshot=load_snapshot(path).snapshot
            units=[]
            for s in snapshot.comments:
                units+=bind_claims(s,{'status':'claims','claims':[{'statement':'Safety reviews should be mandatory.',
                                                            'mode':'normative','segment_ids':['S000']}]})
            links={u['claim_id']:[{'claim_id':v['claim_id']} for v in units if v!=u] for u in units}
            assembly=g.assemble(units,links,self.seed,self.attach)
            agents=profiles(snapshot,units,assembly)
            self.assertEqual(len(agents),1)
            agent=agents[0];eid=agent['evidence'][0]['evidence_id']
            def provider(system,data,schema):
                output=({'verdict':'supported','reason':'Synthetic mock approval'} if 'POINT' in data else
                        {'answerability':'grounded','points':[{'text':'합성 테스트 응답입니다.','evidence_id':eid}],
                         'missing_information':''})
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}
            turn=AgentSession(agent,provider).ask('Explain')
            self.assertTrue(turn['points'])
            self.assertFalse(agent['human_approved'])
            bad=deepcopy(units);bad[0]['spans'][0]['text']='Changed'
            with self.assertRaises(ValueError):profiles(snapshot,bad,assembly)

    def test_checkpoint_reuse_verifies_model_and_request_hash(self):
        fields=['snapshot_sha256','baseline_sha256','model','nli_model','nli_revision','threshold',
                'runtime_config','prompt_sha256','expires_at']
        manifest={k:'fixed' for k in fields}
        manifest['code_sha256']={k:'fixed' for k in ['src/commentscope/factory/automatic.py',
                        'src/commentscope/factory/claim_frame.py','src/commentscope/providers/local_nli.py']}
        with tempfile.TemporaryDirectory() as d:
            old,new=Path(d)/'old',Path(d)/'new'
            for folder in ['llm','nli']:write_json_exclusive(old/folder/'manifest.json',manifest)
            request={'text':'synthetic'};result={'value':1}
            write_json_exclusive(old/'llm'/('call-'+digest(request)+'.json'),
                                 {'request':request,'result':result,'result_sha256':digest(result)})
            self.assertEqual(reuse_checkpoints(old,new,manifest),1)
            with self.assertRaises(ValueError):reuse_checkpoints(old,new,{**manifest,'model':'changed'})


if __name__=='__main__':unittest.main()
