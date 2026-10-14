from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from commentscope.factory.automatic_contract import digest
from experiments import matched_factory_probe as p


def response(value, finish='stop'):
    return {'choices':[{'message':{'content':json.dumps(value)},'finish_reason':finish}]}


def plan():
    return {'expires_at':'2099-01-01T00:00:00Z','sources':[
        {'source_id':str(i),'text':'UBI could help.','parent_id':None} for i in range(3)]}


def card(ids=('a','b','c')):
    citations=[{'member_id':f'M{i}', 'claim_id':f'U{i}', 'source_comment_id':sid,
                'quote':'UBI could help.'} for i,sid in enumerate(ids)]
    return {'id':'V1-C001-D01','source_ids':sorted(set(ids)), 'candidate_source_count':len(set(ids)),
            'common':{'text':'UBI could help.','evidence':citations},'details':[],'support_count':None}


class MatchedFactoryTests(unittest.TestCase):
    def calls(self, directory, value=None, provider=None):
        return p.Calls(plan(),Path(directory),provider or (lambda *a,**kw:response(value)))

    def test_schema_visible_and_raw_response_saved(self):
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{'ok':True});r=c.invoke('extract','S',{'COMMENT':'x'},{'type':'object'})
            self.assertIn('Required JSON output schema',r['request']['system'])
            self.assertEqual(r['response'],response({'ok':True}))
            self.assertEqual(c.counts['extract'],1)
            self.assertEqual(r['request_sha256'],digest(r['request']))

    def test_call_budget_deferred_not_negative(self):
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{});c.counts['extract']=64
            r=c.invoke('extract','S',{}, {})
            self.assertEqual(r['deferred'],'call_budget');self.assertFalse(r['fresh_call'])
            self.assertIsNone(r['result']['output']);self.assertEqual(c.counts['extract'],64)

    def test_time_budget_and_bytes_do_not_truncate(self):
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{});c.seconds=1800
            self.assertEqual(c.invoke('extract','S',{}, {})['deferred'],'time_budget')
            c.seconds=0;original='한'*30000
            r=c.invoke('extract','S',{'COMMENT':original},{})
            self.assertEqual(r['deferred'],'request_size_budget')
            self.assertEqual(r['request']['data']['COMMENT'],original)

    def test_expired_refuses_provider(self):
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{});c.plan['expires_at']='2000-01-01T00:00:00Z'
            with self.assertRaises(ValueError):c.invoke('extract','S',{}, {})
            self.assertEqual(c.counts,{})

    def test_same_request_is_fresh_not_cached(self):
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{})
            c.invoke('extract','S',{},{});c.invoke('extract','S',{}, {})
            self.assertEqual(c.counts['extract'],2);self.assertEqual(len(c.records),2)

    def test_transport_and_incomplete_are_errors(self):
        with tempfile.TemporaryDirectory() as root:
            def fail(*a,**kw):raise OSError('test')
            c=self.calls(root,provider=fail)
            self.assertEqual(c.invoke('extract','S',{}, {})['result']['errors'],['transport_error'])
            c.provider=lambda *a,**kw:response({},'length')
            self.assertEqual(c.invoke('extract','S',{}, {})['result']['errors'],['incomplete_generation'])

    def test_claims_same_source_never_inflate_candidate_sources(self):
        units=[{'id':'a','source_id':'one'},{'id':'b','source_id':'one'}]
        groups=p.candidates(units,[[1,0],[1,0]],.45)
        self.assertEqual(groups[0]['source_ids'],['one'])
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{})
            v=p.draft_candidates(plan(),'V1',groups,units,c)
            self.assertEqual(v['records'][0]['status'],'singleton_source');self.assertEqual(c.counts,{})

    def test_vector_mismatch_and_duplicate_units_fail(self):
        with self.assertRaises(ValueError):p.candidates([{'id':'a'}],[],.45)
        with self.assertRaises(ValueError):p.candidates([{'id':'a'},{'id':'a'}],[[1],[1]],.45)

    def test_empty_extraction_not_hallucinated(self):
        pl=plan();pl['sources']=pl['sources'][:1]
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{'status':'context_dependent','claims':[]})
            result=p.extract_sources(pl,c)
            self.assertEqual(result['units'],[]);self.assertEqual(result['source_count'],1)
            self.assertNotIn('parent',str(c.records[0]['request']['data']))

    def test_bad_segment_reference_blocks_whole_extraction(self):
        pl=plan();pl['sources']=pl['sources'][:1]
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{'status':'claims','claims':[{'statement':'UBI helps.','mode':'description','segment_ids':['missing']}]})
            result=p.extract_sources(pl,c)
            self.assertEqual(result['units'],[]);self.assertEqual(result['rows'][0]['status'],'error')

    def test_invalid_assignment_not_card(self):
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{'groups':[],'assignments':{}})
            v=p.draft_candidates(plan(),'V0',[{'id':'C','members':['0','1']}],[],c)
            self.assertEqual(v['cards'],[]);self.assertTrue(v['records'][0]['errors'])

    def test_auditor_reuses_exact_card_no_regeneration(self):
        v1={'cards':[card()]};before=deepcopy(v1)
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{'P01':{'verdict':'supported','reason':'Faithful.'}})
            v2=p.audit_cards(plan(),v1,c)
            self.assertEqual(v1,before);self.assertEqual(v2['cards'],v1['cards'])
            self.assertIsNot(v2['cards'][0],v1['cards'][0])
            self.assertEqual(v2['base_cards_sha256'],digest(v1['cards']))
            self.assertEqual(c.counts['audit'],3);self.assertFalse(v2['quality_gate_passed'])
            self.assertEqual(v2['agents'],[]);self.assertIsNone(v2['cards'][0]['support_count'])

    def test_same_source_statement_audited_once_not_twice(self):
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{'P01':{'verdict':'supported','reason':'Faithful.'}})
            result=p.audit_cards(plan(),{'cards':[card(('a','a','b'))]},c)
            self.assertEqual(c.counts['audit'],2);self.assertEqual(result['cards'][0]['candidate_source_count'],2)

    def test_one_failed_detail_blocks_card_without_rewriting(self):
        draft=card();draft['details']=[{'kind':'reason','text':'UBI eliminates poverty.','evidence':[draft['common']['evidence'][0]]}]
        def judge(system,data,schema,**kw):
            verdict='partial' if 'eliminates' in data['pairs']['P01']['text'] else 'supported'
            return response({'P01':{'verdict':verdict,'reason':'Test.'}})
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,provider=judge);v=p.audit_cards(plan(),{'cards':[draft]},c)
            self.assertEqual(v['cards'],[]);self.assertFalse(v['records'][0]['retained'])
            self.assertEqual(draft['details'][0]['text'],'UBI eliminates poverty.')

    def test_unknown_and_error_not_support(self):
        for value in [{'P01':{'verdict':'unclear','reason':'Ambiguous.'}}, {'P01':{'verdict':'supported','reason':''}}, {}]:
            with self.subTest(value=value),tempfile.TemporaryDirectory() as root:
                c=self.calls(root,value);v=p.audit_cards(plan(),{'cards':[card()]},c)
                self.assertEqual(v['cards'],[])

    def test_audit_budget_failure_not_supported(self):
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{});c.counts['audit']=192
            v=p.audit_cards(plan(),{'cards':[card()]},c)
            self.assertEqual(v['cards'],[])
            self.assertIn('call_budget',v['records'][0]['pairs'][0]['errors'])

    def test_summary_keeps_source_denominator_and_no_gold(self):
        empty={'rows':[{'status':'error'}]*3,'units':[]}
        variants=[{'variant':name,'cards':[],'records':[]} for name in ['V0','V1','V2']]
        with tempfile.TemporaryDirectory() as root:
            c=self.calls(root,{})
            result=p.summarize(plan(),empty,*variants,c,0)
            self.assertEqual(result['source_denominator'],3)
            for v in result['variants'].values():self.assertIsNone(v['semantic_precision'])
            self.assertEqual(result['agents'],[])


if __name__=='__main__':unittest.main()
