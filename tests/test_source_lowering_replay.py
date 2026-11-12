from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from tools import replay_source_evidence_lowering as replay


class LoweringReplayTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'artifacts').mkdir()
        write(self.root/'plan.json',{'example':'fixed'})
        for name in ('arguments','cores','argument-audits','validation-report'):
            write(self.root/'artifacts'/(name+'.json'),[])
        self.done=dict(plan_sha256=sha(self.root/'plan.json'),report=[],artifacts={
            'artifacts/'+p.name:sha(p) for p in (self.root/'artifacts').glob('*.json')})
        write(self.root/'completed.json',self.done)

    def test_completed_receipt_is_read_only_and_binds_all_artifacts(self):
        self.assertEqual(replay.completed(self.root),self.done)
        (self.root/'artifacts/arguments.json').write_text('["changed"]',encoding='utf-8')
        with self.assertRaises(ValueError):replay.completed(self.root)

    def test_missing_inventory_and_path_escape_are_rejected(self):
        for mutate in (lambda x:x['artifacts'].pop('artifacts/arguments.json'),
                       lambda x:x['artifacts'].update({'plan.json':sha(self.root/'plan.json')})):
            d=deepcopy(self.done);mutate(d)
            (self.root/'completed.json').unlink();write(self.root/'completed.json',d)
            with self.assertRaises(ValueError):replay.completed(self.root)

    def test_changed_plan_and_reused_output_are_rejected_before_replay(self):
        with self.assertRaises(ValueError):replay.replay(self.root,self.root)
        (self.root/'plan.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):replay.completed(self.root)

    def test_source_duplicates_are_rejected_instead_of_selected(self):
        row={'source':{'id':'s'}}
        with self.assertRaises(ValueError):replay.rebuild([row,row],[],[{}])
