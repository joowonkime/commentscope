"""An explicit increase adds a bounded allowance without resetting old charges."""
from copy import deepcopy
import unittest

from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write
from tools import shared_factory_trial as shared
import test_shared_factory_trial as fixture


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.h=fixture.SharedTrialTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.observation=self.h.f.root/'budget-observation.json'
        write(self.observation,{'observed_at':'2026-11-10T09:55:41Z','key_metadata':{'limit':150,'limit_remaining':140,'usage':10}})
        self.path=self.h.f.root/'extended.json'
    def extend(self,**changes):
        args={'additional_usd':'1.50','user_request':'예산 늘어났음 확인하고 현재 실험검증계획 진행해'}
        args.update(changes)
        return shared.extend_budget(self.path,self.h.file,self.h.f.auth,self.observation,**args)
    def test_additional_cap_is_exact_and_original_trial_file_opening_and_owner_are_preserved(self):
        old_hash=sha(self.h.file);money=shared.executor.ledger(self.h.plan['spend_policy']);scope=self.h.plan['spend_scope_sha256']
        call=money.reserve(scope,'a'*64,'1.45',run_limit_usd='8',key_remaining_usd='40');money.finish(call,'1.45')
        extended=self.extend();plan=deepcopy(self.h.plan)
        plan.update(subcap_usd=extended['maximum_usd'],trial={'file':str(self.path),'sha256':sha(self.path),'authorization':extended})
        shared.guard(plan)
        self.assertEqual(sha(self.h.file),old_hash);self.assertEqual(read_json(self.h.file)['maximum_usd'],'1.50')
        self.assertEqual(extended['opening_scope_charge_usd'],self.h.authorization['opening_scope_charge_usd'])
        self.assertEqual(extended['maximum_usd'],'2.95');self.assertEqual(extended['additional_maximum_usd'],'1.5')
        capped=shared.executor.SubcapLedger(money,plan)
        call=capped.reserve(scope,'b'*64,'1.50',run_limit_usd='8',key_remaining_usd='38');money.finish(call,'1.50')
        with self.assertRaises(shared.executor.BudgetExhausted):
            capped.reserve(scope,'c'*64,'0.000001',run_limit_usd='8',key_remaining_usd='37')
        with self.assertRaises(ValueError):self.extend()
    def test_missing_request_larger_amount_boolean_and_reopened_old_cap_are_refused(self):
        for changes in ({'user_request':''},{'additional_usd':'1.500000001'},{'additional_usd':True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.extend(**changes)
        self.assertFalse(self.path.exists())
    def test_changed_metadata_or_original_history_invalidates_extension(self):
        value=self.extend();shared.validate_trial(value)
        for changes in ({'opening_scope_charge_usd':'1'},{'maximum_usd':'3.5'},
                        {'money_owner_sha256':'a'*64},{'authorized_scope_charge_usd':'0.5'}):
            bad=deepcopy(value);bad.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):shared.validate_trial(bad)
        bad=deepcopy(value);bad['base_trial']['sha256']='a'*64
        with self.assertRaises(ValueError):shared.validate_trial(bad)
        bad=deepcopy(value);bad['budget_increase_evidence']['sha256']='a'*64
        with self.assertRaises(ValueError):shared.validate_trial(bad)
    def test_an_old_or_insufficient_provider_budget_observation_does_not_grant_more_money(self):
        for limit,remaining in ((50,40),(150,0.5)):
            # Separate immutable observations, never overwrite actual evidence.
            path=self.h.f.root/(str(limit)+'-'+str(remaining)+'.json')
            write(path,{'key_metadata':{'limit':limit,'limit_remaining':remaining}})
            with self.subTest(limit=limit,remaining=remaining),self.assertRaises(ValueError):
                shared.extend_budget(self.path,self.h.file,self.h.f.auth,path,additional_usd='1.50',user_request='실행')
