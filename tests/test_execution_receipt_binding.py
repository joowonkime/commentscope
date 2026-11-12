"""Exact execution/receipt binding under a shared cumulative money owner."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from commentscope.providers.openrouter_budget import PaidBudget,SpendLedger
import test_source_fidelity_continuation as fixture

c=fixture.c


class ExecutionReceiptBindingTests(TestCase):
    def make(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        return fixture.SettledLengthTests().make(Path(temp.name))

    def dispatch(self,s,req,result,money,*,plan=None,deployment=None,raw=None):
        actual=c.allocate(req,c.live.executor.openrouter.generation_allocation(s.plan['deployment'],require_explicit=True))
        base=Mock();provider=Mock();response=deepcopy(result['transport']['provider_response'] if raw is None else raw)
        base.call.return_value=response;execution_plan=c.sha(s.directory/'plan.json') if plan is None else plan
        b=PaidBudget(base,money,plan_sha256=execution_plan,deployment=deployment or s.plan['deployment'],maximum_run_usd='150',
            spend_scope_sha256=s.plan['spend_scope_sha256'],paid_provider=provider,key_metadata=lambda:{'limit_remaining':149})
        self.assertEqual(b.call(actual,execution_plan,timeout_seconds=1,provider=provider),response)
        return response

    def test_shared_owner_and_identical_body_select_exact_new_execution_receipt(self):
        s,req,result,_,money=self.make();before=money.summary()
        self.dispatch(s,req,result,money)
        paid=money.summary();self.assertEqual(paid['calls'],before['calls']+1)
        self.assertEqual(c.saved_length(s,'source-evidence-proposal',req),result)
        self.assertEqual(money.summary(),paid)

    def test_same_body_and_cost_under_different_model_and_plan_do_not_collide(self):
        s,req,result,_,money=self.make()
        other=deepcopy(s.plan['deployment']);other['model']='openai/gpt-5.2'
        raw=deepcopy(result['transport']['provider_response']);raw.update(id='other-synthetic',model=other['model'])
        self.dispatch(s,req,result,money,plan='b'*64,deployment=other,raw=raw)
        self.dispatch(s,req,result,money)
        before=money.summary()
        self.assertEqual(c.saved_length(s,'source-evidence-proposal',req),result)
        self.assertEqual(money.summary(),before)

    def test_wrong_receipt_binding_never_falls_back_to_a_same_price_row(self):
        s,req,result,_,money=self.make();self.dispatch(s,req,result,money)
        with closing(sqlite3.connect(money.path)) as db:
            row=db.execute('SELECT call_id,binding FROM receipt_bindings').fetchone();binding=json.loads(row[1])
            binding['provider_response_sha256']='f'*64
            db.execute('UPDATE receipt_bindings SET binding=? WHERE call_id=?',(json.dumps(binding),row[0]));db.commit()
        with self.assertRaises(ValueError):c.saved_length(s,'source-evidence-proposal',req)

    def test_duplicate_exact_bindings_are_not_accepted(self):
        s,req,result,_,money=self.make()
        self.dispatch(s,req,result,money);self.dispatch(s,req,result,money)
        with self.assertRaises(ValueError):c.saved_length(s,'source-evidence-proposal',req)

    def test_legacy_ambiguous_charges_still_stop(self):
        s,req,_,_,money=self.make()
        actual=c.allocate(req,c.live.executor.openrouter.generation_allocation(s.plan['deployment'],require_explicit=True))
        call=money.reserve('a'*64,c.digest(actual),'0.2',run_limit_usd='150',key_remaining_usd='149');money.finish(call,'0.02')
        with self.assertRaises(ValueError):c.saved_length(s,'source-evidence-proposal',req)

    def test_invalid_binding_rolls_back_both_settlement_and_evidence(self):
        s,req,_,_,money=self.make()
        call=money.reserve('a'*64,'d'*64,'0.2',run_limit_usd='150',key_remaining_usd='149');before=money.summary()
        binding=dict(execution_plan_sha256=c.sha(s.directory/'plan.json'),request_sha256='e'*64,
            deployment_sha256=c.digest(s.plan['deployment']),provider_response_sha256='f'*64)
        with self.assertRaises(ValueError):money.finish(call,'0.02',receipt_binding=binding)
        self.assertEqual(money.summary(),before)
        with closing(sqlite3.connect(money.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM receipt_bindings').fetchone()[0],0)

    def test_original_response_and_historical_money_are_preserved(self):
        s,req,result,_,money=self.make();raw=deepcopy(result['transport']['provider_response'])
        self.assertEqual(self.dispatch(s,req,result,money),raw)
        with closing(sqlite3.connect(money.path)) as db:
            calls=db.execute('SELECT * FROM calls ORDER BY id').fetchall()
            binding=json.loads(db.execute('SELECT binding FROM receipt_bindings').fetchone()[0])
        self.assertEqual(binding['provider_response_sha256'],c.digest(raw))
        self.assertEqual(binding['execution_plan_sha256'],c.sha(s.directory/'plan.json'))
        before=money.summary();p=s.plan['spend_policy']
        reopened=SpendLedger(p['ledger'],p['account_id'],maximum_usd='150',opening_charge_usd='1')
        self.assertEqual(reopened.summary(),before)
        with closing(sqlite3.connect(money.path)) as db:
            self.assertEqual(db.execute('SELECT * FROM calls ORDER BY id').fetchall(),calls)
