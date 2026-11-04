from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import serve_mvp as server
from commentscope.product.analysis import Analysis
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from commentscope.providers.openrouter_budget import SpendLedger
from experiments.grounding_contract_demo import fixture
from test_openrouter import deployment


class ProductServerPlanTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='runs',prefix='mvp-plan-test-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.addCleanup(patch.stopall)
        patch.dict(os.environ,{'OPENROUTER_API_KEY':'synthetic-test-key'}).start()
        self.analysis=Analysis(fixture(),{'synthetic':True})
        self.factory=self.root/'factory';write(self.factory/'snapshot.json',{'synthetic':True})
        write(self.factory/'plan.json',{'snapshot':str(self.factory/'snapshot.json'),'snapshot_sha256':sha(self.factory/'snapshot.json')})
        write(self.factory/'artifacts/agent-inputs.json',{'bundle':fixture()});write(self.factory/'artifacts/output.json',{})
        self.policy={'account_id':'synthetic-test','ledger':str(self.root/'spend.sqlite'),
                     'maximum_usd':'50','opening_charge_usd':'0.1'}
        write(self.root/'policy.json',self.policy)
        self.cycle={'version':server.CYCLE_VERSION,'tasks':['TASK-004'],
            'started_at':datetime.now(timezone.utc).isoformat(),
            'deadline':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            'maximum_additional_usd':'5','selected_deployment':{**deployment(),'context':65536},
            'shared_policy_file':str(self.root/'policy.json')}
        self.cycle_file=self.root/'cycle.json';write(self.cycle_file,self.cycle)
        patch.object(server,'from_factory',return_value=self.analysis).start()
        patch.object(server,'source_code_hashes',return_value={'synthetic.py':'fixed'}).start()
        patch.object(server,'archive_sources').start()
        patch.object(server,'provider_preflight',return_value={'synthetic':True}).start()
        patch.object(server,'key_metadata',return_value={'limit_remaining':50}).start()
        self.base=patch.object(server,'InferenceBudget').start().return_value
        self.base.call.side_effect=self.response

    def response(self,request,*args,**kwargs):
        data=request['data'];output={'items':[{'relation':'agreement','user_span_ids':['I000'],
            'perspective_claim_ids':[data['PERSPECTIVE_CLAIMS'][0]['id']],
            'explanation':'Synthetic comparison.','consideration_question':None}]}
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}],
                'usage':{'cost':0.00001,'prompt_tokens':1,'completion_tokens':1}}

    def prepare(self,name='server'):
        directory=self.root/name
        plan=server.prepare(directory,self.factory,self.cycle_file,session_ttl_seconds=3600,room_maximum_usd='1')
        return directory,plan

    def compare(self,app):
        token=secrets.token_urlsafe(32)
        _,session=app.handle('POST','/api/v1/sessions',token,{'analysis_id':self.analysis.id,
            'bundle_revision':self.analysis.revision,'initial_opinion':'I support it.','request_id':'create'})
        path='/api/v1/sessions/'+session['session_id']
        _,job=app.handle('POST',path+'/comparisons',token,{'perspective_id':'P1','initial_revision':1,'request_id':'compare'})
        until=time.monotonic()+3
        while time.monotonic()<until:
            result=app.handle('GET','/api/v1/jobs/'+job['job_id'],token)[1]
            if result['state'] not in ('queued','running'):return result
            time.sleep(.01)
        self.fail('Job did not settle')

    def test_prepare_does_not_infer_and_does_not_publish_key_or_approval(self):
        directory,plan=self.prepare()
        self.base.call.assert_not_called()
        self.assertEqual(plan['spend_scope_sha256'],sha(self.cycle_file))
        self.assertFalse(plan['quality_gate_passed'])
        self.assertNotIn('synthetic-test-key',(directory/'plan.json').read_text(encoding='utf-8'))

    def test_two_server_plans_share_one_existing_cycle_charge(self):
        for name in ('first','second'):
            directory,_=self.prepare(name)
            product,legacy,broker=server.build(directory)
            try:self.assertEqual(self.compare(product)['state'],'succeeded')
            finally:product.close()
        ledger=SpendLedger(self.policy['ledger'],self.policy['account_id'],maximum_usd='50',opening_charge_usd='0.1')
        own=ledger.summary(plan_sha256=sha(self.cycle_file))
        self.assertEqual(own['charged_usd'],'0.00002');self.assertEqual(own['maximum_usd'],'5')
        self.assertEqual(self.base.call.call_count,2)

    def test_changed_cycle_and_bundle_refuse_before_inference(self):
        directory,_=self.prepare()
        value=read_json(self.cycle_file);value['maximum_additional_usd']='6';self.cycle_file.write_text(json.dumps(value))
        with self.assertRaises(ValueError):server.build(directory)
        self.base.call.assert_not_called()

    def test_expired_cycle_refuses_new_call_and_keeps_read_and_save_available(self):
        directory,_=self.prepare();product,legacy,broker=server.build(directory)
        try:
            with patch.object(server,'cycle_guard',side_effect=TimeoutError('deadline')):
                self.assertEqual(broker.status(),'cycle_deadline')
                self.assertEqual(product.handle('GET','/api/v1/analyses','')[0],200)
        finally:product.close()
        self.base.call.assert_not_called()
