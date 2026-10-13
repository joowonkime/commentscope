import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.recover_interrupted_membership import recover


class MembershipRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.req={'system':'test','data':{'SOURCE':'original'},'schema':{},'max_tokens':10}
        write(self.root/'plan.json',{'rows':[{'id':'J001','request':self.req,'request_sha256':digest(self.req)}]})
        self.budget=InferenceBudget(self.root/'budget.sqlite','test')
        self.call=self.budget.reserve(self.req,sha(self.root/'plan.json'),90)

    def offline(self):
        return patch('experiments.recover_interrupted_membership.socket.create_connection',side_effect=ConnectionRefusedError())

    def test_missing_response_is_error_not_retry_or_refund(self):
        before=self.budget.summary()
        with self.offline():recover(self.root,self.budget.path)
        stored=read_json(self.root/'J001.json')
        self.assertIsNone(stored['result']['output'])
        self.assertIsNone(stored['result']['seconds'])
        self.assertTrue(stored['result']['errors'])
        self.assertFalse(stored['recovery']['model_retry'])
        self.assertEqual(self.budget.summary(),before)
        with self.offline():recover(self.root,self.budget.path)
        self.assertEqual(self.budget.summary(),before)

    def test_recorded_response_replayed_exactly_without_new_model_call(self):
        value={'verdict':'partial','reason':'Missing condition'}
        response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}
        self.budget.finish(self.call,.4,'ok',response=response)
        with self.offline():recover(self.root,self.budget.path)
        stored=read_json(self.root/'J001.json')
        self.assertEqual(stored['result']['output'],value)
        self.assertEqual(stored['result']['seconds'],.4)
        self.assertEqual(len(self.budget.summary()['calls']),1)

    def test_live_endpoint_cannot_be_recovered(self):
        with patch('experiments.recover_interrupted_membership.socket.create_connection'),self.assertRaises(ValueError):
            recover(self.root,self.budget.path)
        self.assertFalse((self.root/'J001.json').exists())

    def test_ambiguous_attempts_not_selected_for_favorable_output(self):
        self.budget.reserve(self.req,sha(self.root/'plan.json'),90)
        with self.offline(),self.assertRaises(ValueError):recover(self.root,self.budget.path)
        self.assertFalse((self.root/'J001.json').exists())

    def test_database_handle_is_closed_after_recovery(self):
        connections=[];connect=sqlite3.connect
        class TrackedConnection(sqlite3.Connection):
            closed=False
            def close(self):
                self.closed=True
                return super().close()
        def tracked(*args,**kwargs):
            db=connect(*args,**kwargs,factory=TrackedConnection)
            connections.append(db);self.addCleanup(db.close)
            return db
        with self.offline(),patch('experiments.recover_interrupted_membership.sqlite3.connect',side_effect=tracked):
            recover(self.root,self.budget.path)
        self.assertEqual(len(connections),1)
        self.assertTrue(connections[0].closed)
