from copy import deepcopy
import unittest

from commentscope.factory import source_span_selection as s
from tests.test_common_position import seed


def response(task, sid='b', nominees=None):
    row=next(r for r in s.inventory(task) if r['source_id']==sid and r['selectable'])
    return {'errors':[], 'output':{'status':'selected','span_id':row['id'],
                                  'nominated_source_ids':nominees or ['a','b','c']}}


class SourceSpanSelectionTests(unittest.TestCase):
    def test_exact_original_identity_and_complete_context(self):
        task=seed(); before=deepcopy(task); req=s.invocation(task)
        for sid,parts in req['data']['SOURCES'].items():
            self.assertEqual(''.join(p['text'] for p in parts),task['sources'][sid])
        for row in s.inventory(task):
            original=task['sources'][row['source_id']]
            self.assertEqual(row['text'],original[row['start']:row['end']])
            self.assertEqual(row['source_sha256'],s.digest(original))
        p=s.bind(task,response(task))
        self.assertEqual(p['claims']['C']['text'],task['sources']['b'])
        self.assertEqual(p['claims']['C']['scope'],{'entity':'','time':'','conditions':''})
        self.assertEqual(p['sources'],task['sources']);self.assertIn('d',p['sources'])
        self.assertFalse(p['semantic_approval']);self.assertTrue(p['typing_required'])
        self.assertEqual(task,before)
        for w in p['source_witnesses']:self.assertEqual(w['quote'],task['sources'][w['source_id']])

    def test_long_spans_and_sources_remain_full_context_never_truncated(self):
        task=seed();task['sources']['d']='x'*250+'. Short final sentence.'
        rows=[r for r in s.inventory(task) if r['source_id']=='d']
        self.assertFalse(rows[0]['selectable']);self.assertTrue(rows[1]['selectable'])
        self.assertEqual(''.join(r['text'] for r in rows),task['sources']['d'])
        task['sources']['d']='x'*4001+'. Short final sentence.'
        self.assertTrue(all(not r['selectable'] for r in s.inventory(task) if r['source_id']=='d'))
        self.assertEqual(''.join(r['text'] for r in s.invocation(task)['data']['SOURCES']['d']),task['sources']['d'])

    def test_capacity_overflow_explicit_not_subset(self):
        task=seed();task['sources'].update({str(i):'A. B.' for i in range(70)})
        with self.assertRaises(ValueError):s.inventory(task)
        task=seed();task['sources']['d']='x'*30000
        with self.assertRaises(ValueError):s.invocation(task)

    def test_invalid_ids_nominees_and_generated_fields_rejected(self):
        task=seed()
        for mutation in ({'span_id':'foreign'},{'nominated_source_ids':['a','b','b']},
                         {'nominated_source_ids':['a','b','unknown']},
                         {'nominated_source_ids':['a','c','d']},
                         {'nominated_source_ids':['a','b']},
                         {'core':'new claim'},{'quote':'new quote'},{'scope':{}},{'approved':True}):
            r=response(task);r['output'].update(mutation)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):s.bind(task,r)

    def test_nonselectable_id_and_error_rejected(self):
        task=seed();task['sources']['d']='x'*250
        r=response(task);r['output']['span_id']=next(x['id'] for x in s.inventory(task) if x['source_id']=='d')
        with self.assertRaises(ValueError):s.bind(task,r)
        r=response(task);r['errors']=['timeout']
        with self.assertRaises(ValueError):s.bind(task,r)

    def test_defer_is_not_approval(self):
        self.assertIsNone(s.bind(seed(),{'output':{'status':'defer','reason':'context_required'}}))
        with self.assertRaises(ValueError):s.bind(seed(),{'output':{'status':'defer','reason':'anything'}})

    def test_all_nominees_allowed_but_never_semantic_votes(self):
        task=seed();p=s.bind(task,response(task,nominees=list(task['sources'])))
        self.assertEqual(len(p['source_witnesses']),4)
        self.assertFalse(p['semantic_approval']);self.assertNotIn('model_support_count',p)

    def test_exact_dedup_preserves_both_origins_and_all_originals(self):
        a=seed();b=seed('S2');b['sources']['extra']=b['sources']['b']
        first=s.bind(a,response(a));second=s.bind(b,response(b,'extra',['a','c','extra']))
        queue=s.queue([first,second]);self.assertEqual(len(queue),1)
        self.assertEqual({r['source_id'] for r in queue[0]['selected_spans']},{'b','extra'})
        self.assertIn('extra',queue[0]['sources'])
        self.assertEqual(queue[0]['seed_candidate_ids'],['S1','S2'])

    def test_different_exact_text_not_merged(self):
        a=seed();b=seed('S2')
        first=s.bind(a,response(a));second=s.bind(b,response(b,'c'))
        self.assertEqual(len(s.queue([first,second])),2)


if __name__=='__main__':unittest.main()
