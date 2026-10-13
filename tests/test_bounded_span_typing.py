from copy import deepcopy
import unittest

from commentscope.factory import bounded_span_typing as t


class BoundedSpanTypingTests(unittest.TestCase):
    def fixture(self):
        return {'id':'P','claims':{'C':{'id':'C','text':'Safety reviews should be required.','kind':'fact',
                    'scope':{'entity':'operators','time':'','conditions':''},'requires':[]}},
                'sources':{'a':'Safety reviews should be required. I value prevention.\nSafety matters.',
                           'b':'Safety reviews should be required. I worked here.'}}

    def value(self,p):
        _,ranges=t.inventory(p['sources'])
        rid=next(k for k,v in ranges.items() if v['text']=='I value prevention.\n')
        return {'status':'classified','kind':'normative_preference',
                'details':[{'range_id':rid,'kind':'normative_preference','required_fact':False}]}

    def test_all_and_only_nonempty_contiguous_ranges_within_limit_are_enumerated(self):
        sources={'a':'A. B. C.','b':'x'*501+'. End.'};context,ranges=t.inventory(sources)
        self.assertEqual(len(ranges),7) # six combinations of A/B/C, only End in b
        self.assertEqual({v['text'] for v in ranges.values()},{'A. ','B. ','C.','A. B. ','B. C.','A. B. C.','End.'})
        for row in ranges.values():
            self.assertEqual(row['text'],sources[row['source_id']][row['start']:row['end']])
            self.assertLessEqual(len(row['text']),500)
        for row in context.values():self.assertEqual(''.join(s['text'] for s in row['sentences']),sources[row['source_id']])

    def test_schema_cannot_request_long_ranges_or_nonempirical_required_facts(self):
        p=self.fixture();req=t.invocation(p['claims']['C'],p['sources']);_,ranges=t.inventory(p['sources'])
        self.assertEqual(req['schema']['$defs']['range_id']['enum'],list(ranges))
        detail=req['schema']['anyOf'][1]['properties']['details']['items']['anyOf']
        self.assertEqual(detail[0]['properties']['kind']['const'],'empirical_description')
        self.assertEqual(detail[1]['properties']['required_fact']['const'],False)
        for branch in detail:
            self.assertEqual(branch['properties']['range_id'],{'$ref':'#/$defs/range_id'})
            self.assertNotIn('quote',branch['properties'])
        self.assertNotIn('required_fact_ids',req['schema']['anyOf'][1]['properties'])
        self.assertEqual(req['max_tokens'],650)

    def test_exact_copy_and_required_dependency_without_core_rewrite(self):
        p=self.fixture();v=self.value(p);before=deepcopy(v)
        got=t.apply(p,v,p['sources'])
        self.assertEqual(got['claims']['R1']['text'],'I value prevention.\n')
        self.assertEqual(got['claims']['C']['text'],p['claims']['C']['text'])
        self.assertEqual(got['claims']['C']['scope'],p['claims']['C']['scope'])
        self.assertEqual(v,before)
        v['details'][0].update(kind='empirical_description',required_fact=True)
        got=t.apply(p,v,p['sources'])
        self.assertEqual(got['claims']['C']['requires'],['R1'])
        self.assertEqual(got['claims']['R1']['kind'],'fact')

    def test_impossible_or_stale_selections_fail_without_repair(self):
        p=self.fixture();good=self.value(p)
        for change in ({'required_fact':True},{'required_fact':1},{'range_id':'missing'},{'quote':'new'}):
            bad=deepcopy(good);bad['details'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):t.apply(p,bad,p['sources'])
        p['sources']['a']+=' Changed context.'
        with self.assertRaises(ValueError):t.apply(p,good,p['sources'])

    def test_duplicate_reasons_and_empty_or_deferred_results(self):
        p=self.fixture();v=self.value(p);v['details']*=2
        with self.assertRaises(ValueError):t.apply(p,v,p['sources'])
        v['details']=[]
        self.assertEqual(set(t.apply(p,v,p['sources'])['claims']),{'C'})
        self.assertIsNone(t.apply(p,{'status':'defer','reason':'essential_grounds_overflow'},p['sources']))

    def test_no_trimming_for_long_sources_and_bounded_inventory(self):
        p=self.fixture();req=t.invocation(p['claims']['C'],{'a':'x'*501})
        self.assertNotIn('$defs',req['schema'])
        self.assertEqual(req['schema']['anyOf'][1]['properties']['details']['maxItems'],0)
        self.assertEqual(next(iter(req['data']['MEMBER_SOURCES'].values()))['sentences'][0]['text'],'x'*501)
        with self.assertRaisesRegex(ValueError,'sentence budget'):t.inventory({'a':'Short. '*129})
        with self.assertRaisesRegex(ValueError,'range budget'):t.inventory({'a':'A. '*50})
