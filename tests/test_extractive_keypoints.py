import copy
import json
import unittest
from urllib.error import URLError

from commentscope.factory.extractive_keypoints import anchors_for, judge, score_pairs, assemble, render


class ExtractiveKeypointsTests(unittest.TestCase):
    def members(self, count=4):
        return {f'M{i}': {'source_comment_id': f's{i}', 'target': f'Original statement {i}.'} for i in range(count)}

    def matrix(self, members):
        return {s+'->'+a: {'source': s, 'anchor': a, 'relation': 'supports' if s == a else 'not_established',
                           'origin': 'identity_text_only' if s == a else 'local_model', 'errors': []}
                for s in members for a in members}

    def provider(self, system, payload, schema):
        self.assertEqual(set(payload), {'SOURCE', 'REPRESENTATIVE'})
        self.assertEqual(set(schema['properties']), {'relation'})
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"relation":"supports"}'}}]}

    def test_anchors_are_exact_full_source_spans(self):
        members = self.members(); members['M0']['target'] = '  Could help, if funded.\n'
        anchors = anchors_for(members)
        for mid, anchor in anchors.items():
            self.assertEqual(anchor['text'], members[mid]['target'][anchor['start']:anchor['end']])
            self.assertEqual(anchor['source_comment_id'], members[mid]['source_comment_id'])

    def test_bounds_duplicates_empty_and_long_comments(self):
        for members in [{}, self.members(13), {'M0': {'source_comment_id': 's', 'target': ' '}},
                        {'M0': {'source_comment_id': 's', 'target': 'a'*501}}]:
            with self.assertRaises(ValueError): anchors_for(members)
        members = self.members(); members['M1']['source_comment_id'] = members['M0']['source_comment_id']
        with self.assertRaises(ValueError): anchors_for(members)

    def test_n_squared_minus_n_model_calls_and_identity_provenance(self):
        members = self.members(3); calls = []; checkpoints = []
        def provider(*args): calls.append(args); return self.provider(*args)
        pairs = score_pairs(members, anchors_for(members), provider, lambda k, r: checkpoints.append(k))
        self.assertEqual(len(calls), 6); self.assertEqual(len(checkpoints), 9)
        self.assertEqual(pairs['M0->M0']['origin'], 'identity_text_only')
        self.assertIsNone(pairs['M0->M0']['raw'])

    def test_model_cannot_generate_representative_or_extra_text(self):
        def provider(*args):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"relation":"supports","text":"invented"}'}}]}
        result = judge('source', 'anchor', provider)
        self.assertEqual(result['errors'], ['invalid_relation']); self.assertIsNone(result['relation'])

    def test_unknown_relation_truncation_and_transport_fail_closed(self):
        for value, finish in [({'relation': 'approved'}, 'stop'), ({'relation': 'supports'}, 'length')]:
            def provider(*args):
                return {'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(value)}}]}
            self.assertIsNone(judge('source', 'anchor', provider)['relation'])
        def unavailable(*args): raise URLError('offline')
        self.assertIn('transport_error', judge('source', 'anchor', unavailable)['errors'])

    def test_group_requires_direct_support_and_no_transitive_inference(self):
        members = self.members(4); pairs = self.matrix(members)
        for edge in ['M1->M0', 'M2->M0', 'M3->M2']: pairs[edge]['relation'] = 'supports'
        result = assemble(members, anchors_for(members), pairs)
        self.assertEqual(result['groups'][0]['member_ids'], ['M0', 'M1', 'M2'])
        self.assertEqual([r['member_id'] for r in result['unassigned']], ['M3'])
        self.assertFalse(result['human_approved']); self.assertEqual(result['accepted_perspectives'], 0)

    def test_contradicting_members_not_joined_even_if_supporting_anchor(self):
        members = self.members(3); pairs = self.matrix(members)
        for edge in ['M1->M0', 'M2->M0']: pairs[edge]['relation'] = 'supports'
        pairs['M1->M2']['relation'] = 'contradicts'
        self.assertEqual(assemble(members, anchors_for(members), pairs)['groups'], [])

    def test_failed_pair_cannot_provide_support(self):
        members = self.members(3); pairs = self.matrix(members)
        for edge in ['M1->M0', 'M2->M0']: pairs[edge]['relation'] = 'supports'
        pairs['M2->M0']['errors'] = ['incomplete_generation']
        result = assemble(members, anchors_for(members), pairs)
        self.assertEqual(result['groups'], [])
        self.assertIn('M2->M0', result['unassigned'][2]['failed_pair_ids'])

    def test_partition_is_disjoint_and_complete_with_overlapping_support(self):
        members = self.members(5); pairs = self.matrix(members)
        for edge in ['M1->M0', 'M2->M0', 'M2->M3', 'M4->M3']: pairs[edge]['relation'] = 'supports'
        result = assemble(members, anchors_for(members), pairs)
        covered = [m for g in result['groups'] for m in g['member_ids']] + [r['member_id'] for r in result['unassigned']]
        self.assertEqual(len(covered), len(set(covered))); self.assertEqual(set(covered), set(members))

    def test_incomplete_matrix_or_changed_anchor_rejected(self):
        members = self.members(); anchors = anchors_for(members); pairs = self.matrix(members)
        bad = copy.deepcopy(anchors); bad['M0']['text'] = 'Changed'
        with self.assertRaises(ValueError): assemble(members, bad, pairs)
        with self.assertRaises(ValueError): score_pairs(members, bad, self.provider)
        del pairs['M1->M0']
        with self.assertRaises(ValueError): assemble(members, anchors, pairs)

    def test_minimum_support_cannot_be_lowered(self):
        members = self.members()
        for minimum in [1, 2, True]:
            with self.assertRaises(ValueError): assemble(members, anchors_for(members), self.matrix(members), minimum)

    def test_render_escapes_source_and_lists_unassigned_and_matrix(self):
        members = self.members(3); members['M0']['target'] = '<script>text</script>'
        anchors = anchors_for(members); pairs = self.matrix(members)
        page = render({'members': members, 'anchors': anchors, 'pairs': pairs, 'summary': {},
                       'assembly': assemble(members, anchors, pairs)})
        self.assertNotIn('<script>', page); self.assertIn('&lt;script&gt;', page)
        self.assertIn('미배정 댓글', page); self.assertIn('지원 관계 행렬', page)
