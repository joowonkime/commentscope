"""A bounded semantic review holds bad proposals without approving support."""
from copy import deepcopy
import unittest

from commentscope.factory import source_interpretation as si, compact_claims as compact
from commentscope.factory import minimal_claims as mc
from commentscope.contracts.structured_output import check_output
from test_compact_unified_selections import row


def extract(source, rows, *, more=False, previous=None):
    return compact.bind(source, {'output': {'c': rows, 'm': more}},
                        protocol=compact.TRACED_PROPOSALS, previous=previous)


def declarations(count=1):
    return {'decisions': [{'id': f'N{i+1}', 'speech_act': 'assertion',
        'epistemic_status': 'stated', 'world': 'real_world', 'reference_use': 'none',
        'references': [], 'scope_links': [], 'world_frame_ids': [],
        'fidelity': {k: 'preserved' for k in si.FIDELITY_CHECKS}} for i in range(count)]}


class SourceSemanticReviewTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'child', 'text': 'Either that or retain public access.',
                       'parent': {'id': 'parent', 'text': 'Require independent review.'}}
        self.record = extract(self.source, [row(text='Either require independent review or retain public access.')])
        self.proposals = [c['source_interpretation'] for c in self.record['claims']]

    def bind(self, output=None, proposals=None):
        return si.bind_review(proposals or self.proposals,
                              {'output': output if output is not None else declarations()})

    def test_request_has_only_closed_labels_and_existing_segment_addresses(self):
        request = si.review_request(self.proposals)
        self.assertEqual(request['data']['PROPOSALS'][0]['id'], 'N1')
        self.assertEqual(request['data']['PARENT_REFERENCE_SEGMENTS'][0]['id'], 'P000')
        self.assertEqual(request['max_tokens'], 4096)
        self.assertNotIn('PHRASES', request['data'])
        self.assertFalse(check_output(request['schema'], declarations())['errors'])

    def test_faithful_declaration_only_permits_nomination_not_support_or_truth(self):
        review = self.bind()
        admitted = si.nominate([self.record], [review])
        self.assertEqual(admitted['candidates'], mc.candidates([self.record]))
        self.assertTrue(review['decisions'][0]['nomination_eligible'])
        self.assertFalse(review['semantic_approval'])
        self.assertFalse(review['support_approved'])
        self.assertFalse(review['factual_verification'])
        self.assertEqual(si.validate_review(review), review)

    def test_every_changed_or_unclear_dimension_holds_instead_of_repairing(self):
        for dimension in si.FIDELITY_CHECKS:
            for verdict in ['changed', 'unclear']:
                with self.subTest(dimension=dimension, verdict=verdict):
                    value = declarations(); value['decisions'][0]['fidelity'][dimension] = verdict
                    review = self.bind(value)
                    self.assertFalse(si.nominate([self.record], [review])['candidates'])
                    self.assertEqual(review['interpretations'], self.proposals)
                    self.assertIn(dimension+'_'+verdict, review['decisions'][0]['holds'])

    def test_disjunction_concession_and_quantity_have_distinct_scope_roles(self):
        for role in ['alternative', 'concession', 'condition', 'reason', 'quantities_time', 'reported_speech']:
            with self.subTest(role=role):
                value = declarations()
                value['decisions'][0]['scope_links'] = [{'kind': role, 'segment_ids': ['S000']}]
                bound = self.bind(value)['decisions'][0]['scope_links'][0]
                self.assertEqual(bound['kind'], role)
                self.assertEqual(bound['segments'][0]['text'], self.source['text'])

    def test_parent_reference_has_exact_offsets_and_never_becomes_own_scope(self):
        value = declarations(); decision = value['decisions'][0]
        decision.update(reference_use='resolved', references=[{'expression_id': 'S000', 'antecedent_ids': ['P000']}])
        reference = self.bind(value)['decisions'][0]['references'][0]
        self.assertEqual(reference['antecedents'][0]['origin'], 'parent_reference_only')
        self.assertEqual(reference['antecedents'][0]['text'], self.source['parent']['text'])
        decision['scope_links'] = [{'kind': 'reason', 'segment_ids': ['P000']}]
        with self.assertRaises(ValueError): self.bind(value)

    def test_unresolved_reference_is_held_but_explicit_author_uncertainty_is_retained(self):
        value = declarations(); value['decisions'][0].update(reference_use='unclear')
        self.assertFalse(self.bind(value)['decisions'][0]['nomination_eligible'])
        value = declarations(); value['decisions'][0].update(speech_act='expressed_uncertainty', epistemic_status='undecided')
        self.assertTrue(self.bind(value)['decisions'][0]['nomination_eligible'])

    def test_questions_reports_and_unresolved_world_are_not_policy_nominations(self):
        for field, value in [('speech_act', 'question'), ('speech_act', 'reported_view'),
                             ('speech_act', 'unclear'), ('world', 'mixed_or_unclear'),
                             ('epistemic_status', 'unclear')]:
            result = declarations(); result['decisions'][0][field] = value
            self.assertFalse(self.bind(result)['decisions'][0]['nomination_eligible'])

    def test_world_frame_uses_literal_segment_ids_without_generated_anchor_bounds(self):
        source = {'id': 'fiction', 'text': 'In the fictional city '+('very '*45)+'far away, reviews are free.', 'parent': None}
        record = extract(source, [row()]); proposals = [record['claims'][0]['source_interpretation']]
        value = declarations(); value['decisions'][0].update(world='fictional_world', world_frame_ids=['S000'])
        review = self.bind(value, proposals)
        frame = review['decisions'][0]['world_frames'][0]
        self.assertGreater(len(frame['text']), 160)
        self.assertEqual(frame['text'], source['text'])
        self.assertFalse(review['factual_verification'])
        value['decisions'][0]['world_frame_ids'] = []
        with self.assertRaises(ValueError): self.bind(value, proposals)

    def test_closed_schema_and_cross_field_constraints_fail_without_repair(self):
        variants = []
        bad = declarations(); bad['decisions'][0]['fidelity'].pop('logical_scope'); variants.append(bad)
        bad = declarations(); bad['decisions'][0]['fidelity']['reference'] = True; variants.append(bad)
        bad = declarations(); bad['decisions'][0]['id'] = 'N99'; variants.append(bad)
        bad = declarations(); bad['decisions'] *= 2; variants.append(bad)
        bad = declarations(); bad['decisions'][0]['references'] = [{'expression_id': 'S000', 'antecedent_ids': ['P000']}]; variants.append(bad)
        bad = declarations(); bad['decisions'][0]['reference_use'] = 'resolved'; variants.append(bad)
        bad = declarations(); bad['decisions'][0]['world_frame_ids'] = ['S000']; variants.append(bad)
        bad = declarations(); bad['decisions'][0]['scope_links'] = [{'kind': 'condition', 'segment_ids': ['S000','S000']}]; variants.append(bad)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError): self.bind(value)
        with self.assertRaises(ValueError): si.bind_review(self.proposals, {'errors': ['timeout']})

    def test_missing_foreign_duplicate_and_mutated_reviews_cannot_authorize_nomination(self):
        self.assertFalse(si.nominate([self.record], [])['candidates'])
        review = self.bind()
        with self.assertRaises(ValueError): si.nominate([self.record], [review, review])
        foreign = extract({**self.source, 'id': 'other'}, [row(text=self.record['claims'][0]['text'])])
        with self.assertRaises(ValueError): si.nominate([foreign], [review])
        for mutate in [lambda r:r['interpretations'][0]['source']['parent'].update(text='Changed.'),
                       lambda r:r['decisions'][0].update(nomination_eligible=False),
                       lambda r:r.update(support_approved=True)]:
            changed = deepcopy(review); mutate(changed)
            with self.assertRaises(ValueError): si.validate_review(changed)

    def test_bad_proposal_does_not_suppress_a_separate_good_proposal_or_source(self):
        source = {'id': 'own', 'text': 'Either require reviews or retain public access. Protect privacy.', 'parent': None}
        record = extract(source, [row(text='Require reviews.'), row(evidence=('S001',))])
        value = declarations(2); value['decisions'][0]['fidelity']['logical_scope'] = 'changed'
        review = self.bind(value, [c['source_interpretation'] for c in record['claims']])
        result = si.nominate([record], [review])
        self.assertEqual([c['text'] for c in result['candidates']], ['Protect privacy.'])
        self.assertEqual(len(record['claims']), 2)

    def test_batches_are_bounded_and_reported_only_sources_need_no_review_call(self):
        source = {'id': 'own', 'text': ' '.join(f'Preserve option {i}.' for i in range(17)), 'parent': None}
        first = extract(source, [row(evidence=(f'S{i:03}',)) for i in range(16)], more=True)
        final = extract(source, [row(evidence=('S016',))], previous=first)
        self.assertEqual([len(t['interpretations']) for t in si.review_tasks([final])], [8,8,1])
        reported = extract(self.source, [row(author='reported')])
        self.assertEqual(si.review_tasks([reported]), [])
        self.assertFalse(si.nominate([reported], [])['candidates'])

    def test_candidate_filter_rejects_foreign_references_and_never_adds_nominees(self):
        with self.assertRaises(ValueError): mc.candidates([self.record], allowed_extraction_refs=['unknown'])
        with self.assertRaises(ValueError): mc.candidates([self.record], allowed_extraction_refs=[None])
        ref = self.record['claims'][0]['record_id']
        with self.assertRaises(ValueError): mc.candidates([self.record], allowed_extraction_refs=[ref,ref])
        self.assertFalse(mc.candidates([self.record], allowed_extraction_refs=[]))

    def test_topic_name_can_resolve_a_reference_but_never_supply_reason_or_world(self):
        source = {**self.source, 'video_context': {'artifact_kind':'snapshot-video-context-20261017-v1',
            'video_id':'topic', 'title':'Independent review policy', 'primary_language':'en'}}
        record = extract(source,[row(text=self.record['claims'][0]['text'])])
        proposals = [record['claims'][0]['source_interpretation']]
        value = declarations(); decision=value['decisions'][0]
        decision.update(reference_use='resolved',references=[{'expression_id':'S000','antecedent_ids':['V_TITLE']}])
        reference = self.bind(value,proposals)['decisions'][0]['references'][0]
        self.assertEqual(reference['antecedents'][0]['origin'],'topic_metadata_only')
        decision['scope_links']=[{'kind':'reason','segment_ids':['V_TITLE']}]
        with self.assertRaises(ValueError): self.bind(value,proposals)
        decision['scope_links']=[];decision.update(world='fictional_world',world_frame_ids=['V_TITLE'])
        with self.assertRaises(ValueError): self.bind(value,proposals)


