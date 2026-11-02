"""Authored source observations exercise vetoes, not model semantic accuracy."""
from copy import deepcopy
from unittest import TestCase

from commentscope.factory import compact_claims, raw_membership as raw
from commentscope.factory import source_context_observations as contexts
from commentscope.factory.automatic_contract import digest
from commentscope.factory.pipeline_work import PipelineWork
from test_raw_membership import candidate, decision


def observation(**updates):
    return decision(source_use='substantive_experience', population_scope='preserved',
                    predicate_scope='preserved', descriptor_attribution='preserved',
                    reported_descriptor_uses=[], **updates)


class SourceContextMembershipTests(TestCase):
    def setUp(self):
        self.source = {'id': 'example', 'text': 'I dislike being idle.', 'parent': None}
        self.target = candidate(self.source, self.source['text'])

    def bind(self, value):
        context = contexts.bind(self.source, {'output': {'source_use': 'substantive_experience',
                                                        'reported_descriptors': []}})
        return raw.bind(self.source, self.target, {'output': value}, version=raw.SOURCE_CONTEXT,
                        source_context=context)

    def test_candidate_cannot_override_an_independent_promotional_source_observation(self):
        context = contexts.bind(self.source, {'output': {'source_use': 'promotion_or_referral',
                                                        'reported_descriptors': []}})
        record = raw.bind(self.source, self.target, {'output': observation()},
                          version=raw.SOURCE_CONTEXT, source_context=context)
        self.assertFalse(record['passed'])
        self.assertEqual(record['output']['source_use'], 'substantive_experience')
        self.assertIn('independent_source_use_unapproved', record['guards'])

    def test_every_independently_observed_descriptor_requires_a_unique_use_check(self):
        source = {'id': 'reported', 'text': 'They call residents idle. Those residents work.', 'parent': None}
        context = contexts.bind(source, {'output': {'source_use': 'substantive_assertion',
            'reported_descriptors': [{'segment_id': 'S000', 'text': 'idle'}]}})
        target = candidate(source, 'Idle residents work.')
        for uses in ([], [{'id': 'R000', 'use': 'adopted_report'}],
                     [{'id': 'R000', 'use': 'unclear'}]):
            value = observation(); value['reported_descriptor_uses'] = uses
            if not uses:
                with self.assertRaises(ValueError):
                    raw.bind(source, target, {'output': value}, version=raw.SOURCE_CONTEXT, source_context=context)
            else:
                self.assertFalse(raw.bind(source, target, {'output': value},
                                          version=raw.SOURCE_CONTEXT, source_context=context)['passed'])
        value = observation(); value['reported_descriptor_uses'] = [{'id': 'R000', 'use': 'explicit_report'}]
        reported = candidate(source, 'Residents described by others as idle work.')
        self.assertTrue(raw.bind(source, reported, {'output': value},
                                 version=raw.SOURCE_CONTEXT, source_context=context)['passed'])

    def test_source_observation_has_no_candidate_and_keeps_literal_descriptor_evidence(self):
        req = contexts.request(self.source)
        self.assertEqual(set(req['data']), {'ORIGINAL'})
        with self.assertRaises(ValueError):
            contexts.bind(self.source, {'output': {'source_use': 'substantive_assertion',
                'reported_descriptors': [{'segment_id': 'S000', 'text': 'invented label'}]}})

    def test_changed_original_or_context_observation_cannot_be_rebound(self):
        context = contexts.bind(self.source, {'output': {'source_use': 'substantive_experience',
                                                        'reported_descriptors': []}})
        foreign = deepcopy(context); foreign['source']['id'] = 'foreign'
        changed = deepcopy(context); changed['output']['source_use'] = 'promotion_or_referral'
        for bad in (foreign, changed):
            with self.subTest(context=bad), self.assertRaises(ValueError):
                raw.bind(self.source, self.target, {'output': observation()},
                         version=raw.SOURCE_CONTEXT, source_context=bad)

    def test_promotional_or_social_use_vetoes_an_otherwise_positive_clause(self):
        for use in ('promotion_or_referral', 'creator_or_platform', 'social_only', 'unclear'):
            value = observation(); value['source_use'] = use
            with self.subTest(use=use):
                record = self.bind(value)
                self.assertEqual(record['output']['relation'], 'supported')
                self.assertEqual(record['relation'], 'uncertain')
                self.assertFalse(record['passed'])
                self.assertIn('whole_source_use_unapproved', record['guards'])
                self.assertEqual(raw.validate(record), record)

    def test_changed_population_predicate_or_reported_descriptor_vetoes_support(self):
        for key, value in (('population_scope', 'changed'), ('predicate_scope', 'inferred'),
                           ('descriptor_attribution', 'adopted_report'),
                           ('descriptor_attribution', 'unclear')):
            output = observation(); output[key] = value
            with self.subTest(key=key, value=value):
                record = self.bind(output)
                self.assertFalse(record['passed'])
                self.assertIn(key+'_unapproved', record['guards'])

    def test_substantive_or_mixed_source_use_never_overrides_existing_vetoes(self):
        for use in raw.SUBSTANTIVE_USES:
            for update in ({'authorship': 'not_asserted'}, {'scope_preserved': 'no'},
                           {'evidence_segment_ids': []}, {'contribution': 'context_only'}):
                output = observation(); output.update(source_use=use, **update)
                with self.subTest(use=use, update=update):
                    self.assertFalse(self.bind(output)['passed'])

    def test_personal_experience_does_not_require_a_policy_keyword(self):
        record = self.bind(observation())
        self.assertTrue(record['passed'])
        self.assertFalse(record['semantic_approval'])
        self.assertFalse(record['factual_verification'])

    def test_unknown_missing_or_changed_observation_is_not_repaired(self):
        for key in ('source_use', 'population_scope', 'predicate_scope', 'descriptor_attribution'):
            missing = observation(); missing.pop(key)
            unknown = observation(); unknown[key] = 'approved'
            for output in (missing, unknown):
                with self.subTest(key=key, output=output), self.assertRaises(ValueError):
                    self.bind(output)
        record = self.bind(observation()); record['output']['source_use'] = 'promotion_or_referral'
        with self.assertRaises(ValueError): raw.validate(record)

    def test_legacy_request_and_record_remain_exactly_replayable(self):
        self.assertEqual(digest(raw.request(self.source, self.target)),
                         '5b4ff68f0ba4900d9fa8f4c52c47adb0d3f1e615e4ae1f7746068402b3457396')
        old = raw.bind(self.source, self.target, {'output': decision()})
        self.assertEqual(old['artifact_kind'], raw.VERSION)
        self.assertEqual(raw.validate(old), old)
        changed = deepcopy(old); changed['artifact_kind'] = raw.SOURCE_CONTEXT
        with self.assertRaises(ValueError): raw.validate(changed)

    def test_compact_pipeline_applies_whole_source_veto_before_route_calls(self):
        calls = []
        class Runner:
            def call(_, stage, request):
                calls.append((stage, request))
                if stage.startswith('source-context'):
                    return {'output': {'source_use': 'promotion_or_referral', 'reported_descriptors': []},
                            'raw': 'authored', 'errors': []}
                output = observation(); output['source_use'] = 'promotion_or_referral'
                return {'output': output, 'raw': 'authored', 'errors': []}
        work = PipelineWork(Runner(), lambda req: {'fits': True, 'request_sha256': digest(req)},
                            lambda *args: None, registry={'example': self.source},
                            membership_mode='raw', verification_contract='raw-membership-verification-20261026-v12',
                            schedule={}, extraction_protocol=compact_claims.INDEXED)
        batches = work.judge('membership', [{'source_id': 'example', 'candidate_id': self.target['id']}], [self.target])
        self.assertEqual(len(calls), 2)
        self.assertNotIn('CANDIDATE', calls[0][1]['data'])
        self.assertIn('source_use', calls[1][1]['schema']['properties'])
        self.assertNotEqual(batches[0]['memberships'][0]['relation'], 'supported')
        work.judge('other-stage', [{'source_id': 'example', 'candidate_id': self.target['id']}], [self.target])
        self.assertEqual(sum(stage.startswith('source-context') for stage, _ in calls), 1)
