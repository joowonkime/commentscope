from copy import deepcopy
import json
import unittest

from commentscope.factory import source_bound_discovery as boundary
from commentscope.factory import position_frames as frames
from tests import test_framed_clusters as fixture


class SourceBoundDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.FramedClustersTests(); self.fixture.setUp()
        self.records = self.fixture.records

    def test_complete_originals_and_own_spans_are_preserved(self):
        req = boundary.invocation(self.records)
        for original, record in zip(req['data']['ORIGINALS'], self.records, strict=True):
            self.assertEqual(original['text'], record['source']['text'])
            self.assertEqual(original['source_id'], record['source']['id'])
        originals = {r['source_id']: r['text'] for r in req['data']['ORIGINALS']}
        for anchor in req['data']['POSITION_ANCHORS']:
            for span in anchor['spans']:
                self.assertEqual(originals[anchor['source_id']][span['start']:span['end']], span['text'])

    def test_generated_interpretations_are_not_sent_as_evidence(self):
        original = self.records[0]['source']
        generated = fixture.position('INVENTED_STANCE', qualifications=[{
            'text':'INVENTED_CONDITION', 'role':'essential', 'segment_ids':['S000']}], reasons=[{
            'text':'INVENTED_MECHANISM', 'dependency':'essential', 'segment_ids':['S001']}])
        record = frames.bind(original, {'errors':[], 'output':{'status':'positions','positions':[generated]}})
        payload = json.dumps(boundary.invocation([record])['data'])
        for text in ('INVENTED_STANCE', 'INVENTED_CONDITION', 'INVENTED_MECHANISM'):
            self.assertNotIn(text, payload)
        self.assertIn(original['text'], payload)

    def test_parent_is_context_and_has_no_nominated_identity(self):
        packet = deepcopy(self.records[0]['source'])
        packet['parent'] = {'id':'parent', 'text':'Parent opposes the policy.'}
        record = frames.bind(packet, {'errors':[], 'output':{'status':'positions','positions':[fixture.position()]}})
        req = boundary.invocation([record])
        self.assertEqual(req['data']['ORIGINALS'][0]['PARENT_CONTEXT_ONLY'], packet['parent'])
        self.assertEqual({a['source_id'] for a in req['data']['POSITION_ANCHORS']}, {packet['id']})

    def test_existing_candidate_binding_never_approves_or_counts_support(self):
        c = self.fixture.candidate
        result = {'errors':[], 'output':{'candidates':[{'contract':c['contract'],'nominees':c['nominees']}]}}
        self.assertEqual(boundary.bind(self.records, result), [c])
        self.assertFalse(c['semantic_approval'])
        self.assertNotIn('supported', c)
        result['output']['candidates'][0]['nominees'] = ['unknown']
        with self.assertRaises(ValueError): boundary.bind(self.records, result)

    def test_mutated_source_bindings_and_empty_input_fail_closed(self):
        changed = deepcopy(self.records)
        changed[0]['positions'][0]['spans'][0]['text'] = 'Invented quote.'
        with self.assertRaises(ValueError): boundary.invocation(changed)
        with self.assertRaises(ValueError): boundary.invocation([])
        with self.assertRaises(ValueError): boundary.invocation(self.records+self.records[:1])

    def test_source_position_capacity_is_not_silently_truncated(self):
        records = [frames.bind({'id': str(i), 'text': 'Adopt policy P.', 'parent': None},
            {'errors': [], 'output': {'status': 'positions', 'positions': [fixture.position()]}}) for i in range(25)]
        with self.assertRaisesRegex(ValueError, 'one to24'): boundary.invocation(records)

    def test_original_byte_capacity_is_not_silently_truncated(self):
        source = {'id': 'long', 'text': 'Adopt policy P. ' + 'x'*30000, 'parent': None}
        record = frames.bind(source, {'errors': [], 'output': {'status': 'positions', 'positions': [fixture.position()]}})
        with self.assertRaisesRegex(ValueError, 'byte budget'): boundary.invocation([record])


if __name__ == '__main__': unittest.main()
