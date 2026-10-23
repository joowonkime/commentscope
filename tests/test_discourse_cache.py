from copy import deepcopy
from unittest import TestCase

from commentscope.factory import explicit_discourse as ed


class DiscourseCacheTests(TestCase):
    def setUp(self):
        self.source = {'id': 'cache-a', 'text': 'I support the proposal because it saves time.',
                       'parent': {'id': 'cache-parent', 'text': 'Which proposal?'}}

    def test_returned_mutation_cannot_poison_later_validation(self):
        expected = ed.parse(self.source)
        poisoned = ed.parse(self.source)
        poisoned['source']['parent']['text'] = 'Forged parent.'
        poisoned['nodes'][0]['span']['text'] = 'Forged assertion.'
        poisoned['edges'].clear()
        self.assertEqual(ed.parse(self.source), expected)
        with self.assertRaises(ValueError): ed.validate(poisoned)
        self.assertEqual(ed.validate(expected), expected)

    def test_source_parent_and_metadata_changes_do_not_reuse_old_graph(self):
        original = ed.parse(self.source)
        changed = deepcopy(self.source); changed['parent']['text'] = 'A different parent.'
        self.assertNotEqual(ed.parse(changed), original)
        changed['text'] = 'I reject the proposal.'
        self.assertFalse(ed.parse(changed)['edges'])
        changed['video_context'] = {'artifact_kind': 'snapshot-video-context-20261017-v1',
            'video_id': 'test-video', 'title': 'A different topic', 'primary_language': 'en'}
        self.assertEqual(ed.parse(changed), ed._parse_uncached(changed))
        self.assertNotEqual(ed.parse(changed)['source_sha256'], original['source_sha256'])

    def test_invalid_source_is_rejected_after_valid_cache_hit(self):
        ed.parse(self.source); ed.parse(self.source)
        changed = deepcopy(self.source); changed['parent']['id'] = changed['id']
        with self.assertRaises(ValueError): ed.parse(changed)

    def test_exact_output_and_key_order_match_original_parser(self):
        import json
        for text in ('"Reject it." I disagree because it is useful.',
                     'Only if costs fall, I support it.', '지원합니다. 시간이 줄기 때문입니다.',
                     'A'*70000+'.'):
            source = {'text': text, 'parent': None, 'id': 'order-check'}
            expected = json.dumps(ed._parse_uncached(source), ensure_ascii=False)
            self.assertEqual(json.dumps(ed.parse(source), ensure_ascii=False), expected)
            self.assertEqual(json.dumps(ed.parse(source), ensure_ascii=False), expected)
