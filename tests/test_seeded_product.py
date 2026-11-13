from copy import deepcopy
from decimal import Decimal
import json
import unittest

from commentscope.product.analysis import Analysis
from commentscope.product.app import ProductApp
from commentscope.providers.budget import BudgetExhausted
from test_seeded_perspectives import seeded_bundle
from test_seeded_runtime import response, verifier
import test_product_app as fixtures


class SeededProductTests(unittest.TestCase):
    call=fixtures.ProductAppTests.call
    job=fixtures.ProductAppTests.job
    room=fixtures.ProductAppTests.room

    def setUp(self):
        self.decisions=[]
        fixtures.ProductAppTests.setUp(self)

    def build(self):
        bundle=seeded_bundle();bundle['candidates'].append({**deepcopy(bundle['candidates'][0]),'id':'P2'})
        self.analysis=Analysis(bundle,{'source':'synthetic-test'})
        return ProductApp(self.path,[self.analysis],self.model,session_ttl_seconds=3600,
            room_maximum_usd='1',reservation=lambda req:'0.001',
            decision=self.decide,decision_reservation=lambda:'0.002')

    def model(self,stage,request):
        self.calls.append(deepcopy(request))
        return {'output':response(),'errors':[],'new_cost_usd':'0.0001'}

    def decide(self,stage,payload):
        self.decisions.append(deepcopy(payload));return verifier(payload)

    def start(self,mode='group'):
        room=self.room() if mode=='group' else self.call('POST',self.base+'/rooms',{
            'mode':'one_to_one','participant_ids':['P1'],'initial_revision':1,'request_id':'direct'})[1]
        path='/api/v1/rooms/'+room['room_id']
        args={'opening_question':'Why?','expected_revision':room['revision'],'request_id':'start'}
        job=self.call('POST',path+'/start',args)[1]
        return path,args,self.job(job)

    def cost(self,path):
        from commentscope.product.store import decode
        with self.app.store.transaction() as db:
            value=decode(db.execute('SELECT data FROM rooms WHERE id=?',(path.rsplit('/',1)[-1],)).fetchone())
            return Decimal(value['cost_usd'])

    def test_group_preserves_origins_peer_context_counts_and_both_charges(self):
        path,args,job=self.start();self.assertEqual(job['state'],'succeeded')
        room=self.call('GET',path)[1];agents=[m for m in room['messages'] if m['author_kind']=='agent']
        self.assertEqual(len(agents),4);self.assertEqual(len(self.decisions),4)
        self.assertEqual(self.cost(path),Decimal('0.000404'))
        self.assertEqual(agents[2]['reply_to_message_id'],agents[1]['message_id'])
        self.assertTrue(self.calls[2]['data']['PEER_CONTEXT_ONLY'])
        self.assertEqual(self.calls[0]['data']['HISTORY_CONTEXT_ONLY'],[])
        self.assertEqual(self.calls[1]['data']['HISTORY_CONTEXT_ONLY'],[])
        for m in agents:
            self.assertEqual(m['evidence_scope'],'seeded_provenance')
            self.assertEqual([p['origin'] for p in m['points']],['original_comment','ai_reasoning'])
            self.assertEqual([p['member_source_count'] for p in m['points']],[1,0])
        self.call('POST',path+'/start',args)
        self.assertEqual(len(self.calls),4)
        self.app.close();self.app=self.build()
        self.assertEqual(self.call('GET',path)[1]['messages'],room['messages'])

    def test_one_to_one_and_public_count_scope(self):
        path,args,job=self.start('direct');self.assertEqual(job['state'],'succeeded')
        self.assertEqual(self.call('GET',path)[1]['turn_count'],1)
        self.assertEqual(self.analysis.public()['perspectives'][0]['source_count'],1)
        self.assertEqual(self.analysis.public()['perspectives'][0]['support_scope'],
                         'verified_comment_sources_not_population_share')

    def test_typed_failure_keeps_generation_and_verification_charges_and_previous_turn(self):
        original=self.app.decision;count=0
        def fail(stage,payload):
            nonlocal count
            count+=1;raw=original(stage,payload)
            if count==2:raw['provider']='unbound'
            return raw
        self.app.decision=fail
        path,args,job=self.start();self.assertEqual(job['state'],'failed')
        room=self.call('GET',path)[1]
        self.assertEqual(room['turn_count'],1);self.assertEqual(room['state'],'error')
        self.assertEqual(self.cost(path),Decimal('0.000202'))
        self.call('POST',path+'/start',args);self.assertEqual(count,2)

    def test_combined_reservation_refuses_before_any_model_call(self):
        self.app.room_limit=Decimal('0.0025')
        path,args,job=self.start();self.assertEqual(job['state'],'failed')
        self.assertFalse(self.calls);self.assertFalse(self.decisions)
        self.assertEqual(self.cost(path),0)

    def test_unknown_typed_cost_requires_reconciliation_and_keeps_generation_charge(self):
        def unknown(stage,payload):
            raw=verifier(payload);raw.pop('usage');return raw
        self.app.decision=unknown
        path,args,job=self.start();self.assertEqual(job['state'],'needs_reconciliation')
        self.assertEqual(self.cost(path),Decimal('0.0001'))

    def test_missing_verifier_or_expired_reference_refuses_before_dispatch(self):
        with self.assertRaises(ValueError):
            ProductApp(self.path,[self.analysis],self.model,session_ttl_seconds=3600,
                room_maximum_usd='1',reservation=lambda req:'0.001')
        self.analysis.bundle['documents'][0]['expires_at']='2020-01-01T00:00:00Z'
        self.assertEqual(self.analysis.public()['status'],'expired')
        self.assertFalse(self.calls)

    def test_known_charge_attached_to_transport_failure_is_preserved(self):
        def failed(stage,payload):
            exc=BudgetExhausted('settled transport failure requires reconciliation')
            exc.new_cost_usd='0.000003'
            raise exc
        self.app.decision=failed
        path,args,job=self.start()
        self.assertEqual(job['state'],'needs_reconciliation')
        self.assertEqual(self.cost(path),Decimal('0.000103'))


if __name__=='__main__':unittest.main()
