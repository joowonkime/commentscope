import unittest
from copy import deepcopy

from tools.opinion_sample import sample_ids, summarize


class OpinionSampleTests(unittest.TestCase):
    def test_draw_depends_only_on_the_processed_comment_frame(self):
        frame = [f's{i}' for i in range(104)]
        sample = sample_ids(frame, 'video')
        self.assertEqual(len(set(sample)), 50)
        self.assertEqual(sample, sample_ids(frame[::-1], 'video'))
        self.assertNotEqual(sample, sample_ids(frame, 'another-video'))
        self.assertEqual(set(sample_ids(['a','b'], 'video')), {'a','b'})
        with self.assertRaises(ValueError):
            sample_ids(['a','a'], 'video')

    def setUp(self):
        self.sheet = {
            'analysis_id':'analysis', 'issue':'Which policy?', 'population':6,
            'perspectives':{'a':'Policy A', 'b':'Policy B'},
            'comments':[{'id':str(i), 'text':f'Private text {i}', 'parent_context':None,
                         'classification':None, 'supports':[]} for i in range(6)]}
        self.review = deepcopy(self.sheet)
        for row, (status, views) in zip(self.review['comments'], [
                ('position',['a','b']), ('position',['b']), ('position',[]),
                ('no_position',[]), ('unclear',[]), ('no_position',[])], strict=True):
            row.update(classification=status, supports=views)

    def test_unmatched_positions_remain_in_denominator_and_overlap_in_each_bar(self):
        result = summarize(self.sheet, self.review, 'ai')
        self.assertEqual(result['positions'], 3)
        self.assertEqual(result['supports'], {'a':1, 'b':2})
        self.assertEqual((result['sample_size'], result['unmatched'], result['no_position'], result['unclear']),
                         (6, 1, 2, 1))
        self.assertNotIn('Private text', str(result))
        self.assertEqual(result['reviewer'], 'ai')

    def test_partial_duplicate_stale_and_inconsistent_reviews_cannot_publish(self):
        for change in ('missing','duplicate','unreviewed','wrong_view','invalid_status','duplicate_vote',
                       'no_position_with_vote','changed_text','different_analysis'):
            with self.subTest(change=change):
                altered = deepcopy(self.review)
                rows = altered['comments']
                if change == 'missing': rows.pop()
                elif change == 'duplicate': rows[-1] = rows[0]
                elif change == 'unreviewed': rows[0]['classification'] = None
                elif change == 'wrong_view': rows[0]['supports'] = ['other']
                elif change == 'invalid_status': rows[0]['classification'] = 'opinion?'
                elif change == 'duplicate_vote': rows[0]['supports'] = ['a','a']
                elif change == 'no_position_with_vote': rows[0]['classification'] = 'no_position'
                elif change == 'changed_text': rows[0]['text'] = 'different quote'
                elif change == 'different_analysis': altered['analysis_id'] = 'new revision'
                with self.assertRaises(ValueError):
                    summarize(self.sheet, altered, 'ai')
