"""Source interpretation survives nomination without becoming support or truth."""
from copy import deepcopy
import unittest

from commentscope.factory import compact_claims as compact, minimal_claims as mc
from commentscope.factory import minimal_membership as membership, raw_membership as raw
from commentscope.factory import candidate_consolidation as consolidation
from commentscope.factory import source_interpretation as interpretation
from commentscope.factory.automatic_contract import digest
from test_compact_unified_selections import row


PROTOCOL = 'compact-source-claims-20261104-v8'


def extract(source, rows, *, previous=None, more=False):
    return compact.bind(source, {'output': {'c': rows, 'm': more}},
                        protocol=PROTOCOL, previous=previous)


class SourceInterpretationTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'child', 'text': 'Either that or keep the service voluntary.',
                       'parent': {'id': 'parent', 'text': 'Make reviews mandatory.'}}

    def candidate(self, source=None):
        source = source or self.source
        return mc.candidates([extract(source, [row(text='Either require reviews or keep the service voluntary.')])])[0]

    def test_v8_keeps_original_v7_request_and_normalization(self):
        response = {'output': {'c': [row(text='Either require reviews or keep the service voluntary.')], 'm': False}}
        old = compact.bind(self.source, response, protocol=compact.PROPOSALS)
        new = compact.bind(self.source, response, protocol=PROTOCOL)
        self.assertEqual(compact.request(self.source, protocol=PROTOCOL),
                         compact.request(self.source, protocol=compact.PROPOSALS))
        self.assertEqual(new['canonical_record'], old['canonical_record'])
        self.assertNotIn('source_interpretation', old['claims'][0])
        proposal = new['claims'][0]['source_interpretation']
        self.assertEqual(proposal['proposal'], old['claims'][0])
        self.assertEqual(proposal['source'], self.source)
        self.assertFalse(proposal['semantic_approval'])
        self.assertFalse(proposal['factual_verification'])
        self.assertEqual(compact.validate(new), new)

    def test_conditions_and_framing_are_bound_without_word_specific_rules(self):
        cases = [
            'Adopt the policy only if grants are available.',
            'Either restrict access or retain public review.',
            'In the imagined city, food is free three days a week.',
            'Some people demand closure. I disagree.',
            'Why trade privacy for convenience?',
        ]
        for text in cases:
            with self.subTest(text=text):
                source = {'id': 'own', 'text': text, 'parent': None}
                request = compact.request(source, protocol=PROTOCOL)
                locked = request['data']['LOCKED_CONDITIONALS']
                rows = ([row(evidence=locked[0]['evidence_segment_ids'],
                             conditions=locked[0]['essential_condition_segment_ids'], locked=locked[0]['id'])]
                        if locked else [row()])
                record = extract(source, rows)
                claim = record['claims'][0]
                bound = interpretation.validate(claim['source_interpretation'])
                self.assertEqual(bound['proposal']['evidence'], claim['evidence'])
                self.assertEqual(bound['proposal']['essential_conditions'], claim['essential_conditions'])
                self.assertEqual(bound['source']['text'], text)
                self.assertFalse(bound['semantic_approval'])

    def test_candidate_keeps_proposal_and_only_one_representative_context(self):
        first = self.candidate()
        other = {**self.source, 'id': 'z-child', 'parent': {'id': 'z-parent', 'text': 'Choose optional review.'}}
        records = [extract(s, [row(text=first['text'])]) for s in [other, self.source]]
        forward = mc.candidates(records)[0]
        backward = mc.candidates(list(reversed(records)))[0]
        self.assertEqual(forward, backward)
        self.assertEqual(forward['source_interpretation']['source'], self.source)
        self.assertEqual(len(forward['nominees']), 2)
        self.assertEqual(len(forward['extraction_refs']), 2)
        packet = mc.candidate_packet(forward)
        self.assertEqual(packet['SOURCE_INTERPRETATION_PROPOSAL'], interpretation.packet(first['source_interpretation']))
        self.assertFalse(packet['SOURCE_INTERPRETATION_PROPOSAL']['semantic_approval'])

    def test_parent_and_other_authors_never_enter_own_evidence(self):
        candidate = self.candidate()
        context = candidate['source_interpretation']
        self.assertEqual(context['proposal']['evidence'][0]['text'], self.source['text'])
        request = raw.request(self.source, candidate)
        self.assertIn('OWN_INTERPRETATION_PROPOSAL', request['data'])
        self.assertNotIn('SOURCE_INTERPRETATION_PROPOSAL', request['data']['CANDIDATE'])
        foreign = {'id': 'other', 'text': 'Keep the service voluntary.', 'parent': None}
        self.assertNotIn('OWN_INTERPRETATION_PROPOSAL', raw.request(foreign, candidate)['data'])
        changed = deepcopy(context)
        changed['proposal']['evidence'][0]['text'] = self.source['parent']['text']
        with self.assertRaises(ValueError): interpretation.validate(changed)

    def test_reported_and_uncertain_proposals_are_retained_without_nomination(self):
        for author in ['reported', 'uncertain']:
            record = extract(self.source, [row(text='Make reviews mandatory.', author=author)])
            self.assertIn('source_interpretation', record['claims'][0])
            self.assertEqual(mc.candidates([record]), [])

    def test_supplement_keeps_both_proposals_and_their_original_provenance(self):
        source = {'id': 'own', 'text': 'Keep review voluntary. Protect access.', 'parent': None}
        first = extract(source, [row()], more=True)
        final = extract(source, [row(evidence=('S001',))], previous=first)
        self.assertEqual(final['claims'][0], first['claims'][0])
        self.assertEqual(len(mc.candidates([final])), 2)
        self.assertEqual(compact.validate(final), final)

    def test_source_parent_conditions_authorship_and_identity_mutations_fail(self):
        original = self.candidate()
        for mutate in [
            lambda c: c['source_interpretation']['source']['parent'].update(text='Unrelated parent.'),
            lambda c: c['source_interpretation']['proposal'].update(authorship='reported'),
            lambda c: c['source_interpretation'].update(semantic_approval=True),
            lambda c: c.update(extraction_refs=[]),
        ]:
            changed = deepcopy(original)
            mutate(changed)
            with self.assertRaises(ValueError): mc.validate_candidate(changed)
        source = {'id': 'own', 'text': 'Adopt P only if funded.', 'parent': None}
        locked = compact.request(source, protocol=PROTOCOL)['data']['LOCKED_CONDITIONALS'][0]
        record = extract(source, [row(evidence=locked['evidence_segment_ids'],
                                     conditions=locked['essential_condition_segment_ids'], locked=locked['id'])])
        changed = mc.candidates([record])[0]
        changed['source_interpretation']['proposal']['essential_conditions'] = []
        with self.assertRaises(ValueError): mc.validate_candidate(changed)

    def test_changed_or_stripped_interpretation_invalidates_previous_membership(self):
        candidate = self.candidate()
        response = {'output': {'relation': 'uncertain', 'authorship': 'unclear',
            'candidate_interpretation': 'uncertain', 'scope_preserved': 'unclear',
            'contribution': 'uncertain', 'evidence_segment_ids': []}}
        bound = raw.bind(self.source, candidate, response)
        batch = raw.batch([self.source], [candidate], [bound])
        self.assertEqual(membership.collect([self.source], [candidate], [batch])[0]['relation'], 'uncertain')
        changed = deepcopy(candidate); changed.pop('source_interpretation')
        with self.assertRaises(ValueError): membership.collect([self.source], [changed], [batch])
        changed_source = {**self.source, 'parent': {'id': 'parent', 'text': 'Use a different kind of review.'}}
        other = self.candidate(changed_source)
        self.assertEqual(other['id'], candidate['id'])
        with self.assertRaises(ValueError): membership.collect([self.source], [other], [batch])

    def test_consolidation_and_independent_checks_do_not_invent_context_support(self):
        from commentscope.factory import raw_membership_verification as verification
        candidate = self.candidate()
        final = consolidation.consolidate([self.source], [candidate], [], [])['candidates'][0]
        self.assertEqual(final['source_interpretation'], candidate['source_interpretation'])
        self.assertEqual(verification.independent_candidate_view({'candidate': candidate, 'source': self.source}),
                         ({'text': candidate['text']}, []))
        self.assertEqual(mc.candidate_context_hashes(candidate),
                         {'candidate_interpretation_sha256': digest(candidate['source_interpretation'])})

    def test_bad_paraphrase_stays_visible_and_is_never_marked_semantically_repaired(self):
        record = extract(self.source, [row(text='Keep the service voluntary.')])
        proposal = record['claims'][0]['source_interpretation']
        self.assertEqual(proposal['proposal']['text'], 'Keep the service voluntary.')
        self.assertIn('Either', proposal['proposal']['evidence'][0]['text'])
        self.assertFalse(proposal['semantic_approval'])
        self.assertFalse(record['semantic_approval'])

    def test_scoped_membership_also_binds_the_interpretation(self):
        candidate = self.candidate()
        pairs = [{'source_id': self.source['id'], 'candidate_id': candidate['id']}]
        response = {'output': {'decisions': [{'pair_id': 'P1', 'relation': 'uncertain',
            'authorship': 'unclear', 'scope_preserved': 'unclear', 'evidence_segment_ids': ['S000']}]}}
        batch = membership.bind([self.source], [candidate], pairs, response)
        self.assertEqual(membership.collect([self.source], [candidate], [batch])[0]['relation'], 'uncertain')
        stripped = deepcopy(candidate); stripped.pop('source_interpretation')
        with self.assertRaises(ValueError): membership.collect([self.source], [stripped], [batch])
        old = membership.bind([self.source], [stripped], pairs, response)
        with self.assertRaises(ValueError): membership.collect([self.source], [candidate], [old])

    def test_scoped_comparison_also_keeps_foreign_nomination_context_out(self):
        candidate = self.candidate()
        foreign = {'id': 'other', 'text': 'Keep the service voluntary.', 'parent': None}
        request = membership.membership_request([self.source, foreign], [candidate],
            [{'source_id': s['id'], 'candidate_id': candidate['id']} for s in [self.source, foreign]])
        own, other = request['data']['PAIRS']
        self.assertIn('OWN_INTERPRETATION_PROPOSAL', own)
        self.assertNotIn('OWN_INTERPRETATION_PROPOSAL', other)
        self.assertEqual(own['CANDIDATE'], {'text': candidate['text']})
        self.assertEqual(other['CANDIDATE'], {'text': candidate['text']})

    def test_bilateral_equivalence_compares_written_candidates_without_source_donation(self):
        sources = [{'id': 'a', 'text': 'Adopt reviews.', 'parent': None},
                   {'id': 'b', 'text': 'Require reviews.', 'parent': None}]
        candidates = mc.candidates([extract(s, [row()]) for s in sources])
        by_source = {c['source_interpretation']['source']['id']: c for c in candidates}
        assessments = [raw.bind(s, by_source[s['id']], {'output': {
            'relation': 'supported', 'authorship': 'asserted_or_endorsed',
            'candidate_interpretation': 'clear', 'scope_preserved': 'yes',
            'contribution': 'substantive', 'evidence_segment_ids': ['S000']}}) for s in sources]
        batch = raw.batch(sources, candidates, assessments)
        pair = {'a': candidates[0]['id'], 'b': candidates[1]['id']}
        request = consolidation.equivalence_request(sources, candidates, [batch], [pair],
                                                    protocol=consolidation.BILATERAL)
        self.assertEqual(request['data']['PAIRS'][0]['A'], {'text': candidates[0]['text']})
        self.assertEqual(request['data']['PAIRS'][0]['B'], {'text': candidates[1]['text']})


