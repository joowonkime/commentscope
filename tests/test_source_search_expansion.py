"""Closed expansion scope and continuation of proven paid failures; no API calls."""
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tools import source_search_expansion as x
from commentscope.factory.pipeline_work import PipelineWork
from commentscope.factory.shared_admission import PriorRequestUnavailable
import test_source_fidelity_continuation as paid
import test_minimal_factory as fixture


class SourceSearchExpansionTests(TestCase):
    def primary(self,root):
        doc=dict(id='primary',text='Adopt P.\n\nAn observed scope.',url='https://tietotarjotin.fi/en/information-package/158070/basic-income-experiment',title='Synthetic title',publisher='synthetic',published_at='2020-09-16T06:55:00Z',retrieved_at='2020-09-16T06:55:00Z',expires_at='2020-10-16T06:55:00Z',source_kind='synthetic')
        body=root/'article.json';body.write_text(json.dumps([dict(articleId='158070',title_en=doc['title'],publishDate=doc['published_at'],content_en='<p>Adopt P.</p><p>An observed scope.</p>')]))
        receipt=root/'receipt.json';record=dict(version='same-document-primary-revalidation-20261113-v1',old_document_sha256=x.digest(doc),body_file=str(body),body_sha256=x.reuse.file_sha(body),url=doc['url'],final_url='https://tietotarjotin.fi/api/node-cache/articles/158070',retrieved_at=datetime.now(timezone.utc).isoformat())
        receipt.write_text(json.dumps(record));return doc,body,receipt,record

    def test_primary_refresh_keeps_all_text_scope_and_only_updates_retrieval_metadata(self):
        with TemporaryDirectory() as temp:
            doc,_,receipt,_=self.primary(Path(temp));current=x.refreshed_documents([doc],receipt)[0]
            self.assertEqual({k:v for k,v in current.items() if k not in ('retrieved_at','expires_at')},{k:v for k,v in doc.items() if k not in ('retrieved_at','expires_at')})
            self.assertEqual(datetime.fromisoformat(current['expires_at'])-datetime.fromisoformat(current['retrieved_at']),timedelta(days=30))

    def test_primary_refresh_rejects_missing_scope_even_if_receipt_hash_is_updated(self):
        with TemporaryDirectory() as temp:
            doc,body,receipt,record=self.primary(Path(temp));a=x.read_json(body);a[0]['content_en']='<p>Adopt P.</p>';body.write_text(json.dumps(a))
            record['body_sha256']=x.reuse.file_sha(body);receipt.write_text(json.dumps(record))
            with self.assertRaises(ValueError):x.refreshed_documents([doc],receipt)

    def test_primary_refresh_rejects_stale_or_foreign_retrieval_and_modified_body(self):
        with TemporaryDirectory() as temp:
            doc,body,receipt,record=self.primary(Path(temp))
            for change in (dict(retrieved_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()),dict(final_url='https://example.org/foreign')):
                receipt.write_text(json.dumps({**record,**change}))
                with self.assertRaises(ValueError):x.refreshed_documents([doc],receipt)
            receipt.write_text(json.dumps(record));body.write_text('[]')
            with self.assertRaises(ValueError):x.refreshed_documents([doc],receipt)

    def inventory(self):
        p=dict(candidate_ids=['c'],new_pairs=[dict(source_id='s',candidate_id='c')],new_pair_count=1,new_source_count=1)
        return p,dict(pairs=[dict(source_id='old',candidate_id='c')]),[dict(id='c')],{'s':{}}

    def test_new_inventory_is_exact_and_old_failed_attempts_cannot_be_retried(self):
        args=self.inventory();self.assertEqual(x.checked_pairs(*args),args[0]['new_pairs'])
        for mutate in (
            lambda p:p['new_pairs'].append(p['new_pairs'][0]),
            lambda p:p['new_pairs'][0].update(source_id='old'),
            lambda p:p['new_pairs'][0].update(candidate_id='foreign'),
            lambda p:p.update(candidate_ids=['c','c']),
            lambda p:p.update(new_source_count=2),
        ):
            p=deepcopy(args[0]);mutate(p)
            with self.assertRaises(ValueError):x.checked_pairs(p,*args[1:])
        old=dict(pairs=args[0]['new_pairs'])
        with self.assertRaises(ValueError):x.checked_pairs(args[0],old,*args[2:])

    def test_window_is_finite_and_preserves_time_for_the_actual_call(self):
        start=datetime(2026,11,13,tzinfo=timezone.utc)
        auth=dict(started_at=start.isoformat(),deadline=(start+timedelta(hours=4)).isoformat())
        x.window(auth,now=start);x.window(auth,now=start+timedelta(hours=3),call_seconds=180)
        for end in (start,start+timedelta(hours=4,microseconds=1)):
            with self.assertRaises(ValueError):x.window({**auth,'deadline':end.isoformat()},now=start)
        for now in (start-timedelta(seconds=1),start+timedelta(hours=4,seconds=-180)):
            with self.assertRaises(TimeoutError):x.window(auth,now=now,call_seconds=180)

    def test_streamed_memberships_preserve_complete_selected_batches(self):
        sources=[dict(id='s',text='Adopt P.',parent=None),dict(id='t',text='Adopt Q.',parent=None)]
        candidates=x.mc.candidates(fixture.extraction(sources,{'s':['Adopt P.'],'t':['Adopt Q.']}))
        batches=[fixture.membership([s],[c],[dict(source_id=s['id'],candidate_id=c['id'])]) for s,c in zip(sources,candidates)]
        with TemporaryDirectory() as temp:
            p=Path(temp)/'members.json';p.write_text(json.dumps(batches))
            self.assertEqual(x.selected_memberships(p,{candidates[0]['id']}),batches[:1])
            mixed=fixture.membership(sources,candidates,[dict(source_id=s['id'],candidate_id=c['id']) for s,c in zip(sources,candidates)])
            p.write_text(json.dumps([mixed]))
            with self.assertRaises(ValueError):x.selected_memberships(p,{candidates[0]['id']})

    def terminal(self,root,raw):
        helper=paid.SettledLengthTests();s,req,result,done,money=helper.make(root)
        result=deepcopy(result);receipt=result['transport']['provider_response'];receipt['choices'][0]['message']['content']=raw
        result['raw']=raw;result['transport']['provider_response_sha256']=x.digest(receipt)
        bound=x.read_json(done);bound['result']=result;bound['result_sha256']=x.digest(result);helper.save(done,bound)
        response=next((root/'calls').glob('*.result.json'));helper.save(response,result)
        return s,req,result,money

    def test_settled_length_including_null_raw_is_an_unchanged_hold_without_new_charge(self):
        for raw in (None,'{"units":['):
            with self.subTest(raw=raw),TemporaryDirectory() as temp:
                s,req,result,money=self.terminal(Path(temp),raw);before=money.summary();saved={}
                with self.assertRaises(PriorRequestUnavailable):x.settled_hold(s,'source-evidence-proposal',req,lambda k,v:saved.setdefault(k,v))
                self.assertEqual(money.summary(),before);self.assertEqual(next(iter(saved.values()))['result'],result)
                self.assertIsNone(result['output']);self.assertEqual(result['errors'],['incomplete_generation'])

    def test_proven_null_raw_hold_allows_next_work_item_without_synthetic_output(self):
        with TemporaryDirectory() as temp:
            s,req,_,money=self.terminal(Path(temp),None);before=money.summary();seen=[]
            class Runner:
                def call(self,stage,request):
                    seen.append(request)
                    if len(seen)==1:return x.settled_hold(s,'source-evidence-proposal',req,lambda k,v:None)
                    return dict(output={'kept':True},errors=[])
            work=PipelineWork(Runner(),lambda req:{'fits':True,'request_sha256':x.digest(req)},lambda k,v:None,registry={},membership_mode='raw',verification_contract=x.raw.FULL_SCOPE,schedule=x.minimal_pipeline.SCHEDULE)
            values=work.work('source-evidence-proposal',[1,2],lambda group:{**req,'data':{'n':group[0]}},lambda group,result:result['output'],1)
            self.assertEqual(values,[{'kept':True}]);self.assertEqual(len(seen),2);self.assertEqual(money.summary(),before)
            self.assertEqual(len(work.holds),1)

    def test_unproven_or_unsettled_null_raw_failure_cannot_continue(self):
        with TemporaryDirectory() as temp:
            s,req,_,money=self.terminal(Path(temp),None)
            call=next((s.directory/'calls').glob('*.result.json'));call.write_text('{}')
            with self.assertRaises(ValueError):x.settled_hold(s,'source-evidence-proposal',req,lambda k,v:None)
        with TemporaryDirectory() as temp:
            s,req,_,money=self.terminal(Path(temp),None)
            cid=money.reserve('a'*64,'b'*64,'0.1',run_limit_usd='150',key_remaining_usd='149');money.finish(cid,None)
            with self.assertRaises(x.e.BudgetExhausted):x.settled_hold(s,'source-evidence-proposal',req,lambda k,v:None)

    def test_registered_physical_request_is_counted_once_and_unknown_stages_stop(self):
        s=x.Session.__new__(x.Session);s.seen=set();s.counts=Counter();q={'x':1}
        s.admit('core','generation',q);s.admit('core','generation',q)
        self.assertEqual(s.counts['core'],1)
        with self.assertRaises(x.e.BudgetExhausted):s.admit('embedding','generation',q)
        with self.assertRaises(ValueError):s.embed('sources',[])

    def test_foreign_typed_source_or_candidate_never_reaches_provider(self):
        s=x.Session.__new__(x.Session);s.registry={'s':dict(id='s',text='Adopt P.',parent=None)}
        s.targets=[dict(id='c',text='Adopt P.')];s.pairs={('s','c')};s.seen=set();s.counts=Counter()
        payload=dict(state=dict(READING_INPUT=dict(ORIGINAL=x.mc.packet(s.registry['s']),CANDIDATE=dict(text='Adopt P.'))))
        with patch.object(x.shared.Session,'decide',return_value={'ok':True}) as dispatch:
            self.assertEqual(s.decide('synthetic',payload),{'ok':True});self.assertEqual(dispatch.call_count,1)
            bad=deepcopy(payload);bad['state']['READING_INPUT']['CANDIDATE']['text']='Invented'
            with self.assertRaises(ValueError):s.decide('synthetic',bad)
            bad=deepcopy(payload);bad['state']['READING_INPUT']['ORIGINAL']['source_sha256']='changed'
            with self.assertRaises(ValueError):s.decide('synthetic',bad)
            self.assertEqual(dispatch.call_count,1)
