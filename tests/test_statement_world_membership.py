"""Independent worlds veto scope loss without repairing source or model votes."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import statement_worlds as worlds
from commentscope.factory import raw_membership as raw, source_context_observations as contexts
from commentscope.factory import compact_claims
from commentscope.factory.pipeline_work import PipelineWork
from commentscope.factory.automatic_contract import digest
from test_raw_membership import candidate
from test_raw_membership_source_context import observation


class StatementWorldTests(TestCase):
    def setUp(self):
        self.source = {'id': 'source', 'text': 'In the novel Mooncity, all residents have their basic needs met.', 'parent': None}
        self.target = candidate(self.source, 'All residents have their basic needs met.')

    def world(self, text, kind='real_world', anchor='', parent=None):
        return worlds.bind(text, {'output': {'world': kind, 'anchor': anchor}}, parent=parent)

    def bind(self, target=None, *, source_world=None, candidate_world=None, output=None, context=None):
        target = target or self.target
        source_world = source_world or self.world(self.source['text'], 'fictional_world', 'Mooncity')
        candidate_world = candidate_world or self.world(target['text'])
        context = context or contexts.bind(self.source, {'output': {
            'source_use': 'substantive_assertion', 'reported_descriptors': []}})
        return raw.bind(self.source, target, {'output': output or observation()}, version=raw.WORLD_CONTEXT,
                        source_context=context, source_world=source_world, candidate_world=candidate_world)

    def test_classifier_receives_one_text_and_only_its_optional_parent(self):
        req = worlds.request(self.target['text'])
        self.assertEqual(req['data'], {'STATEMENT': self.target['text'], 'PARENT_CONTEXT_ONLY': None})
        self.assertNotIn('ORIGINAL', req['data'])
        self.assertLessEqual(req['max_tokens'], 256)

    def test_fictional_source_cannot_support_an_unqualified_real_world_claim(self):
        bound = self.bind()
        self.assertEqual(bound['output']['relation'], 'supported')
        self.assertEqual(bound['relation'], 'uncertain')
        self.assertIn('independent_world_scope_unapproved', bound['guards'])
        self.assertFalse(bound['passed'])
        self.assertEqual(raw.validate(bound), bound)

    def test_matching_explicit_fictional_world_preserves_a_valid_own_statement(self):
        target = candidate(self.source, 'In the novel Mooncity, all residents have their basic needs met.')
        bound = self.bind(target, candidate_world=self.world(target['text'], 'fictional_world', 'Mooncity'))
        self.assertTrue(bound['passed'])
        self.assertFalse(bound['semantic_approval'])
        self.assertFalse(bound['factual_verification'])

    def test_different_fictional_names_and_unclear_worlds_do_not_approve(self):
        target = candidate(self.source, 'In the novel Ironrealm, all residents have their basic needs met.')
        for check in (self.world(target['text'], 'fictional_world', 'Ironrealm'),
                      self.world(target['text'], 'mixed_or_unclear')):
            self.assertFalse(self.bind(target, candidate_world=check)['passed'])

    def test_real_policy_conditions_are_not_automatically_fictional_worlds(self):
        self.source['text'] = 'Require reviews only if fees are waived.'
        target = candidate(self.source, self.source['text'])
        bound = self.bind(target, source_world=self.world(self.source['text']), candidate_world=self.world(target['text']))
        self.assertTrue(bound['passed'])

    def test_hypothetical_frame_must_match_and_cannot_become_realized_fact(self):
        self.source['text'] = 'Imagine no scarcity. Everyone could rest.'
        source = self.world(self.source['text'], 'hypothetical_world', 'Imagine no scarcity')
        target = candidate(self.source, 'Everyone could rest.')
        self.assertFalse(self.bind(target, source_world=source)['passed'])
        framed = candidate(self.source, 'Imagine no scarcity: everyone could rest.')
        self.assertTrue(self.bind(framed, source_world=source,
            candidate_world=self.world(framed['text'], 'hypothetical_world', 'Imagine no scarcity'))['passed'])

    def test_source_parent_can_resolve_world_but_cannot_leak_into_candidate_observation(self):
        self.source.update(text='They have their basic needs met.', parent={'id': 'p', 'text': 'In the novel Mooncity.'})
        source = self.world(self.source['text'], 'fictional_world', 'Mooncity', parent=self.source['parent']['text'])
        target = candidate(self.source, self.source['text'])
        leaked = self.world(target['text'], 'fictional_world', 'Mooncity', parent=self.source['parent']['text'])
        with self.assertRaises(ValueError): self.bind(target, source_world=source, candidate_world=leaked)
        self.assertFalse(self.bind(target, source_world=source, candidate_world=self.world(target['text']))['passed'])

    def test_foreign_text_missing_observations_and_legacy_protocol_cannot_bypass_binding(self):
        with self.assertRaises(ValueError): self.bind(source_world=self.world('Foreign statement.'))
        context = contexts.bind(self.source, {'output': {'source_use': 'substantive_assertion', 'reported_descriptors': []}})
        with self.assertRaises(ValueError):
            raw.bind(self.source, self.target, {'output': observation()}, version=raw.WORLD_CONTEXT, source_context=context)
        with self.assertRaises(ValueError):
            raw.bind(self.source, self.target, {'output': observation()}, version=raw.SOURCE_CONTEXT,
                     source_context=context, source_world=self.world(self.source['text'], 'fictional_world', 'Mooncity'))

    def test_positive_worlds_cannot_override_authorship_scope_genre_or_primary_rejection(self):
        self.source['text'] = self.target['text']
        for updates in ({'authorship': 'not_asserted'}, {'scope_preserved': 'no'},
                        {'evidence_segment_ids': []}, {'relation': 'unrelated'}):
            self.assertFalse(self.bind(source_world=self.world(self.source['text']), output=observation(**updates))['passed'])
        context = contexts.bind(self.source, {'output': {'source_use': 'promotion_or_referral', 'reported_descriptors': []}})
        self.assertFalse(self.bind(source_world=self.world(self.source['text']), context=context)['passed'])

    def test_literal_anchor_and_closed_observation_fields_are_never_repaired(self):
        for output in ({'world': 'fictional_world', 'anchor': 'invented'},
                       {'world': 'fictional_world', 'anchor': ''},
                       {'world': 'real_world', 'anchor': 'Mooncity'},
                       {'world': 'unknown', 'anchor': ''}, {'world': 'real_world'},
                       {'world': 'real_world', 'anchor': '', 'approved': True}):
            with self.assertRaises(ValueError): worlds.bind(self.source['text'], {'output': output})
        with self.assertRaises(ValueError): worlds.bind(self.source['text'], {'output': None, 'errors': ['invalid_response']})

    def test_response_world_anchor_parent_and_positive_flag_tampering_fail_replay(self):
        bound = self.bind()
        for change in (lambda r: r['source_world']['output'].update(world='real_world', anchor=''),
                       lambda r: r['candidate_world'].update(parent='Mooncity'),
                       lambda r: r.update(passed=True)):
            other = deepcopy(bound); change(other)
            with self.assertRaises(ValueError): raw.validate(other)

    def test_pipeline_caches_independent_worlds_and_vetoes_before_route_or_evidence_calls(self):
        calls = []
        class Runner:
            def call(_, stage, request):
                calls.append((stage, request))
                if stage.startswith('source-context'):
                    return {'output': {'source_use': 'substantive_assertion', 'reported_descriptors': []}, 'raw': 'authored', 'errors': []}
                if request['system'].startswith(worlds.SYSTEM):
                    text = request['data']['STATEMENT']
                    return {'output': {'world': 'fictional_world' if 'Mooncity' in text else 'real_world',
                                       'anchor': 'Mooncity' if 'Mooncity' in text else ''}, 'raw': 'authored', 'errors': []}
                return {'output': observation(), 'raw': 'authored', 'errors': []}
        work = PipelineWork(Runner(), lambda req: {'fits': True, 'request_sha256': digest(req)},
            lambda *args: None, registry={'source': self.source}, membership_mode='raw',
            verification_contract='raw-membership-verification-20261026-v12', schedule={}, extraction_protocol=compact_claims.SEGMENTED)
        pairs = [{'source_id': 'source', 'candidate_id': self.target['id']}]
        first = work.judge('nomination', pairs, [self.target])
        work.judge('membership', pairs, [self.target])
        self.assertFalse(first[0]['memberships'][0]['relation'] == 'supported')
        self.assertEqual(sum(req['system'].startswith(worlds.SYSTEM) for _, req in calls), 2)
        self.assertFalse(any(stage.startswith(('raw-candidate-route', 'raw-own-evidence')) for stage, _ in calls))
