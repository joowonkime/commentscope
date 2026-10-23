from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from commentscope.factory import position_frames as f, framed_clusters as c
from commentscope.factory.automatic_contract import digest
from commentscope.ingestion import load_snapshot


def position(statement='Adopt policy P.', *, qualifications=None, reasons=None):
    return {'target': 'policy P adoption', 'statement': statement, 'mode': 'normative',
            'entity': 'policy P', 'time': '', 'segment_ids': ['S000'],
            'qualifications': qualifications or [], 'reasons': reasons or []}


class FramedClustersTests(TestCase):
    def setUp(self):
        template = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        texts = ['Adopt policy P immediately. Freedom is my reason.',
                 'Policy P should be adopted. Fairness is my reason.',
                 'I support adopting policy P.',
                 'Adopt policy P only if funding is secured.',
                 'Do not adopt policy P.']
        self.snapshot = replace(template, usage=replace(template.usage, expires_at='2099-01-01T00:00:00Z'),
                                comments=tuple(replace(template.comments[0], comment_id=f's{i}', text_original=t)
                                               for i, t in enumerate(texts)))
        extra = {'text': 'immediately', 'role': 'additional', 'segment_ids': ['S000']}
        condition = {'text': 'only if funding is secured', 'role': 'essential', 'segment_ids': ['S000']}
        self.positions = [position(qualifications=[extra], reasons=[
            {'text': 'Freedom is my reason.', 'dependency': 'supporting', 'segment_ids': ['S001']}]),
            position(reasons=[{'text': 'Fairness is my reason.', 'dependency': 'supporting', 'segment_ids': ['S001']}]),
            position(), position('Adopt P only if funding is secured.', qualifications=[condition]),
            position('Do not adopt policy P.')]
        self.records = [self.record(i) for i in range(5)]
        contract = {'target': 'policy P adoption', 'statement': 'Adopt policy P.',
                    'entity': 'policy P', 'time': '', 'conditions': ''}
        result = {'errors': [], 'output': {'candidates': [{'contract': contract,
                  'nominees': [r['positions'][0]['id'] for r in self.records[:3]]}]}}
        self.candidate = c.proposals(self.records, result)[0]

    def record(self, i, positions=None):
        return f.bind(f.source_packet(self.snapshot, f's{i}'), {'errors': [], 'output': {
            'status': 'positions', 'positions': positions if positions is not None else [self.positions[i]]}})

    def membership(self, i, relation='supported', *, unit=0, qualification_status='preserved', **changes):
        record = self.records[i]; p = record['positions'][unit]
        value = {'frame_fidelity': 'faithful', 'premise_completeness': 'preserved', 'relation': relation,
                 'qualifications': [{'qualification_id': q['id'], 'status': qualification_status}
                                    for q in p['qualifications']], 'reason': 'Synthetic contract case.'}
        value.update(changes)
        return c.bind_membership(record, p['id'], self.candidate, {'errors': [], 'output': value})

    def build(self, memberships):
        return c.assemble_map(self.snapshot, self.records, [self.candidate], memberships)

    def test_shared_stance_different_reasons_and_additional_request(self):
        out = self.build([self.membership(i) for i in range(3)] +
                         [self.membership(3, 'conditional'), self.membership(4, 'opposed')])
        p = out['opinion_map']['perspectives'][0]
        self.assertEqual(p['counts']['supported'], 3)
        self.assertEqual(p['counts']['conditional'], 1)
        self.assertEqual(p['counts']['not_supported'], 1)
        self.assertTrue(p['minimum_support_met'])
        self.assertFalse(out['quality_gate_passed'])
        facets = out['source_facets'][self.candidate['id']]
        self.assertEqual(facets[0]['reasons'][0]['source_id'], 's0')
        self.assertEqual(facets[1]['reasons'][0]['source_id'], 's1')
        self.assertNotEqual(facets[0]['reasons'][0]['text'], facets[1]['reasons'][0]['text'])

    def test_discovery_view_excludes_reasons_and_additional_qualifier(self):
        view = f.stance_view(self.records[0])[0]
        self.assertNotIn('reasons', view)
        self.assertEqual(view['restrictions'], [])
        self.assertEqual(len(f.stance_view(self.records[3])[0]['restrictions']), 1)
        self.assertTrue(self.records[0]['positions'][0]['qualifications'])

    def test_nomination_is_not_a_support_vote(self):
        out = self.build([])
        self.assertEqual(out['opinion_map']['perspectives'][0]['counts']['supported'], 0)
        self.assertEqual(out['opinion_map']['perspectives'][0]['counts']['unassessed'], 5)

    def test_missing_essential_condition_cannot_override_supported_label(self):
        m = self.membership(3, qualification_status='missing_or_changed')
        self.assertEqual(m['decision']['relation'], 'supported')
        self.assertEqual(m['relation'], 'uncertain')
        self.assertTrue(m['guards'])
        self.assertEqual(self.build([m])['opinion_map']['perspectives'][0]['counts']['supported'], 0)

    def test_essential_cannot_be_downgraded_to_additional_preference(self):
        self.assertEqual(self.membership(3, qualification_status='additional_only')['relation'], 'uncertain')

    def test_additional_request_does_not_block_shared_stance(self):
        self.assertEqual(self.membership(0, qualification_status='additional_only')['relation'], 'supported')

    def test_uncertain_extracted_condition_is_not_silently_approved(self):
        self.positions[3]['qualifications'][0]['role'] = 'uncertain'
        self.records[3] = self.record(3)
        self.assertEqual(self.membership(3)['relation'], 'uncertain')

    def test_frame_or_premise_failure_blocks_support(self):
        for changes in ({'frame_fidelity': 'distorted'}, {'frame_fidelity': 'unclear'},
                        {'premise_completeness': 'missing'}, {'premise_completeness': 'unclear'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.membership(0, **changes)['relation'], 'uncertain')

    def test_explanation_maxlength_matches_schema_without_relaxing_claim_limits(self):
        self.assertEqual(self.membership(0, reason='x' * 400)['relation'], 'supported')
        with self.assertRaises(ValueError): self.membership(0, reason='x' * 401)
        self.positions[0]['statement'] = 'x' * 600
        with self.assertRaises(ValueError): self.record(0)

    def test_every_qualification_requires_one_decision(self):
        with self.assertRaises(ValueError): self.membership(0, qualifications=[])
        qid = self.records[0]['positions'][0]['qualifications'][0]['id']
        checks = [{'qualification_id': qid, 'status': 'preserved'}] * 2
        with self.assertRaises(ValueError): self.membership(0, qualifications=checks)

    def test_wrong_claim_source_or_frame_cannot_reuse_membership(self):
        for key in ('frame_sha256', 'candidate_sha256', 'source_id', 'request_sha256'):
            m = self.membership(0); m[key] = 'changed'
            with self.subTest(key=key), self.assertRaises(ValueError): self.build([m])

    def test_duplicate_membership_rejected(self):
        m = self.membership(0)
        with self.assertRaises(ValueError): self.build([m, m])

    def test_two_position_votes_from_one_source_count_once(self):
        second = position('I favor adopting policy P.')
        self.records[2] = self.record(2, [self.positions[2], second])
        # s2 was a nominee: a changed frame requires a new candidate binding.
        self.candidate['frame_sha256']['s2'] = digest(self.records[2])
        out = self.build([self.membership(2), self.membership(2, unit=1)])
        self.assertEqual(out['opinion_map']['perspectives'][0]['counts']['supported'], 1)

    def test_unrelated_second_position_does_not_require_shared_reason_or_topic(self):
        second = position('Public meetings should be accessible.')
        second['target'] = 'public meetings'
        self.records[2] = self.record(2, [self.positions[2], second])
        self.candidate['frame_sha256']['s2'] = digest(self.records[2])
        out = self.build([self.membership(2), self.membership(2, 'unrelated', unit=1)])
        self.assertEqual(out['opinion_map']['perspectives'][0]['counts']['supported'], 1)

    def test_conflicting_or_unexamined_second_position_is_not_hidden(self):
        self.records[2] = self.record(2, [self.positions[2], position('Do not adopt policy P.')])
        self.candidate['frame_sha256']['s2'] = digest(self.records[2])
        for ms in ([self.membership(2)], [self.membership(2), self.membership(2, 'opposed', unit=1)]):
            with self.subTest(ms=ms):
                out = self.build(ms)['opinion_map']['perspectives'][0]['counts']
                self.assertEqual(out['supported'], 0)
                self.assertEqual(out['uncertain'], 1)

    def test_non_nominee_can_join_after_independent_check(self):
        # This synthetic test verifies routing, not semantic correctness of s4.
        self.assertNotIn(self.records[4]['positions'][0]['id'], self.candidate['nominees'])
        out = self.build([self.membership(4)])
        self.assertEqual(out['opinion_map']['perspectives'][0]['supported_canonical_ids'], ['s4'])

    def test_singleton_candidate_is_preserved_without_promotion(self):
        candidate = deepcopy(self.candidate)
        candidate['nominees'] = [self.records[0]['positions'][0]['id']]
        candidate['frame_sha256'] = {'s0': digest(self.records[0])}
        self.candidate = candidate
        out = self.build([self.membership(0)])
        self.assertFalse(out['opinion_map']['perspectives'][0]['minimum_support_met'])
        self.assertEqual(out['agent_approval'], 'not_evaluated')

    def test_proposal_changes_and_unknown_nominees_rejected(self):
        self.candidate['contract']['statement'] = 'A different claim.'
        with self.assertRaises(ValueError): self.build([])

    def test_bound_reason_ownership_cannot_be_changed(self):
        self.records[0]['positions'][0]['reasons'][0]['source_id'] = 's1'
        with self.assertRaises(ValueError): self.build([])

    def test_exact_span_copy_and_context_survive_binding(self):
        p = self.records[0]['positions'][0]
        for facet in [p, *p['reasons'], *p['qualifications']]:
            for span in facet['spans']:
                self.assertEqual(self.snapshot.comments[0].text_original[span['start']:span['end']], span['text'])

    def test_unknown_and_duplicate_segments_rejected(self):
        for ids in (['missing'], ['S000', 'S000'], []):
            self.positions[0]['segment_ids'] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError): self.record(0)

    def test_partial_generation_and_silent_capacity_truncation_rejected(self):
        source = f.source_packet(self.snapshot, 's0')
        value = {'status': 'positions', 'positions': [self.positions[0]]}
        with self.assertRaises(ValueError): f.bind(source, {'errors': ['incomplete_generation'], 'output': value})
        value['status'] = 'capacity_deferred'
        with self.assertRaises(ValueError): f.bind(source, {'errors': [], 'output': value})
        value['positions'] = []
        self.assertEqual(f.bind(source, {'errors': [], 'output': value})['positions'], [])

    def test_parent_is_context_not_a_source_owned_evidence_segment(self):
        self.snapshot = replace(self.snapshot, comments=(self.snapshot.comments[0],
            replace(self.snapshot.comments[1], parent_id='s0', parent_status='present'), *self.snapshot.comments[2:]))
        source = f.source_packet(self.snapshot, 's1')
        self.assertEqual(source['parent']['id'], 's0')
        req = f.invocation(source)
        self.assertNotIn('Freedom', str(req['data']['SOURCE_SEGMENTS']))
        record = f.bind(source, {'errors': [], 'output': {'status': 'positions', 'positions': [self.positions[1]]}})
        self.assertEqual(record['positions'][0]['reasons'][0]['source_id'], 's1')

    def test_duplicate_alias_frame_cannot_vote(self):
        alias = replace(self.snapshot.comments[0], comment_id='zalias')
        self.snapshot = replace(self.snapshot, comments=self.snapshot.comments + (alias,))
        record = f.bind(f.source_packet(self.snapshot, 'zalias'), {'errors': [], 'output': {
            'status': 'positions', 'positions': [self.positions[0]]}})
        with self.assertRaises(ValueError):
            c.assemble_map(self.snapshot, [*self.records, record], [self.candidate], [])

    def test_foreign_snapshot_or_parent_cannot_be_attached(self):
        self.snapshot = replace(self.snapshot, comments=(replace(self.snapshot.comments[0], text_original='Changed.'),
                                                         *self.snapshot.comments[1:]))
        with self.assertRaises(ValueError): self.build([])

    def test_no_input_mutation(self):
        before = deepcopy((self.records, self.candidate))
        self.build([self.membership(0)])
        self.assertEqual(before, (self.records, self.candidate))