class SemanticReviewPipelineTests(unittest.TestCase):
    def fixture(self, *, reject=False, malformed=False, empty=False):
        from test_compact_claims import CompactPipelineTests
        from commentscope.factory import owned_arguments
        helper = CompactPipelineTests(); fixture, Base = helper.fixture()
        self.addCleanup(helper.doCleanups)
        class Runner(Base):
            def call(self, stage, request):
                if empty and request['system'].startswith(compact.PREFIX):
                    self.calls.append((stage,request))
                    return {'output': {'c': [], 'm': False}}
                if request['system'].startswith(si.REVIEW_SYSTEM):
                    self.calls.append((stage,request))
                    if malformed: return {'output': {'decisions': []}}
                    value = declarations(len(request['data']['PROPOSALS']))
                    for decision, proposal in zip(value['decisions'],request['data']['PROPOSALS']):
                        decision['speech_act'] = 'request'
                        if reject and proposal['text'] == 'Adopt P.':
                            decision['fidelity']['logical_scope'] = 'changed'
                    return {'output': value}
                if request['system'].startswith(owned_arguments.ALIGN):
                    self.calls.append((stage,request)); data=request['data']
                    return {'output': {'relation': 'equivalent' if data['SOURCE_POSITION'].rstrip('.') ==
                        data['CANDIDATE']['text'].rstrip('.') else 'different'}}
                return super().call(stage,request)
        return fixture,Runner()

    def test_reviewed_path_reaches_two_agents_and_keeps_independent_support(self):
        from experiments.framed_agent_probe import runtime_probe
        fixture,runner=self.fixture()
        result=fixture.process(runner,extraction_protocol=compact.TRACED_PROPOSALS,review_interpretations=True)
        self.assertEqual(len(result['interpretation_reviews']),6)
        self.assertTrue(result['interpretation_review_required'])
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']),2)
        self.assertEqual(len(runtime_probe(result['agent_inputs']['bundle'],runner)['turns']),6)
        self.assertTrue(result['nomination_batches'])
        self.assertFalse(result['quality_gate_passed'])

    def test_negative_review_holds_only_affected_proposals_and_keeps_originals(self):
        fixture,runner=self.fixture(reject=True)
        result=fixture.process(runner,extraction_protocol=compact.TRACED_PROPOSALS,review_interpretations=True)
        self.assertEqual(len(result['extractions']),6)
        self.assertFalse(result['errors'])
        self.assertNotIn('Adopt P.', [c['text'] for c in result['candidates']])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']),1)
        holds=[d for d in result['interpretation_admission']['decisions'] if d['holds']]
        self.assertEqual(len(holds),3)
        self.assertTrue(all('logical_scope_changed' in d['holds'] for d in holds))

    def test_malformed_review_is_recorded_once_without_retry_or_unreviewed_nomination(self):
        fixture,runner=self.fixture(malformed=True)
        result=fixture.process(runner,extraction_protocol=compact.TRACED_PROPOSALS,review_interpretations=True)
        self.assertEqual(len(result['extractions']),6)
        self.assertEqual(len(result['errors']),6)
        self.assertFalse(result['candidates'])
        self.assertTrue(all(d['holds']==['semantic_review_missing'] for d in result['interpretation_admission']['decisions']))
        calls=[req for _,req in runner.calls if req['system'].startswith(si.REVIEW_SYSTEM)]
        self.assertEqual(len(calls),6)

    def test_empty_extractions_dispatch_no_semantic_review(self):
        fixture,runner=self.fixture(empty=True)
        result=fixture.process(runner,extraction_protocol=compact.TRACED_PROPOSALS,review_interpretations=True)
        self.assertEqual(result['interpretation_reviews'],[])
        self.assertFalse(any(req['system'].startswith(si.REVIEW_SYSTEM) for _,req in runner.calls))
        self.assertTrue(all(r['status']=='unresolved' for r in result['extractions']))

    def test_old_default_and_wrong_protocol_do_not_silently_enable_review(self):
        fixture,runner=self.fixture()
        with self.assertRaises(ValueError):fixture.process(runner,review_interpretations=True)
        with self.assertRaises(ValueError):fixture.process(runner,extraction_protocol=compact.PROPOSALS,review_interpretations=True)
        with self.assertRaises(ValueError):fixture.process(runner,review_interpretations=1)
        self.assertEqual(runner.calls,[])


if __name__ == '__main__': unittest.main()
