from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from commentscope.storage import write_json_exclusive as write
from tools import launch_mvp as launch


class LaunchTests(unittest.TestCase):
    def setUp(self):
        root=TemporaryDirectory(dir='runs')
        self.addCleanup(root.cleanup)
        self.root=Path(root.name).resolve()
        self.state=self.root/'state'
        self.state.mkdir()
        self.expiry=(datetime.now(timezone.utc)+timedelta(days=20)).isoformat()
        self.args=(self.state,self.root/'catalog.json',[self.root/'video'],
                   [SimpleNamespace(id='A1',compiled={'expires_at':self.expiry})],self.root/'deployment.json')
        write(self.args[1],{'analyses':['video'],'deployment':'deployment.json'})
        write(self.args[4],{})
        self.key=patch.dict('os.environ',{'OPENROUTER_API_KEY':'synthetic-bound-test'})
        self.key.start()
        self.addCleanup(self.key.stop)

    def test_restart_and_partial_setup_keep_one_binding_and_settled_opening_charge(self):
        until=(datetime.now(timezone.utc)+timedelta(days=11)).isoformat()
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
            with self.assertRaises(ValueError):
                launch.server_plan(*self.args,'1',(datetime.now(timezone.utc)+timedelta(days=16)).isoformat())
        self.assertFalse((self.state/'authorization.json').exists())
