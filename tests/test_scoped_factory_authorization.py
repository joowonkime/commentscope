"""Jev/chat spend one immutable scope; existing cycles and defaults are intact."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
import json
from unittest.mock import patch
import unittest

from commentscope.factory.claim_clusters import sha,read_json
from commentscope.factory import argument_observations as obs
from commentscope.providers import scoped_authorization as auth,openrouter_decisions as od
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.storage import write_json_exclusive as write
from experiments import openrouter_factory_pipeline as executor
from test_jev_audit_integration import receipt
import test_openrouter_factory_pipeline as fixture


class ScopedFactoryTests(unittest.TestCase):
    setUp=fixture.OpenRouterExecutorTests.setUp

    def prepare(self,directory=None):
        if not hasattr(self,'scope_file'):
            self.policy.update(maximum_usd='50');write(self.root/'policy.json',self.policy)
            self.scope_file=self.root/'authorization.json';now=datetime.now(timezone.utc)
            write(self.scope_file,{'version':auth.VERSION,'tasks':['TASK-005','TASK-006'],'gates':['G1','G2','G3'],
                'started_at':now.isoformat(),'deadline':(now+timedelta(hours=1)).isoformat(),
                'maximum_additional_usd':'8','shared_policy_file':str(self.root/'policy.json'),
                'chat_deployment':self.deployment,'decisions_deployment':od.DEPLOYMENT})
            patch.object(executor,'transfer_admission',return_value={}).start()
            patch.object(od,'preflight',return_value={}).start()
            def process(snapshot,runner,*args,**kwargs):
                for name,value in self.artifacts.items():kwargs['save'](name,value)
                return deepcopy(self.output)
            self.process.side_effect=process
        return executor.prepare(directory or self.run_dir,self.deployment,self.materials,self.policy,8,
            discovery_mode='free',scope_file=self.scope_file,argument_audit_protocol=obs.JEV_SPLIT)

    def test_both_transports_and_fresh_plans_debit_same_scope_and_completed_replay_is_free(self):
        self.prepare();original=self.time_budget.call.side_effect
        def respond(request,*args,**kwargs):
            return receipt(request) if 'questions' in request else original(request,*args,**kwargs)
        self.time_budget.call.side_effect=respond
        def process(snapshot,runner,*args,**kwargs):
            from commentscope.factory import argument_dependencies as deps
            from experiments.jev_transfer_controls import FIXTURE
            c=read_json(FIXTURE)['sources'][0];p=deps.requests(deps.tasks(c['record'],c['cores'])[0])[0]
            runner.decide('typed-test',p)
            for name,value in self.artifacts.items():kwargs['save'](name,value)
            return deepcopy(self.output)
        self.process.side_effect=process
        first=executor.run(self.run_dir);second_dir=self.root/'second';self.prepare(second_dir);second=executor.run(second_dir)
        self.assertEqual(first['spend_scope_sha256'],sha(self.scope_file))
        self.assertEqual(second['spend_scope_sha256'],first['spend_scope_sha256'])
        self.assertEqual(second['run_spending']['calls'],14)
        count=self.time_budget.call.call_count
        self.assertEqual(executor.run(second_dir),second);self.assertEqual(self.time_budget.call.call_count,count)

    def test_model_or_authorization_change_rejects_before_dispatch(self):
        self.prepare();plan=read_json(self.run_dir/'plan.json');plan['decisions_deployment']['model']='other/model'
        (self.run_dir/'plan.json').write_text(json.dumps(plan));(self.run_dir/'frozen.json').write_text(json.dumps({'plan_sha256':sha(self.run_dir/'plan.json')}))
        with self.assertRaises(ValueError):executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()

    def test_scope_cap_is_not_reset_and_g4_is_outside_authorization(self):
        self.prepare();ledger=SpendLedger(self.policy['ledger'],self.policy['account_id'],maximum_usd='50')
        cid=ledger.reserve(sha(self.scope_file),'a'*64,'7.99999',run_limit_usd='8',key_remaining_usd='50');ledger.finish(cid,'7.99999')
        with self.assertRaises(executor.BudgetExhausted):executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()
        with self.assertRaises(ValueError):auth.bind(self.scope_file,self.deployment,self.policy,'8','G4')

    def test_expired_scope_cannot_be_extended_by_new_plan(self):
        self.prepare();binding=read_json(self.run_dir/'plan.json')['scoped_authorization'];a=binding['authorization']
        with self.assertRaises(TimeoutError):auth.guard(a,observed_at=datetime.fromisoformat(a['deadline']))
        changed=deepcopy(a);changed['maximum_additional_usd']='9'
        with self.assertRaises(ValueError):auth.guard(changed)

    def test_transfer_resource_stop_resumes_same_plan_without_resetting_before_or_charge(self):
        from experiments import jev_transfer_controls as transfer
        self.prepare();directory=self.root/'transfer'
        transfer.prepare(directory,self.scope_file)
        with patch.object(transfer,'key_metadata',return_value={'limit_remaining':50}),\
             patch.object(transfer,'InferenceBudget',return_value=self.time_budget),\
             patch.object(transfer.host_resources,'watch',side_effect=executor.host_resources.ResourceStopRequested('low memory')):
            with self.assertRaises(executor.host_resources.ResourceStopRequested):transfer.run(directory)
        self.time_budget.call.assert_not_called();before=sha(directory/'before.json')
        self.time_budget.call.side_effect=lambda payload,*a,**k:receipt(payload)
        with patch.object(transfer,'key_metadata',return_value={'limit_remaining':50}),\
             patch.object(transfer,'InferenceBudget',return_value=self.time_budget),\
             patch.object(transfer.host_resources,'watch',return_value=nullcontext()):
            report=transfer.run(directory)
            count=self.time_budget.call.call_count
            self.assertEqual(transfer.run(directory),report)
            self.assertEqual(self.time_budget.call.call_count,count)
        self.assertEqual(sha(directory/'before.json'),before)
        self.assertTrue((directory/'attempts/0001.failed.json').exists())
        self.assertTrue((directory/'attempts/0002.started.json').exists())


if __name__=='__main__':unittest.main()
