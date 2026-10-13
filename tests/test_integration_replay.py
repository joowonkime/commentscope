from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import integration_replay as replay
from experiments.audit_model_compare import command


class IntegrationReplayTests(unittest.TestCase):
    def fixture(self, root, *, state='ok'):
        source=root/'old';source.mkdir()
        deployment={'server':{'path':'server'},'models':{'baseline':{'path':'weights'}},
                    'runtime':{'context':4096,'gpu_layers':16,'threads':6,'template_kwargs':{}}}
        plan={key:{} for key in replay.SEMANTIC_FIELDS}
        plan.update(artifact_kind='cached-source-range-integration-0.3',inputs={},code_sha256={},
                    deployment=deployment,budget={'ledger':str(root/'ledger.sqlite'),'cycle_id':'synthetic'})
        write(source/'plan.json',plan);ph=sha(source/'plan.json')
        write(source/'started.json',{'plan_sha256':ph})
        write(source/'failed.json',{'exception_type':'TimeoutError'})
        write(source/'membership-server/runtime.json',{'command':command(deployment,'baseline')})
        write(source/'membership-server/stopped.json',{'returncode':0})
        req={'system':'synthetic','data':{},'schema':{},'max_tokens':50}
        response={'choices':[{'message':{'content':'{"status":"defer"}'},'finish_reason':'stop'}]}
        result={'raw':'{"status":"defer"}','output':{'status':'defer'},'errors':[],'seconds':1.,'usage':None}
        if state!='ok':result={'raw':None,'output':None,'errors':['bounded_call_failed'],'seconds':None,'usage':None}
        write(source/'calls/0001-typing.request.json',{'request':req,'request_sha256':digest(req),'plan_sha256':ph})
        write(source/'calls/0001-typing.result.json',result)
        with closing(sqlite3.connect(plan['budget']['ledger'])) as db, db:
            db.execute('CREATE TABLE calls(plan_sha,request_sha,state,response_json)')
            db.execute('INSERT INTO calls VALUES(?,?,?,?)',(ph,digest(req),state,json.dumps(response) if state=='ok' else None))
        return source,plan,req,result

    def test_prefix_binds_raw_results_and_reuses_failures_without_retry(self):
        for state in ('ok','timeout'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as tmp:
                source,plan,req,result=self.fixture(Path(tmp),state=state)
                entries,files=replay.bind_prefix(source,plan)
                self.assertEqual(len(entries),1)
                self.assertEqual(entries[0]['prefix'],'0001-typing')
                self.assertIn(str(source/'calls/0001-typing.result.json'),files)
                new=Path(tmp)/'new';new.mkdir()
                new_plan={**plan,'reused_calls':entries,'limits':{'analysis_seconds':900,'call_seconds':90}}
                write(new/'plan.json',new_plan)
                budget=Mock();runner=replay.ReplayRunner(new,new_plan,budget)
                self.assertEqual(runner.call('typing',req),result)
                budget.call.assert_not_called()
                saved=read_json(new/'calls/0001-typing.request.json')
                self.assertEqual(saved['plan_sha256'],sha(new/'plan.json'))
                self.assertIn('reused_from',saved)

    def test_changed_semantics_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,plan,_,_=self.fixture(Path(tmp))
            for key in replay.SEMANTIC_FIELDS:
                changed=deepcopy(plan);changed[key]='changed'
                with self.subTest(key=key),self.assertRaises(ValueError):replay.bind_prefix(source,changed)

    def test_completed_run_and_missing_response_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,plan,_,_=self.fixture(Path(tmp))
            (source/'calls/0001-typing.result.json').unlink()
            with self.assertRaises(ValueError):replay.bind_prefix(source,plan)
            write(source/'completed.json',{})
            with self.assertRaises(ValueError):replay.bind_prefix(source,plan)

    def test_unfinished_or_unrepresented_ledger_call_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,plan,_,_=self.fixture(Path(tmp))
            with closing(sqlite3.connect(plan['budget']['ledger'])) as db, db:
                db.execute('UPDATE calls SET state="reserved"')
            with self.assertRaises(ValueError):replay.bind_prefix(source,plan)
        with tempfile.TemporaryDirectory() as tmp:
            source,plan,_,_=self.fixture(Path(tmp))
            with closing(sqlite3.connect(plan['budget']['ledger'])) as db, db:
                db.execute('INSERT INTO calls VALUES(?,?,?,?)',(sha(source/'plan.json'),'unrepresented','timeout',None))
            with self.assertRaises(ValueError):replay.bind_prefix(source,plan)

    def test_replay_rejects_changed_request_and_changed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,plan,req,_=self.fixture(Path(tmp));entries,_=replay.bind_prefix(source,plan)
            new=Path(tmp)/'new';new.mkdir();plan={**plan,'reused_calls':entries}
            write(new/'plan.json',plan);budget=Mock()
            runner=replay.ReplayRunner(new,plan,budget)
            with self.assertRaises(ValueError):runner.call('detail',req)
            (source/'calls/0001-typing.result.json').write_text('{}')
            runner=replay.ReplayRunner(new,plan,budget)
            with self.assertRaises(ValueError):runner.call('typing',req)
            budget.call.assert_not_called()

    def test_ledger_response_tampering_is_rejected_before_freezing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,plan,_,_=self.fixture(Path(tmp))
            different={'choices':[{'message':{'content':'{"status":"changed"}'},'finish_reason':'stop'}]}
            with closing(sqlite3.connect(plan['budget']['ledger'])) as db, db:
                db.execute('UPDATE calls SET response_json=?',(json.dumps(different),))
            with self.assertRaises(ValueError):replay.bind_prefix(source,plan)

    def test_only_calls_after_prefix_use_the_bounded_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,plan,req,result=self.fixture(Path(tmp));entries,_=replay.bind_prefix(source,plan)
            new=Path(tmp)/'new';new.mkdir();plan={**plan,'reused_calls':entries}
            write(new/'plan.json',plan);runner=replay.ReplayRunner(new,plan,Mock())
            with patch.object(replay.Runner,'call',return_value={'new_call':True}) as fresh:
                self.assertEqual(runner.call('typing',req),result)
                fresh.assert_not_called()
                self.assertEqual(runner.call('detail',req),{'new_call':True})
                fresh.assert_called_once_with('detail',req)

    def test_read_connection_is_closed_on_success_and_rejection(self):
        connect = sqlite3.connect
        for state in ('ok', 'reserved'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                source, plan, _, _ = self.fixture(Path(tmp), state=state)
                opened = []
                def tracking(*args, **kwargs):
                    db = connect(*args, **kwargs); opened.append(db); return db
                with patch.object(replay.sqlite3, 'connect', side_effect=tracking):
                    if state == 'ok': replay.bind_prefix(source, plan)
                    else:
                        with self.assertRaises(ValueError): replay.bind_prefix(source, plan)
                self.assertEqual(len(opened), 1)
                with self.assertRaises(sqlite3.ProgrammingError): opened[0].execute('SELECT 1')
