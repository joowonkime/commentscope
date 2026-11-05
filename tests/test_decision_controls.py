"""Typed transport accounting and blind dependency declarations; no API calls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from commentscope.factory import dependency_decisions as dd
from commentscope.providers import openrouter_decisions as od
from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.providers.budget import BudgetExhausted
from datetime import datetime,timedelta,timezone
from experiments.jev_argument_controls import clock_guard

FIXTURE=Path(__file__).parent/'fixtures/argument-dependency-controls.json'


def synthetic_response(observation):
    req=dd.request(observation,od.DEPLOYMENT);rows={}
    for alias,q in req['questions'].items():
        selected=('value' if observation['id']=='O1' else 'fact') if alias.startswith('kind_') else (
            'asserted' if alias.startswith('authorship_') else 'reason' if alias=='function' and observation['id']=='O1'
            else 'position' if alias=='function' else 'complete' if alias=='coverage'
            else 'necessary_fact' if alias=='relation_U1' and observation['id']=='O2' else 'none')
        rows[alias]={'type':'choice','choice':selected,'confidence':1,
                     'probabilities':{k:int(k==selected) for k in q['criteria']}}
    return {'id':'synthetic-receipt','provider':'TypeSafe','model':'typesafe/jev-1.14-20261014',
            'answers':rows,'usage':{'cost':0.0001,'input_tokens':100,'output_tokens':50}}


class DecisionControlsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=json.loads(FIXTURE.read_text());self.observations={o['id']:o for o in self.fixture['observations']}

    def test_two_blind_observations_cover_four_declaration_controls(self):
        observed={k:dd.observe(o,synthetic_response(o),od.DEPLOYMENT) for k,o in self.observations.items()}
        for case in self.fixture['cases']:
            o=self.observations[case['observation_id']]
            self.assertEqual(dd.compare(o,observed[o['id']],case['declared'])['admitted'],case['expected_admitted'])
        self.assertEqual(len(observed),2)

    def test_expected_labels_and_declared_edges_never_enter_model_request(self):
        payload=dd.request(self.observations['O2'],od.DEPLOYMENT)
        self.assertEqual(set(payload['state']),{'ORIGINAL','PARENT_CONTEXT_ONLY','UNITS','TARGET','OWNER_POSITION'})
        self.assertNotIn('requires',json.dumps(payload));self.assertNotIn('expected_admitted',json.dumps(payload))
        for c in self.fixture['cases'][1:]:
            self.assertEqual(payload,dd.request(self.observations[c['observation_id']],od.DEPLOYMENT))

    def test_literal_span_tamper_and_unknown_declaration_alias_are_rejected(self):
        o=deepcopy(self.observations['O2']);o['units'][0]['text']='Invented.'
        with self.assertRaises(ValueError):dd.request(o,od.DEPLOYMENT)
        o=self.observations['O2'];r=dd.observe(o,synthetic_response(o),od.DEPLOYMENT)
        with self.assertRaises(ValueError):dd.compare(o,r,{'kind':'fact','function':'position','requires':['U99']})

    def test_missing_answer_and_invalid_distribution_cannot_bind(self):
        o=self.observations['O2'];response=synthetic_response(o);response['answers'].pop('coverage')
        with self.assertRaises(ValueError):dd.observe(o,response,od.DEPLOYMENT)
        response=synthetic_response(o);response['answers']['kind_U1']['probabilities']['fact']=float('nan')
        with self.assertRaises(ValueError):dd.observe(o,response,od.DEPLOYMENT)

    def test_nonfactual_prerequisite_and_uncertain_coverage_still_block(self):
        o=self.observations['O2'];r=synthetic_response(o)
        r['answers']['kind_U1'].update(choice='value',probabilities={k:int(k=='value') for k in dd.KINDS})
        bound=dd.observe(o,r,od.DEPLOYMENT)
        self.assertIn('premise_type_or_authorship_unverified',bound['guards'])
        self.assertFalse(dd.compare(o,bound,self.fixture['cases'][1]['declared'])['admitted'])

    def test_model_and_provider_are_bound_and_payload_has_no_chat_fields(self):
        o=self.observations['O1'];payload=dd.request(o,od.DEPLOYMENT)
        self.assertEqual(set(payload),{'model','state','questions','provider'})
        for field,value in [('provider','Other'),('model','typesafe/jev-latest')]:
            response=synthetic_response(o);response[field]=value
            with self.assertRaises(ValueError):dd.observe(o,response,od.DEPLOYMENT)

    def test_wire_identity_keeps_choice_option_order(self):
        first=dd.request(self.observations['O1'],od.DEPLOYMENT);second=deepcopy(first)
        second['questions']['kind_U1']['criteria']=dict(reversed(list(second['questions']['kind_U1']['criteria'].items())))
        self.assertNotEqual(od.wire_sha256(first,od.DEPLOYMENT),od.wire_sha256(second,od.DEPLOYMENT))

    def test_new_trial_deadline_and_subcap_cannot_be_extended(self):
        now=datetime.now(timezone.utc)
        authorization={'started_at':now.isoformat(),'deadline':(now+timedelta(minutes=15)).isoformat(),
            'maximum_new_usd':'0.10','maximum_requests':2,'model':od.DEPLOYMENT['model']}
        clock_guard(authorization,now=now)
        with self.assertRaises(TimeoutError):clock_guard(authorization,now=now+timedelta(minutes=15))
        with self.assertRaises(TimeoutError):clock_guard(authorization,call_seconds=30,now=now+timedelta(minutes=14,seconds=45))
        bad=deepcopy(authorization);bad['maximum_new_usd']='5'
        with self.assertRaises(ValueError):clock_guard(bad,now=now)

    def test_metadata_price_and_context_changes_are_rejected(self):
        e={'name':'TypeSafe | typesafe/jev-1.14-20261014','tag':'typesafe','provider_name':'TypeSafe',
           'context_length':262144,'status':0,'pricing':{'prompt':'0.000000042','completion':'0'}}
        metadata={'id':od.DEPLOYMENT['model'],'endpoints':[e]}
        self.assertEqual(od.preflight(od.DEPLOYMENT,metadata)['reservation_usd'],'0.011010048')
        for field,value in [('context_length',131072),('pricing',{'prompt':'0.000000043','completion':'0'})]:
            bad=deepcopy(metadata);bad['endpoints'][0][field]=value
            with self.assertRaises(ValueError):od.preflight(od.DEPLOYMENT,bad)


class FakeTimeBudget:
    def __init__(self,response=None,error=None):self.response=response;self.error=error;self.calls=0
    def call(self,payload,plan_sha,*,timeout_seconds,provider,typed_request):
        assert typed_request is True
        self.calls+=1
        if self.error:raise self.error
        return self.response


def unused_provider(payload):raise AssertionError('No network in accounting tests')


class DecisionAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.ledger=SpendLedger(Path(self.temp.name)/'spend.sqlite','synthetic',maximum_usd='50')
        self.scope='a'*64;self.plan='b'*64
        first=self.ledger.reserve(self.scope,'c'*64,'0.02',run_limit_usd='5',key_remaining_usd='50')
        self.ledger.finish(first,'0.02')
        self.o=json.loads(FIXTURE.read_text())['observations'][0];self.request=dd.request(self.o,od.DEPLOYMENT)

    def budget(self,base,cap='0.10'):
        return od.PaidDecisions(base,self.ledger,plan_sha256=self.plan,deployment=od.DEPLOYMENT,
            spend_scope_sha256=self.scope,parent_limit_usd='5',opening_scope_charge_usd='0.02',trial_limit_usd=cap,
            paid_provider=unused_provider,key_metadata=lambda:{'limit_remaining':49})

    def test_known_receipt_settles_same_original_money_owner(self):
        base=FakeTimeBudget(synthetic_response(self.o));budget=self.budget(base)
        budget.call(self.request,self.plan,timeout_seconds=30,provider=unused_provider)
        own=self.ledger.summary(plan_sha256=self.scope)
        self.assertEqual(own['maximum_usd'],'5');self.assertEqual(own['charged_usd'],'0.0201')
        self.assertEqual(self.ledger.summary(plan_sha256=self.plan)['calls'],0)

    def test_subcap_rejects_before_time_worker_or_charge(self):
        base=FakeTimeBudget(synthetic_response(self.o));budget=self.budget(base,'0.001')
        with self.assertRaises(BudgetExhausted):budget.call(self.request,self.plan,timeout_seconds=30,provider=unused_provider)
        self.assertEqual(base.calls,0);self.assertEqual(self.ledger.summary()['calls'],1)

    def test_missing_usage_retains_whole_reservation_and_stops_new_calls(self):
        base=FakeTimeBudget({'answers':{}});budget=self.budget(base)
        with self.assertRaises(BudgetExhausted):budget.call(self.request,self.plan,timeout_seconds=30,provider=unused_provider)
        self.assertEqual(self.ledger.summary()['uncertain_calls'],1)
        with self.assertRaises(BudgetExhausted):budget.call(self.request,self.plan,timeout_seconds=30,provider=unused_provider)
        self.assertEqual(base.calls,1)

    def test_semantic_rejection_keeps_known_charge_settled(self):
        response=synthetic_response(self.o);response['provider']='wrong'
        budget=self.budget(FakeTimeBudget(response))
        actual=budget.call(self.request,self.plan,timeout_seconds=30,provider=unused_provider)
        with self.assertRaises(ValueError):dd.observe(self.o,actual,od.DEPLOYMENT)
        self.assertEqual(self.ledger.summary(plan_sha256=self.scope)['charged_usd'],'0.0201')
        self.assertEqual(self.ledger.summary()['uncertain_calls'],0)
