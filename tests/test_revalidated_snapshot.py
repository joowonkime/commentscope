"""Fixed evaluation inputs may be revalidated, never silently changed."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json
import tempfile
import unittest

from commentscope.contracts import parse_snapshot
from commentscope.ingestion import revalidated_snapshot as refresh
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from experiments.minimal_factory_pipeline import synthetic12


class RevalidatedSnapshotTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(dir='runs',prefix='test-refresh-');self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        now=datetime.now(timezone.utc);old=json.loads(json.dumps(synthetic12().to_dict()))
        old['captured_at']=(now-timedelta(days=31)).isoformat();old['usage']['expires_at']=(now-timedelta(days=1)).isoformat()
        old['comments'][1].update(parent_id='A',parent_status='present')
        self.original=parse_snapshot(old);self.original_file=self.root/'old.json';write(self.original_file,old)
        self.fresh=deepcopy(old);self.fresh['captured_at']=now.isoformat();self.fresh['usage']['expires_at']=(now+timedelta(days=30)).isoformat()
        self.fresh['comments']=[c for c in self.fresh['comments'] if c['comment_id']!='L']
        for c in self.fresh['comments']:c['replies_status']='unknown'
        items=[{'id':c['comment_id'],'snippet':{'textDisplay':c['text_original'],'parentId':c['parent_id'],
                'likeCount':c['likes'],'publishedAt':c['published_at']}} for c in self.fresh['comments']]
        self.receipt={'captured_at':now.isoformat(),'requested_ids':[c['comment_id'] for c in old['comments']],
                      'response':{'items':items}}
        self.receipt_file=self.root/'receipt.json';self.snapshot_file=self.root/'fresh.json';self.binding_file=self.root/'binding.json'
        self.video_file=self.root/'video.json';write(self.video_file,{'items':[{'id':old['video']['video_id'],'snippet':{'title':old['video']['title']}}]})
        self.publish()

    def publish(self):
        for path,value in ((self.receipt_file,self.receipt),(self.snapshot_file,self.fresh)):
            path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        self.binding={'version':refresh.VERSION,'registered_snapshot_sha256':sha(self.original_file),
            'snapshot_file':str(self.snapshot_file),'snapshot_sha256':sha(self.snapshot_file),
            'receipt_sha256':{str(p):sha(p) for p in (self.receipt_file,self.video_file)}}
        self.binding_file.write_text(json.dumps(self.binding),encoding='utf-8')

    def bind(self):return refresh.bind(self.binding_file,self.original,sha(self.original_file),['B'])

    def test_current_receipts_can_revalidate_identical_scope_despite_missing_outside_source(self):
        fresh,path,inputs,binding=self.bind()
        self.assertEqual(len(fresh.comments),11);self.assertEqual(len(self.original.comments),12)
        self.assertEqual(path,self.snapshot_file);self.assertEqual(inputs[str(self.receipt_file)],sha(self.receipt_file))
        self.assertEqual(binding['snapshot_sha256'],sha(self.snapshot_file))

    def test_legitimate_new_text_or_parent_context_changes_cannot_inherit_old_labels(self):
        for sid in ('B','A'):
            with self.subTest(changed_source=sid):
                old_fresh=deepcopy(self.fresh);old_receipt=deepcopy(self.receipt)
                next(c for c in self.fresh['comments'] if c['comment_id']==sid)['text_original']='A changed stance.'
                next(c for c in self.receipt['response']['items'] if c['id']==sid)['snippet']['textDisplay']='A changed stance.'
                self.publish()
                with self.assertRaises(ValueError):self.bind()
                self.fresh=old_fresh;self.receipt=old_receipt

    def test_missing_selected_source_is_refused_without_replacing_it(self):
        self.fresh['comments']=[c for c in self.fresh['comments'] if c['comment_id']!='B']
        self.receipt['response']['items']=[r for r in self.receipt['response']['items'] if r['id']!='B'];self.publish()
        with self.assertRaises(ValueError):self.bind()

    def test_receipt_tampering_and_unqueried_current_sources_are_rejected(self):
        self.receipt_file.write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):self.bind()
        self.publish();self.receipt['requested_ids'].remove('C');self.publish()
        with self.assertRaises(ValueError):self.bind()

    def test_new_expiry_is_bounded_and_old_snapshot_is_unchanged(self):
        old_bytes=self.original_file.read_bytes()
        self.fresh['usage']['expires_at']=(datetime.fromisoformat(self.fresh['captured_at'])+timedelta(days=31)).isoformat();self.publish()
        with self.assertRaises(ValueError):self.bind()
        self.assertEqual(self.original_file.read_bytes(),old_bytes)


if __name__=='__main__':unittest.main()
