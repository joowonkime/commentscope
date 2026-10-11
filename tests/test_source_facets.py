import json
import unittest
from urllib.error import URLError

from commentscope.factory.source_facets import classify, validate, assemble, SCHEMA
from experiments.source_facet_loop import evaluate, render
from experiments.review_source_facets import apply_review


class SourceFacetTests(unittest.TestCase):
    def value(self, kind='need', polarity='affirmed', topic=True):
        return {'topic_match':topic,'assertion_type':kind,'polarity':polarity,'assertion_quote':'original'}

    def record(self, i, kind='need', polarity='affirmed'):
        return {'id':str(i),'source_comment_id':'s'+str(i),'source':'original conditional statement',
                'result':{'output':self.value(kind,polarity),'errors':[]}}

    def test_request_contains_only_target_and_preserves_raw(self):
        def provider(system, data, schema):
            self.assertEqual(data,{'TARGET':'original'}); self.assertEqual(schema,SCHEMA)
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(self.value())}}]}
        r=classify('original',provider=provider)
        self.assertEqual(r['errors'],[]); self.assertEqual(json.loads(r['raw']),self.value())
        self.assertFalse(r['human_approved'])

    def test_fabricated_quote_and_extra_fields_fail(self):
        self.assertIn('quote_not_in_source',validate(self.value(),'different text'))
        self.assertEqual(validate({**self.value(),'reason':'invented'},'original'),['keys'])

    def test_null_quote_only_for_unclear(self):
        self.assertIn('missing_quote',validate({**self.value(),'assertion_quote':None},'original'))
        self.assertEqual(validate({**self.value('unclear'),'assertion_quote':None},'original'),[])

    def test_truncated_generation_fails(self):
        def provider(*args): return {'choices':[{'finish_reason':'length','message':{'content':json.dumps(self.value())}}]}
        self.assertIn('incomplete_generation',classify('original',provider=provider)['errors'])

    def test_transport_failure_and_oversize_fail(self):
        def provider(*args): raise URLError('offline')
        self.assertIn('transport_error',classify('original',provider=provider)['errors'])
        self.assertIn('invalid_response',classify('x'*501,provider=provider)['errors'])

    def test_group_preserves_full_source_not_just_trigger_quote(self):
        records=[self.record(i) for i in range(3)]
        a=assemble(records); self.assertEqual(len(a['groups']),1)
        for card in a['groups'][0]['source_cards']:
            self.assertEqual(card['text'],'original conditional statement')
            self.assertEqual(card['text'][card['start']:card['end']],card['text'])
        self.assertEqual(a['accepted_perspectives'],0)

    def test_negated_claims_cannot_merge_with_affirmed(self):
        a=assemble([self.record(1),self.record(2,polarity='negated')])
        self.assertEqual(len(a['groups']),2)
        self.assertEqual({g['polarity'] for g in a['groups']},{'affirmed','negated'})

    def test_rare_mixed_unclear_and_errors_retained(self):
        records=[self.record(1),self.record(2,'mixed'),self.record(3,'unclear'),self.record(4)]
        records[3]['result']['errors']=['incomplete_generation']
        a=assemble(records)
        self.assertEqual(a['groups'][0]['status'],'rare_preserved')
        self.assertEqual(len(a['unassigned']),3)
        all_ids=[i for g in a['groups'] for i in g['members']]+[u['member_id'] for u in a['unassigned']]
        self.assertEqual(sorted(all_ids),['1','2','3','4'])

    def test_off_topic_is_not_grouped(self):
        r=self.record(1); r['result']['output']['topic_match']=False
        a=assemble([r]); self.assertEqual(a['groups'],[])
        self.assertEqual(a['unassigned'][0]['reason'],'off_topic')

    def test_duplicates_and_oversize_rejected(self):
        for records in [[],[self.record(1),self.record(1)],[self.record(i) for i in range(25)]]:
            with self.assertRaises(ValueError): assemble(records)

    def test_evaluation_failures_are_not_success(self):
        r=self.record(1)
        expectation={'1':{'allowed_types':['need'],'allowed_polarities':['affirmed'],'topic_match':True}}
        self.assertEqual(evaluate([r],expectation)['joint_matches'],1)
        r['result']['errors']=['invalid']
        self.assertEqual(evaluate([r],expectation)['joint_matches'],0)

    def test_html_escapes_sources(self):
        r=self.record(1); r['source']='original <script>x</script>'
        page=render({'split':'development','records':[r],'assembly':assemble([r]),'evaluation':{}})
        self.assertNotIn('<script>',page); self.assertIn('&lt;script&gt;',page)

    def review(self, decision='confirm'):
        return {'reviewer':'conversation_assistant','human_approved':False,'entries':[
            {'id':'1','decision':decision,'reason_ko':'검수 이유','reading_ko':'검수 해석','cautions_ko':'조건 보존'}]}

    def test_review_keeps_raw_model_and_changes_only_explicit_fields(self):
        records=[self.record(1,'prediction')]; review=self.review('correct')
        review['entries'][0]['corrected']={'topic_match':True,'assertion_type':'need','polarity':'affirmed'}
        result=apply_review(records,review)
        self.assertEqual(records[0]['result']['output']['assertion_type'],'prediction')
        self.assertEqual(result[0]['model_result'],records[0]['result'])
        self.assertEqual(result[0]['result']['output']['assertion_type'],'need')
        self.assertEqual(result[0]['result']['output']['assertion_quote'],records[0]['source'])
        self.assertFalse(result[0]['result']['human_approved'])

    def test_review_requires_full_coverage_and_origin(self):
        for review in [self.review(),{**self.review(),'reviewer':'human'},{**self.review(),'human_approved':True}]:
            with self.assertRaises(ValueError): apply_review([self.record(1),self.record(2)],review)

    def test_review_cannot_confirm_invalid_or_hide_correction(self):
        record=self.record(1); record['result']['errors']=['invalid']
        with self.assertRaises(ValueError): apply_review([record],self.review())
        review=self.review(); review['entries'][0]['corrected']={}
        with self.assertRaises(ValueError): apply_review([self.record(1)],review)

    def test_review_abstention_is_retained_not_grouped(self):
        records=apply_review([self.record(1)],self.review('abstain'))
        a=assemble(records); self.assertEqual(a['groups'],[]); self.assertEqual(len(a['unassigned']),1)
