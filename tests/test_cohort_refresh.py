"""Receipt selection cannot depend on output labels or silently renew context."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
import json,tempfile,unittest

from tools import cohort_refresh as refresh
from commentscope.factory import acceptance


class CohortRefreshTests(unittest.TestCase):
    def setUp(self):
        self.base=SimpleNamespace(video=SimpleNamespace(video_id='toy-video'),comments=[
            SimpleNamespace(comment_id='old',text_original='Café policy',parent_id=None)])
        now=datetime.now(timezone.utc);self.now=now;self.selection={'frozen_at':(now-timedelta(seconds=2)).isoformat()}

    def item(self,cid,text,**changes):
        snippet={'textOriginal':text,'publishedAt':'2026-01-01T00:00:00Z','likeCount':0,**changes}
        return {'snippet':{'videoId':'toy-video','topLevelComment':{'id':cid,'snippet':snippet}}}

    def receipt(self,items,**query):
        return {'retrieved_at':self.now.isoformat(),'query':{'videoId':'toy-video','order':'time',
                'textFormat':'plainText',**query},'response':{'items':items}}

    def test_first_distinct_nonempty_sources_include_a_non_substantive_emoji(self):
        r=self.receipt([self.item('old','Changed same ID'),self.item('dup','Cafe\u0301   policy'),
            self.item('empty','  '),self.item('first','👍'),self.item('second','Oppose P.'),self.item('third','Support P.')])
        selected=refresh.latest_fill(self.base,[r],self.selection)
        self.assertEqual([c['comment_id'] for c in selected],['first','second'])
        self.assertEqual([c['sampling_origins'][0]['rank'] for c in selected],[4,5])
        self.assertTrue(all(c['replies_status']=='unknown' for c in selected))

    def test_order_video_and_page_chain_are_required(self):
        for changes in ({'order':'relevance'},{'videoId':'foreign'},{'pageToken':'unrequested'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                refresh.latest_fill(self.base,[self.receipt([self.item('a','A.'),self.item('b','B.')],**changes)],self.selection)
        first=self.receipt([self.item('a','A.')]);first['response']['nextPageToken']='next'
        second=self.receipt([self.item('b','B.')],pageToken='wrong')
        with self.assertRaises(ValueError):refresh.latest_fill(self.base,[first,second],self.selection)
        second['query']['pageToken']='next'
        self.assertEqual(len(refresh.latest_fill(self.base,[first,second],self.selection)),2)

    def test_capture_before_plan_or_in_future_is_rejected(self):
        for timestamp in (self.now-timedelta(hours=1),self.now+timedelta(hours=1)):
            row=self.receipt([self.item('a','A.'),self.item('b','B.')]);row['retrieved_at']=timestamp.isoformat()
            with self.subTest(timestamp=timestamp),self.assertRaises(ValueError):refresh.latest_fill(self.base,[row],self.selection)

    def test_foreign_video_and_reply_cannot_be_imported_as_roots(self):
        item=self.item('a','A.');item['snippet']['videoId']='foreign'
        for first in (item,self.item('a','A.',parentId='parent')):
            with self.subTest(first=first),self.assertRaises(ValueError):
                refresh.latest_fill(self.base,[self.receipt([first,self.item('b','B.')])],self.selection)

    def test_incomplete_inventory_cannot_synthesize_missing_rows(self):
        with self.assertRaises(ValueError):refresh.latest_fill(self.base,[self.receipt([self.item('a','A.')])],self.selection)

    def test_changed_acceptance_or_missing_approval_fails_before_reading_inputs(self):
        base={'version':refresh.VERSION,'quality_profile_sha256':acceptance.R5_DIGEST,
              'canonical_sources':999,'meaningful_sources':755,'minimum_correct_utilization':453,'new_model_calls':0,
              'approval':{'user_request':'Proceed','old_results_preserved':True}}
        for changes in ({'minimum_correct_utilization':452},{'meaningful_sources':754},
                        {'new_model_calls':1},{'approval':{}},{'quality_profile_sha256':'0'*64}):
            with self.subTest(changes=changes),tempfile.TemporaryDirectory(dir='runs',prefix='test-cohort-') as tmp:
                p=Path(tmp)/'binding.json';p.write_text(json.dumps({**base,**changes}))
                with self.assertRaises(ValueError):refresh.bind(p)


if __name__=='__main__':unittest.main()
