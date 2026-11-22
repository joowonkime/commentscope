from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from commentscope.storage import write_json_exclusive as write
from tools import launch_mvp as launch
from tools import review_product_http as http_review
from commentscope.providers.openrouter_budget import SpendLedger


class LaunchTests(unittest.TestCase):
    def test_host_review_retains_full_reservation_and_requires_matching_terminal_evidence(self):
        folder = self.state / 'server'
        policy = {'ledger': str(self.state / 'spend.sqlite'), 'account_id': 'synthetic',
                  'maximum_usd': '1', 'opening_charge_usd': '0'}
        plan = {'spend_policy': policy, 'spend_scope_sha256': 'b'*64}
        write(self.state / 'authorization.json', {'policy': policy})
        req = 'c'*64
        write(folder / 'calls/0001-product-comparison.request.json', {'request_sha256': req})
        ledger = SpendLedger(policy['ledger'], 'synthetic', maximum_usd='1')
        call = ledger.reserve('b'*64, req, '0.1', run_limit_usd='1', key_remaining_usd='1')
        with patch.object(launch.serve_mvp, 'validate', return_value=plan), \
                patch.object(http_review, 'terminal_evidence') as evidence:
            with self.assertRaisesRegex(ValueError, 'active'):
                http_review.review(self.state)
            evidence.assert_not_called()
            ledger.finish(call, None)
            evidence.side_effect = ValueError('Unconfirmed interruption')
            with self.assertRaisesRegex(ValueError, 'Unconfirmed'):
                http_review.review(self.state)
            self.assertEqual(ledger.summary()['uncertain_calls'], 1)
            evidence.side_effect = None
            evidence.return_value = {'ledger_call_id': call, 'retained_units': launch.units('0.1'), 'http_status': 502}
            self.assertIn('Retained USD 0.1', http_review.review(self.state))
            self.assertEqual(ledger.summary()['conservative_usd'], '0.1')
            self.assertIn('No uncertain charge', http_review.review(self.state))

    def setUp(self):
        root=TemporaryDirectory(dir='runs')
        self.addCleanup(root.cleanup)
        self.root=Path(root.name).resolve()
        self.state=self.root/'state'
        self.state.mkdir()
        self.expiry=(datetime.now(timezone.utc)+timedelta(days=25)).isoformat()
        self.args=(self.state,self.root/'catalog.json',[self.root/'video'],
                   [SimpleNamespace(id='A1',compiled={'expires_at':self.expiry})],self.root/'deployment.json')
        write(self.args[1],{'analyses':['video'],'deployment':'deployment.json'})
        write(self.args[4],{})
        self.key=patch.dict('os.environ',{'OPENROUTER_API_KEY':'synthetic-bound-test'})
        self.key.start()
        self.addCleanup(self.key.stop)

    def test_restart_and_partial_setup_keep_one_binding_and_settled_opening_charge(self):
        until=(datetime.now(timezone.utc)+timedelta(days=21)).isoformat()
        prepared=[]
        def prepare(path,*args,**kwargs):
            prepared.append(path)
            if len(prepared)==1:raise RuntimeError('transient preflight')
            path.mkdir()
        with patch.object(launch.serve_mvp,'key_metadata',return_value={'limit':150,'limit_remaining':115,'usage':33}) as metadata, \
                patch.object(launch.serve_mvp,'prepare',side_effect=prepare):
            with self.assertRaises(RuntimeError):launch.server_plan(*self.args,'1',until)
            path=launch.server_plan(*self.args,'1',until)
            self.assertEqual(path,launch.server_plan(*self.args,'1.00',until))
            self.assertEqual(len(prepared),2)
            metadata.assert_called_once()
            scope=launch.read_json(self.state/'authorization.json')
            self.assertEqual(float(scope['policy']['opening_charge_usd']),35)
            self.assertNotIn('synthetic-bound-test',str(scope))
            for cap,deadline in [('2',until),('1',None)]:
                with self.assertRaisesRegex(ValueError,'bound'):launch.server_plan(*self.args,cap,deadline)

    def test_bad_deadline_does_not_freeze_authorization(self):
        with patch.object(launch.serve_mvp,'key_metadata',return_value={'limit':150,'limit_remaining':115,'usage':33}):
            now = datetime.now(timezone.utc)
            for source_days, requested_days in [(25, 22), (17, 20)]:
                with self.subTest(source_days=source_days, requested_days=requested_days):
                    self.args[3][0].compiled['expires_at'] = (now + timedelta(days=source_days)).isoformat()
                    with self.assertRaisesRegex(ValueError, 'registered sources'):
                        launch.server_plan(*self.args, '1', (now + timedelta(days=requested_days)).isoformat())
        self.assertFalse((self.state/'authorization.json').exists())
