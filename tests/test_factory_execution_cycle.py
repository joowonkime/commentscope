"""Real executor/ledger composition with synthetic model receipts only."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers.execution_cycle import CYCLE_VERSION
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.storage import write_json_exclusive as write
from experiments import openrouter_factory_pipeline as executor
import test_openrouter_factory_pipeline as fixtures


class FactoryCycleTests(unittest.TestCase):
    setUp=fixtures.OpenRouterExecutorTests.setUp
    def prepare(self):
        self.cycle_file=self.root/'cycle.json'
        self.policy.update(maximum_usd='50')
        write(self.root/'policy.json',self.policy)
        cycle={'version':CYCLE_VERSION,'tasks':['TASK-004','TASK-005'],
            'started_at':datetime.now(timezone.utc).isoformat(),
            'deadline':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            'maximum_additional_usd':'5','selected_deployment':self.deployment,
            'shared_policy_file':str(self.root/'policy.json')}
        write(self.cycle_file,cycle)
        return self.prepare_bound(self.run_dir)

    def prepare_bound(self,directory):
        return executor.prepare(directory,self.deployment,self.materials,self.policy,5,
                                cycle_file=self.cycle_file)

    def test_factory_plans_share_previous_cycle_spending(self):
        plan=self.prepare()
        ledger=SpendLedger(self.policy['ledger'],self.policy['account_id'],maximum_usd='50')
        call=ledger.reserve(sha(self.cycle_file),'a'*64,'0.2',run_limit_usd='5',key_remaining_usd='50')
        ledger.finish(call,'0.1')
        first=executor.run(self.run_dir)
        second_dir=self.root/'second';self.prepare_bound(second_dir)
        second=executor.run(second_dir)
        own=ledger.summary(plan_sha256=sha(self.cycle_file))
        self.assertEqual(own['calls'],13)
        self.assertEqual(own['charged_usd'],'0.10012')
        self.assertEqual(own['maximum_usd'],'5')
        self.assertEqual(first['spend_scope_sha256'],second['spend_scope_sha256'])
        self.assertNotEqual(first['plan_sha256'],second['plan_sha256'])
        self.assertEqual(executor.run(second_dir),second)
        self.assertEqual(ledger.summary(plan_sha256=sha(self.cycle_file)),own)

    def test_changed_cycle_rejected_before_paid_or_auxiliary_model_work(self):
        self.prepare();cycle=read_json(self.cycle_file);cycle['maximum_additional_usd']='6'
        self.cycle_file.write_text(json.dumps(cycle))
        with self.assertRaises(ValueError):executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()

    def test_previously_spent_cycle_cannot_be_reset_with_a_fresh_factory_plan(self):
        self.prepare()
        ledger=SpendLedger(self.policy['ledger'],self.policy['account_id'],maximum_usd='50')
        call=ledger.reserve(sha(self.cycle_file),'b'*64,'4.99999',run_limit_usd='5',key_remaining_usd='50')
        ledger.finish(call,'4.99999')
        with self.assertRaises(executor.BudgetExhausted):
            executor.run(self.run_dir)
        self.time_budget.call.assert_not_called()
        own=ledger.summary(plan_sha256=sha(self.cycle_file))
        self.assertEqual(own['calls'],1)
        self.assertEqual(own['charged_usd'],'4.99999')
        self.assertEqual(own['reserved_calls'],0)

    def test_different_cap_or_model_cannot_create_another_cycle_limit(self):
        self.prepare();self.preflight.reset_mock()
        for cap,model in ((4,self.deployment),(5,{**self.deployment,'model':'other/model'})):
            with self.assertRaisesRegex(ValueError,'original cycle'):
                executor.prepare(self.root/'bad',model,self.materials,self.policy,cap,cycle_file=self.cycle_file)
        self.preflight.assert_not_called();self.time_budget.call.assert_not_called()

    def test_expiry_between_calls_stops_before_second_model_dispatch(self):
        self.prepare();original=executor.check_cycle;checks=0
        def timed(plan,**kwargs):
            nonlocal checks
            if kwargs.get('call_seconds'):
                checks+=1
                if checks==2:raise TimeoutError('cycle deadline')
            return original(plan,**kwargs)
        # GroundedSession persists an error turn; runtime_probe then refuses it.
        with patch.object(executor,'check_cycle',side_effect=timed),self.assertRaisesRegex(ValueError,'runtime turn failed'):
            executor.run(self.run_dir)
        self.assertEqual(self.time_budget.call.call_count,1)
        self.assertFalse((self.run_dir/'completed.json').exists())

    def test_completed_result_can_be_read_after_deadline_without_model_work(self):
        self.prepare();completed=executor.run(self.run_dir);count=self.time_budget.call.call_count
        def expired(plan,**kwargs):
            if not kwargs.get('allow_expired'):raise TimeoutError('deadline')
        with patch.object(executor,'check_cycle',side_effect=expired):
            self.assertEqual(executor.run(self.run_dir),completed)
        self.assertEqual(self.time_budget.call.call_count,count)

    def test_resource_stop_is_a_structured_cli_result_before_any_model_call(self):
        self.prepare()
        with patch.object(executor.host_resources,'watch',side_effect=executor.host_resources.ResourceStopRequested('low disk')),patch('builtins.print') as printed:
            self.assertEqual(executor.main(['run',str(self.run_dir)]),2)
        result=json.loads(printed.call_args.args[0])
        self.assertEqual(result['reason'],'host_resources')
        self.assertFalse(result['automatic_retry'])
        self.time_budget.call.assert_not_called();self.metadata.assert_not_called()
