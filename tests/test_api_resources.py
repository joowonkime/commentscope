"""API storage admission and historical resource policies, without network."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import json

from commentscope.providers import host_resources as host,api_resources as api

GiB=1024**3


class OfflineLargeReceiptClient:
    """Picklable worker fixture. This client has no HTTP implementation."""
    def __init__(self,deployment):self.deployment=deployment
    def generate(self,system,data,schema,max_tokens):
        from commentscope.providers.remote_verification import SOL
        return {'provider':'OpenAI','model':SOL['model'],
                'choices':[{'message':{'content':json.dumps({'payload':'x'*data['size']})},'finish_reason':'stop'}],
                'usage':{'cost':0.00001,'prompt_tokens':10,'completion_tokens':10}}

    def decode_response(self,request,response):
        from commentscope.providers.openrouter import Client
        return Client(self.deployment).decode_response(request,response)

    def transport_record(self,request,response):
        from commentscope.providers.openrouter import Client
        return Client(self.deployment).transport_record(request,response)


class ApiResourceTests(unittest.TestCase):
    def test_explicit_api_policy_accepts_small_host_without_weakening_old_policies(self):
        row={'available_mb':512,'committed_bytes':10*GiB,'commit_limit':12*GiB,'disk_free_bytes':2*GiB}
        self.assertEqual(host.reasons(row,host.HTTP_API_POLICY,workload='http_api'),[])
        self.assertEqual(host.reasons(row,host.HTTP_ONLY_POLICY,workload='http_only'),['low_host_disk'])
        self.assertEqual(host.reasons(row,host.POLICY),['low_host_available_memory','low_host_disk'])
        with self.assertRaises(ValueError):host.reasons(row,host.HTTP_API_POLICY)
        row['disk_free_bytes']=GiB-1
        self.assertEqual(host.reasons(row,host.HTTP_API_POLICY,workload='http_api'),['low_host_disk'])

    def guard(self,root,free=2*GiB):
        return api.SpaceGuard(root,api.STORAGE_POLICY,disk_usage=lambda path:SimpleNamespace(free=free))

    def test_next_call_needs_disk_floor_plus_its_record_headroom(self):
        with tempfile.TemporaryDirectory() as root:
            guard=self.guard(root);guard.check()
            self.assertEqual(guard.summary()['used_bytes'],0)
            with self.assertRaises(host.ResourceStopRequested):
                self.guard(root,GiB+api.STORAGE_POLICY['next_call_headroom_bytes']-1).check()

    def test_run_limit_refuses_before_another_call_and_keeps_existing_records(self):
        with tempfile.TemporaryDirectory() as root:
            file=Path(root)/'receipt.json';file.write_bytes(b'preserve')
            guard=self.guard(root)
            with patch.object(guard,'used_bytes',return_value=GiB-api.STORAGE_POLICY['next_call_headroom_bytes']+1):
                with self.assertRaises(host.ResourceStopRequested):guard.check()
            self.assertEqual(file.read_bytes(),b'preserve')

    def test_final_json_write_checks_actual_utf8_size_and_run_headroom(self):
        value={'text':'한글'*100}
        with tempfile.TemporaryDirectory() as root:
            guard=self.guard(root);guard.before_write(value)
            with patch.object(guard,'used_bytes',return_value=GiB-api.STORAGE_POLICY['next_call_headroom_bytes']-100):
                with self.assertRaises(host.ResourceStopRequested):guard.before_write(value)

    def test_execution_volume_and_host_volume_are_both_checked(self):
        with tempfile.TemporaryDirectory() as root:
            guard=self.guard(root)
            guard.disk_usage=Mock(side_effect=[SimpleNamespace(free=2*GiB),SimpleNamespace(free=0)])
            with self.assertRaises(host.ResourceStopRequested):guard.check()
            self.assertEqual(guard.disk_usage.call_count,2)

    def test_unknown_storage_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):api.SpaceGuard(root,{**api.STORAGE_POLICY,'maximum_run_bytes':10*GiB})

    def test_observer_temporary_file_disappearing_during_scan_is_safe(self):
        import stat
        with tempfile.TemporaryDirectory() as root:
            guard=self.guard(root);gone=Mock();gone.stat.side_effect=FileNotFoundError()
            live=Mock();live.stat.return_value=SimpleNamespace(st_mode=stat.S_IFREG,st_size=10)
            with patch.object(type(guard.directory),'rglob',return_value=iter([gone,live])):
                self.assertEqual(guard.used_bytes(),10)

    def test_large_offline_receipt_actual_sqlite_checkpoint_and_aggregate_fit_call_headroom(self):
        from commentscope.providers import openrouter
        from commentscope.providers.remote_verification import SOL,WireBudget
        from commentscope.providers.budget import InferenceBudget
        from commentscope.providers.openrouter_budget import SpendLedger
        from commentscope.providers.checkpoint_calls import CheckpointRunner
        from commentscope.factory.claim_clusters import sha
        from commentscope.storage import write_json_exclusive as write
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan={'deployment':SOL,'limits':{'analysis_seconds':None,'call_seconds':30}}
            write(root/'plan.json',plan);client=OfflineLargeReceiptClient(SOL)
            money=SpendLedger(root/'money.sqlite','offline-fixture',maximum_usd='50')
            budget=WireBudget(InferenceBudget(root/'time.sqlite','offline-storage-fixture',limit_seconds=None),money,
                plan_sha256=sha(root/'plan.json'),deployment=SOL,maximum_run_usd='0.5',paid_provider=client.generate,
                key_metadata=lambda:{'limit_remaining':50})
            runner=CheckpointRunner(openrouter.Runner(root,plan,budget,client),openrouter.generation_allocation(SOL))
            sample=1_900_000
            req={'system':'Offline synthetic storage stress only.','data':{'size':sample},'max_tokens':100,
                 'schema':{'type':'object','properties':{'payload':{'type':'string','maxLength':sample}},
                           'required':['payload'],'additionalProperties':False}}
            guard=self.guard(root);guard.check();result=runner.call('fixture',req)
            self.assertEqual(result['errors'],[]);self.assertEqual(len(result['output']['payload']),sample)
            aggregate={'records':[result]};guard.before_write(aggregate);write(root/'aggregate.json',aggregate)
            observed=guard.summary()['used_bytes']
            self.assertGreater(observed,2*sample)
            self.assertLess(observed,api.STORAGE_POLICY['next_call_headroom_bytes'])
            self.assertEqual(money.summary()['calls'],1)


if __name__=='__main__':unittest.main()
