from copy import deepcopy
import unittest

from commentscope.factory import span_typing as t, perspective_typing as legacy
from commentscope.factory.automatic_contract import digest


class SpanTypingTests(unittest.TestCase):
    def fixture(self):
        return {'id':'P','claims':{'C':{'id':'C','text':'Safety reviews should be required.','kind':'fact',
                'scope':{'entity':'operators','time':'','conditions':''},'requires':[]}},
                'sources':{'s1':'Safety reviews should be required. I value prevention.\nSafety matters.',
                           's2':'Safety reviews should be required. I worked here.'}}

    def response(self,p):
        part=t.inventory(p['sources'])['s1'][1]
        return {'status':'classified','kind':'normative_preference','details':[{
            'id':'D1','kind':'normative_preference','source_id':'s1','first':part['id'],'last':part['id']}],
            'required_fact_ids':[]}

    def test_whole_source_context_and_no_generated_quote_field(self):
        p=self.fixture();req=t.invocation(p['claims']['C'],p['sources'])
        for sid,parts in req['data']['MEMBER_SOURCES'].items():
            self.assertEqual(''.join(x['text'] for x in parts),p['sources'][sid])
        detail=req['schema']['anyOf'][1]['properties']['details']['items']['properties']
        self.assertNotIn('quote',detail)
        self.assertEqual(req['max_tokens'],650)
        self.assertIn('Do not delete required facts',req['system'])
        self.assertNotEqual(t.SYSTEM,legacy.SYSTEM)

    def test_host_copies_exact_range_and_preserves_core(self):
        p=self.fixture();value=self.response(p);original=deepcopy(value)
        result=t.apply(p,value,p['sources'])
        self.assertEqual(result['claims']['R1']['text'],'I value prevention.\n')
        self.assertEqual(result['claims']['C']['text'],p['claims']['C']['text'])
        self.assertEqual(result['claims']['C']['scope'],p['claims']['C']['scope'])
        span=result['selected_ranges'][0]
        self.assertEqual(p['sources']['s1'][span['start']:span['end']],result['claims']['R1']['text'])
        self.assertEqual(result['typing_request_sha256'],digest(t.invocation(p['claims']['C'],p['sources'])))
        self.assertEqual(value,original)

    def test_cross_source_ranges_unknown_ids_reversal_and_text_are_rejected(self):
        p=self.fixture();good=self.response(p)
        changes=[{'source_id':'s2'},{'source_id':'outsider'},{'first':'missing'},
                 {'first':t.inventory(p['sources'])['s1'][2]['id']},{'quote':'Invented'}]
        for change in changes:
            with self.subTest(change=change):
                bad=deepcopy(good);bad['details'][0].update(change)
                with self.assertRaises((ValueError,KeyError)):t.apply(p,bad,p['sources'])

    def test_source_text_change_invalidates_range_ids(self):
        p=self.fixture();v=self.response(p);sources=dict(p['sources']);sources['s1']+=' More context.'
        with self.assertRaises(ValueError):t.apply(p,v,sources)

    def test_required_fact_cannot_disappear_or_be_retyped_as_value(self):
        p=self.fixture();v=self.response(p);v['required_fact_ids']=['D1']
        with self.assertRaises(ValueError):t.apply(p,v,p['sources'])
        v['details'][0]['kind']='empirical_description'
        result=t.apply(p,v,p['sources'])
        self.assertEqual(result['claims']['C']['requires'],['R1'])
        self.assertEqual(result['claims']['R1']['kind'],'fact')
        v['details']=[]
        with self.assertRaises(ValueError):t.apply(p,v,p['sources'])

    def test_duplicate_range_and_long_range_not_silently_trimmed(self):
        p=self.fixture();v=self.response(p);v['details'].append({**v['details'][0],'id':'D2'})
        with self.assertRaises(ValueError):t.apply(p,v,p['sources'])
        p['sources']={'s1':'x'*501};part=t.inventory(p['sources'])['s1'][0]
        v={'status':'classified','kind':'normative_preference','details':[{
            'id':'D1','kind':'normative_preference','source_id':'s1','first':part['id'],'last':part['id']}],'required_fact_ids':[]}
        with self.assertRaisesRegex(ValueError,'length budget'):t.apply(p,v,p['sources'])

    def test_empty_details_and_explicit_deferral_remain_available(self):
        p=self.fixture()
        result=t.apply(p,{'status':'classified','kind':'normative_preference','details':[],'required_fact_ids':[]},p['sources'])
        self.assertEqual(set(result['claims']),{'C'})
        self.assertIsNone(t.apply(p,{'status':'defer','reason':'mixed_or_unclear'},p['sources']))

    def test_oversized_request_is_rejected_before_inference(self):
        p=self.fixture()
        with self.assertRaisesRegex(ValueError,'byte budget'):
            t.invocation(p['claims']['C'],{'s':'Long. '*2000})
