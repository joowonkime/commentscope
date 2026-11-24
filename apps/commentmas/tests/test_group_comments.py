import copy
import json
import tempfile
import unittest
from pathlib import Path

from group_comments import (ModelRunner, assignment_schema, discovery_schema, group_source, model_comments,
                            save_results, validate_assignments, validate_discovery, validate_result, validate_summary)


def comment(cid, text, parent='', likes=1):
    return {'comment_id':cid,'text':text,'parent_id':parent,'author':'원작성자','like_count':likes,'is_reply':bool(parent)}


def definition(gid, seed):
    return {'group_id':gid,'name':'근로시간 단축' if gid=='g1' else '비용 우려',
            'stance':'관점 '+gid,'reasoning':'원문에 근거한 관점','inclusion_criteria':['이 관점을 표현함'],
            'exclusion_criteria':['반대 결론은 다른 관점'],'seed_comment_ids':[seed]}


def assignment(cid, gid='g1', fit='core', secondary=None, confidence=.95):
    return {'comment_id':cid,'primary_group_id':gid,'secondary_group_ids':secondary or [],'fit':fit,
            'confidence':confidence,'viewpoint_summary':'원문 관점','reason':'입장과 논거가 일치함'}


class FakeClient:
    provider='openai'
    model='test/model'
    reasoning_effort='medium'
    requests=0

    def __init__(self, uniform=False, mixed=False):
        self.calls=[]
        self.uniform=uniform
        self.mixed=mixed

    def structured(self, system, payload, schema, name):
        self.requests+=1
        self.calls.append((name,copy.deepcopy(payload)))
        if name=='discover':
            groups=[definition('g1',payload['comments'][0]['comment_id'])]
            if not self.uniform and len(payload['comments'])>1:
                groups.append(definition('g2',payload['comments'][1]['comment_id']))
            data={'grouping_rationale':'실제로 구분되는 관점만 생성','groups':groups}
        elif name=='assign':
            data={'assignments':[]}
            for c in payload['comments']:
                gid='g2' if '반대' in c['text'] and not self.uniform else 'g1'
                fit='peripheral' if '소수' in c['text'] else 'core'
                secondary=['g2'] if self.mixed and '복합' in c['text'] else []
                data['assignments'].append(assignment(c['comment_id'],gid,fit,secondary))
        elif name=='summarize':
            evidence=payload['eligible_evidence_ids'][0]
            peripheral=[c['comment_id'] for c in payload['comments'] if c['grouping']['fit']=='peripheral']
            data={'stance':payload['group']['stance'],'stance_evidence_comment_ids':[evidence],
                  'key_arguments':[{'argument':'근거 있는 논거','supporting_comment_ids':[evidence]}],
                  'within_group_variations':[{'description':'소수 관점','comment_ids':peripheral}] if peripheral else [],
                  'limitations':['댓글 기반 관점이며 사실 검증은 아님']}
        else:
            raise AssertionError(name)
        return {'data':data,'model':self.model,'usage':{'input_tokens':10,'output_tokens':10}}


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.output=Path(self.tmp.name)
        self.source={'meta':{'counts':{'review':55,'exclude':12}},'comments':[
            comment('long-source-ID.with.dot_A','찬성',likes=0),comment('other-ID.B','반대',likes=4),
            comment('third','소수 대안',likes=2),comment('reply','동감','long-source-ID.with.dot_A',likes=0)]}

    def tearDown(self):
        self.tmp.cleanup()

    def run_group(self, source=None, client=None, **kwargs):
        return group_source(source or self.source,client or FakeClient(),self.output,topic='근무시간 단축',**kwargs)

    def test_end_to_end_partition_raw_comments_evidence_and_distribution(self):
        original=copy.deepcopy(self.source)
        result=self.run_group(batch_size=2,workers=3)
        self.assertEqual(self.source,original)
        self.assertEqual(len(result['groups']),2)
        self.assertEqual([a['comment'] for a in result['assignments']],self.source['comments'])
        self.assertEqual(sum(g['statistics']['comment_count'] for g in result['groups']),3)
        self.assertAlmostEqual(sum(g['statistics']['comment_share'] for g in result['groups'])+result['other_opinions']['statistics']['comment_share'],1)
        self.assertAlmostEqual(sum(g['statistics']['like_share'] for g in result['groups'])+result['other_opinions']['statistics']['like_share'],1)
        self.assertEqual(result['meta']['other_opinions_count'],1)
        self.assertEqual(result['meta']['stage1_review_not_grouped'],55)
        for g in result['groups']:
            for cid in g['summary']['stance_evidence_comment_ids']:
                self.assertIn(cid,{x['comment_id'] for x in g['comments']})
        save_results(self.output,result)
        self.assertEqual(json.loads((self.output/'groups.json').read_text())['groups'],result['groups'])

    def test_resume_uses_all_stage_caches_without_new_requests(self):
        client=FakeClient()
        self.run_group(client=client,batch_size=2)
        calls=client.requests
        result=self.run_group(client=client,batch_size=2)
        self.assertEqual(client.requests,calls)
        self.assertTrue(all(r['cached'] for r in result['meta']['model_calls']))

    def test_likes_authors_not_sent_and_parent_context_preserved(self):
        client=FakeClient()
        self.run_group(client=client)
        discovery=client.calls[0][1]
        self.assertEqual(discovery['comments'][-1]['parent_context'],'찬성')
        self.assertEqual(discovery['comments'][0]['comment_id'],'c0001')
        for _,payload in client.calls:
            for c in payload.get('comments',[]):
                self.assertNotIn('author',c)
                self.assertNotIn('like_count',c)

    def test_primary_and_secondary_do_not_double_count_comments(self):
        source=copy.deepcopy(self.source)
        source['comments'][0]['text']='찬성 복합'
        result=self.run_group(source,FakeClient(mixed=True))
        self.assertEqual(result['assignments'][0]['grouping']['secondary_group_ids'],['g2'])
        self.assertEqual(sum(g['statistics']['comment_count'] for g in result['groups']),3)

    def test_single_homogeneous_group_not_forced_into_four(self):
        source={'comments':[comment('one','찬성')]}
        result=self.run_group(source,FakeClient(uniform=True))
        self.assertEqual(len(result['groups']),1)

    def test_no_confident_members_remain_other_without_inventing_a_group(self):
        source={'comments':[comment('one','소수 대안')]}
        result=self.run_group(source,FakeClient(uniform=True))
        self.assertEqual(result['groups'],[])
        self.assertEqual(result['other_opinions']['statistics']['comment_count'],1)
        self.assertIsNone(result['assignments'][0]['grouping']['primary_group_id'])

    def test_zero_likes_has_defined_zero_share(self):
        source=copy.deepcopy(self.source)
        for c in source['comments']: c['like_count']=0
        result=self.run_group(source)
        self.assertTrue(all(g['statistics']['like_share']==0 for g in result['groups']))

    def test_input_empty_duplicate_ids_and_max_six_fail_before_api(self):
        client=FakeClient()
        cases=[({'comments':[]},{}),({'comments':[comment('x','a'),comment('x','b')]},{}),(self.source,{'max_groups':6})]
        for source,kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                group_source(source,client,self.output,topic='test',**kwargs)
        self.assertEqual(client.requests,0)

    def test_assignment_missing_duplicate_unknown_and_secondary_errors_rejected(self):
        good=assignment('c1')
        cases=[[],[good,good],[assignment('other')],[assignment('c1','g9')],
               [assignment('c1',secondary=['g1'])],[assignment('c1',secondary=['g2','g2'])],
               [assignment('c1',confidence=True)],[assignment('c1',confidence=float('nan'))]]
        for values in cases:
            with self.subTest(values=values),self.assertRaises(ValueError):
                validate_assignments({'assignments':values},['c1'],['g1','g2'])

    def test_discovery_over_limit_and_fake_seed_rejected(self):
        for data in [ {'grouping_rationale':'why','groups':[definition(f'g{i}','c1') for i in range(1,7)]},
                      {'grouping_rationale':'why','groups':[definition('g1','nonexistent')]}]:
            with self.assertRaises(ValueError):validate_discovery(data,['c1'],5)

    def test_summary_rejects_other_group_and_provisional_evidence(self):
        data={'stance':'주장','stance_evidence_comment_ids':['c1'],
              'key_arguments':[{'argument':'논거','supporting_comment_ids':['c2']}],
              'within_group_variations':[],'limitations':[]}
        with self.assertRaises(ValueError):validate_summary(data,['c1','c2'],['c1'])
        data['key_arguments'][0]['supporting_comment_ids']=['c1']
        data['within_group_variations']=[{'description':'차이','comment_ids':['foreign']}]
        with self.assertRaises(ValueError):validate_summary(data,['c1','c2'],['c1'])

    def test_large_schema_uses_local_membership_check_instead_of_large_enum(self):
        schema=discovery_schema([f'c{i}' for i in range(1150)],5)
        field=schema['properties']['groups']['items']['properties']['seed_comment_ids']['items']
        self.assertEqual(field,{'type':'string'})

    def test_rejected_response_not_cached_and_one_retry_is_bounded(self):
        class BadClient(FakeClient):
            def structured(self,*args):
                self.requests+=1
                return {'data':{'bad':True},'model':self.model,'usage':{}}
        client=BadClient()
        runner=ModelRunner(client,self.output)
        with self.assertRaises(ValueError):
            runner.call('assign','rules',{},assignment_schema(['c1'],['g1']),lambda d:validate_assignments(d,['c1'],['g1']))
        self.assertEqual(client.requests,2)
        self.assertFalse((self.output/'.cache').exists())
        self.assertEqual(len(list((self.output/'.rejected').glob('*.json'))),2)

    def test_missing_parent_is_not_invented(self):
        mapping,items=model_comments([comment('r','동의','unknown')],[])
        self.assertIsNone(items[0]['parent_context'])

    def test_modified_or_duplicated_output_cannot_pass_validation(self):
        result=self.run_group()
        result['groups'][0]['comments'][0]['text']='변조'
        with self.assertRaises(ValueError):validate_result(self.source,result)

    def test_incorrect_distribution_and_review_flags_rejected(self):
        result=self.run_group()
        result['groups'][0]['statistics']['like_count']+=1
        with self.assertRaises(ValueError):validate_result(self.source,result)
        result=self.run_group()
        result['assignments'][0]['grouping']['needs_review']=True
        with self.assertRaises(ValueError):validate_result(self.source,result)

    def test_other_opinions_never_become_group_members_or_summary_evidence(self):
        result=self.run_group()
        other=result['other_opinions']
        self.assertFalse(other['is_perspective_group'])
        self.assertEqual([x['comment_id'] for x in other['comments']],['third'])
        self.assertTrue(all('third' not in {x['comment_id'] for x in g['comments']} for g in result['groups']))
        result['groups'][0]['summary']['stance_evidence_comment_ids']=['third']
        with self.assertRaises(ValueError):validate_result(self.source,result)


if __name__=='__main__':
    unittest.main()
