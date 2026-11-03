"""Recognized approximation loss is a veto, never source-support approval."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import raw_membership as raw, raw_membership_verification as v
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate, decision


PROTOCOL = 'full-scope-evidence-qualifiers-20261103-v3'


class ApproximationEvidenceTests(TestCase):
    def setUp(self):
        self.source = {'id': 's', 'text': 'Program R is essentially like policy P. Results are poor.', 'parent': None}
        self.text = 'Policy P has been implemented through program R.'
        self.value = {'reference_basis': 'self_contained', 'target_alignment': 'aligned',
                      'source_basis': 'own_assertion', 'verdict': 'fully_stated',
                      'basis': 'Authored positive model declaration, not semantic ground truth.'}

    def proof(self, source=None, text=None, evidence=('S000',)):
        source = source or self.source
        return raw.bind(source, candidate(source, text or self.text),
                        {'output': decision(evidence_segment_ids=list(evidence))})

    def bind(self, proof=None, value=None, protocol=PROTOCOL):
        return v.bind_evidence(proof or self.proof(), {'output': value or self.value},
                               v.FULL_SCOPE, protocol=protocol)

    def test_positive_model_cannot_turn_analogy_into_unqualified_implementation(self):
        evidence = self.bind()
        self.assertFalse(evidence['passed'])
        self.assertIn('selected_approximation_not_preserved', evidence['guards'])
        self.assertEqual(evidence['output'], self.value)
        self.assertEqual(evidence['approximation']['source_operators'][0]['text'], 'essentially')
        self.assertFalse(evidence['approximation']['semantic_approval'])

    def test_bounded_operators_are_not_silently_dropped(self):
        for operator in ('essentially', 'basically', 'roughly', 'approximately', 'nearly', 'almost'):
            source = {**self.source, 'text': f'The program is {operator} ready.'}
            with self.subTest(operator=operator):
                evidence = self.bind(self.proof(source, 'The program is ready.'))
                self.assertFalse(evidence['passed'])

    def test_paraphrased_approximations_can_remove_only_this_veto(self):
        examples = [('The program is nearly ready.', 'The program is almost ready.'),
                    ('The grant is roughly ten units.', 'The grant is approximately ten units.'),
                    ('Program R is essentially like P.', 'Program R is similar to P.'),
                    ('이 제도는 거의 준비됐습니다.', 'The program is nearly ready.')]
        for original, target in examples:
            with self.subTest(original=original, target=target):
                proof = self.proof({**self.source, 'text': original}, target)
                evidence = self.bind(proof)
                self.assertTrue(evidence['passed'])
                self.assertFalse(evidence['approximation']['blocked'])
                refused = self.bind(proof, {**self.value, 'target_alignment': 'different_target'})
                self.assertFalse(refused['passed'])

    def test_unselected_original_and_parent_words_do_not_supply_a_veto(self):
        source = {**self.source, 'text': 'Program R is almost ready. Keep policy Q.',
                  'parent': {'id': 'p', 'text': 'Policy Q is roughly like another policy.'}}
        evidence = self.bind(self.proof(source, 'Keep policy Q.', evidence=('S001',)))
        self.assertTrue(evidence['passed'])
        self.assertEqual(evidence['approximation']['source_operators'], [])

    def test_unchanged_unqualified_assertion_keeps_existing_model_checks(self):
        proof = self.proof({**self.source, 'text': 'Keep policy Q.'}, 'Keep policy Q.')
        self.assertTrue(self.bind(proof)['passed'])
        for change in ({'verdict': 'extra_assertion'}, {'source_basis': 'parent_only'},
                       {'reference_basis': 'missing_or_ambiguous'}):
            self.assertFalse(self.bind(proof, {**self.value, **change})['passed'])

    def test_v2_historical_positive_is_preserved_instead_of_retroactively_repaired(self):
        record = self.bind(protocol=v.BRIEF)
        self.assertTrue(record['passed'])
        self.assertNotIn('approximation', record)
        old = v.evidence_request(self.proof(), v.FULL_SCOPE, protocol=v.BRIEF)
        current = v.evidence_request(self.proof(), v.FULL_SCOPE, protocol=PROTOCOL)
        self.assertEqual(old['data'], current['data'])
        self.assertEqual(old['schema'], current['schema'])
        self.assertNotEqual(digest(old), digest(current))

    def test_changed_qualifier_witness_cannot_validate_as_original_proof(self):
        proof = self.proof()
        route = v.bind_route(proof['candidate'], {'output': {'focus_token': 'T1',
            'focus_domain': 'substantive_issue', 'role': 'subject_position', 'interpretation': 'clear'}},
            self.source, version=v.FULL_SCOPE)
        record = v.assessment(proof, route, self.bind(proof), version=v.FULL_SCOPE)
        self.assertEqual(v.validate(record), record)
        changed = deepcopy(record)
        changed['evidence_check']['approximation']['source_operators'][0]['text'] = 'nearly'
        with self.assertRaises(ValueError): v.validate(changed)

    def test_bad_protocol_or_unbounded_model_reply_is_not_repaired(self):
        for protocol in ('unknown',):
            with self.assertRaises(ValueError): self.bind(protocol=protocol)
        with self.assertRaises(ValueError): self.bind(value={**self.value, 'basis': 'x'*241})

    def test_unified_runtime_vetoes_before_a_positive_vote_is_exported(self):
        from commentscope.factory import compact_claims, statement_worlds
        from commentscope.factory.pipeline_work import PipelineWork
        from test_raw_membership_source_context import observation
        owner = self
        class Runner:
            def call(self, stage, req):
                if stage.startswith('source-context'):
                    value = {'source_use': 'substantive_assertion', 'reported_descriptors': []}
                elif req['system'].startswith(statement_worlds.SYSTEM): value = {'world': 'real_world', 'anchor': ''}
                elif stage.startswith('raw-candidate-route'):
                    value = {'focus_token': 'T1', 'focus_domain': 'substantive_issue',
                             'role': 'subject_position', 'interpretation': 'clear'}
                elif stage.startswith('raw-own-evidence'): value = deepcopy(owner.value)
                else:
                    value = observation(); value['source_use'] = 'substantive_assertion'
                return {'output': value, 'raw': 'authored positive model declarations', 'errors': []}
        target = candidate(self.source, self.text)
        work = PipelineWork(Runner(), lambda req: {'fits': True, 'request_sha256': digest(req)},
                            lambda *args: None, registry={'s': self.source}, membership_mode='raw',
                            verification_contract=v.FULL_SCOPE, schedule={}, extraction_protocol=compact_claims.UNIFIED)
        batches = work.judge('membership', [{'source_id': 's', 'candidate_id': target['id']}], [target])
        assessment = batches[0]['verified_assessments'][0]
        self.assertTrue(assessment['raw']['passed'])
        self.assertEqual(assessment['evidence_check']['output']['verdict'], 'fully_stated')
        self.assertIn('selected_approximation_not_preserved', assessment['evidence_check']['guards'])
        self.assertEqual(batches[0]['memberships'][0]['relation'], 'uncertain')
