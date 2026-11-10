"""Financial inheritance and immutable component scoring, never live inference."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers import openrouter_decisions as od
from commentscope.storage import write_json_exclusive as write
from tools import jev_membership_probe as probe,shared_factory_trial as shared
import test_shared_factory_trial as shared_fixture
from test_jev_membership import responses


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.h=shared_fixture.SharedTrialTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.directory=self.h.f.root/'membership-component'
        self.parent=self.h.f.root/'financial.json';write(self.parent,self.h.plan)
        self.resume=self.h.f.root/'new-resume.json'
        owner=self.h.plan['authorization']['authorization']['money_owner']['file']
        auth=shared.executor.authorize(self.resume,Path(owner),resume_request='실제 진행: 돈과 정확도 모두')
        self.plan={'artifact_kind':probe.VERSION,'formal_admission_eligible':False,'quality_gate_passed':False,
            'membership_deployment':deepcopy(od.DEPLOYMENT),'membership_judge_protocol':probe.j.VERSION,
            'financial_parent':{'file':str(self.parent),'sha256':sha(self.parent),'plan':deepcopy(self.h.plan)},
            'resume_authorization':{'file':str(self.resume),'sha256':sha(self.resume),'authorization':auth},
            **{k:deepcopy(self.h.plan[k]) for k in ('spend_scope_sha256','spend_policy','maximum_cost_usd')},'expires_at':'2099-01-01T00:00:00Z'}

    def test_resume_changes_time_without_changing_original_trial_money(self):
        probe.guard(self.plan)
        self.assertEqual(probe.parent(self.plan)['opening_scope_charge_usd'],self.h.authorization['opening_scope_charge_usd'])
        self.assertEqual(probe.parent(self.plan)['subcap_usd'],'1.50')
        for key,value in (('maximum_cost_usd','50'),('formal_admission_eligible',True),('membership_judge_protocol','different')):
            bad=deepcopy(self.plan);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):probe.guard(bad)

    def test_nested_original_trial_does_not_reset_when_component_opens(self):
        ledger=shared.executor.ledger(self.plan['spend_policy']);scope=self.plan['spend_scope_sha256']
        original=shared.executor.SubcapLedger(ledger,probe.parent(self.plan))
        call=original.reserve(scope,'a'*64,'1.45',run_limit_usd='8',key_remaining_usd='30');ledger.finish(call,'1.45')
        # A newly named component cannot re-open the old1.50 trial.
        with self.assertRaises(shared.executor.BudgetExhausted):
            original.reserve(scope,'b'*64,'0.06',run_limit_usd='8',key_remaining_usd='28')

    def test_fixture_expected_answers_do_not_enter_typed_state(self):
        cases=read_json(probe.FIXTURE)['cases'];self.assertEqual(len(cases),6)
        for raw in cases:
            case=probe.synthetic(raw);task=probe.case_task(case)
            self.assertEqual(len(task['requests']),1)
            for payload in task['requests']:
                self.assertNotIn('expected_relation',str(payload));self.assertNotIn('annotation_note',str(payload))
                self.assertNotIn(raw['id'],payload['state']['READING_INPUT']['ORIGINAL']['source_id'])
        self.assertLess(od.reservation(od.DEPLOYMENT)*11,Decimal('0.127202540'))

    def test_scoring_distinguishes_raw_error_host_veto_and_false_negative(self):
        case=probe.synthetic(read_json(probe.FIXTURE)['cases'][2]);task=probe.case_task(case)
        from test_raw_membership_source_context import observation
        wrong={**observation(),'scope_preserved':'no'}
        proof=probe.j.bind(task,responses(task,wrong));row=probe.assess(case,proof)
        self.assertTrue(row['raw_false_support']);self.assertFalse(row['invalid_support'])
        self.assertFalse(row['relation_correct']);self.assertTrue(row['support_correct'])
        positive=probe.synthetic(read_json(probe.FIXTURE)['cases'][0]);task=probe.case_task(positive)
        held=probe.j.bind(task,responses(task,observation(relation='uncertain')))
        self.assertTrue(probe.assess(positive,held)['missed_valid_support'])