class TracedPipelineTests(unittest.TestCase):
    def test_traced_contract_reaches_agents_with_existing_independent_guards(self):
        from test_compact_claims import CompactPipelineTests
        from commentscope.factory import owned_arguments
        helper = CompactPipelineTests()
        fixture, Runner = helper.fixture()
        self.addCleanup(helper.doCleanups)
        class TracedRunner(Runner):
            def call(self, stage, request):
                if request['system'].startswith(owned_arguments.ALIGN):
                    self.calls.append((stage, request))
                    data = request['data']
                    relation = ('equivalent' if data['SOURCE_POSITION'].rstrip('.') ==
                                data['CANDIDATE']['text'].rstrip('.') else 'different')
                    return {'output': {'relation': relation}}
                return super().call(stage, request)
        runner = TracedRunner()
        result = fixture.process(runner, extraction_protocol=PROTOCOL)
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        self.assertTrue(result['candidates'])
        self.assertTrue(all('source_interpretation' in c for c in result['candidates']))
        self.assertTrue(all(r['artifact_kind'] == PROTOCOL for r in result['extractions']))
        self.assertTrue(all(r['protocol'] == consolidation.BILATERAL for r in result['equivalences']))
        self.assertFalse(result['quality_gate_passed'])
        self.assertFalse(result['runtime_reference_labels'])


if __name__ == '__main__': unittest.main()
