"""First S1/S2 contract slice; scripted outputs are not model quality evidence."""
from copy import deepcopy
import unittest

from commentscope.factory import compact_claims as compact, source_interpretation as si
from commentscope.factory import source_semantics as semantics
from commentscope.factory.automatic_contract import digest
import test_source_semantic_review as legacy
from test_compact_unified_selections import row


def typed_declarations(count=1, *, kind='value', authorship='asserted'):
    value = legacy.declarations(count)
    for decision in value['decisions']:
        decision.update(kind=kind, authorship=authorship)
    return value


class SourceSemanticsContractTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'own', 'text': '임금이 유지되면 😀 도입에 찬성한다.',
                       'parent': {'id': 'parent', 'text': '도입에 찬성한다. 그 이유는 가족 때문이다.'}}
        self.extraction = legacy.extract(self.source, [row(conditions=('S000',))])
        self.proposals = [c['source_interpretation'] for c in self.extraction['claims']]
        self.snapshot_sha = digest({'synthetic_scope': self.source})

    def review(self, value=None):
        return si.bind_review(self.proposals, {'output': value or typed_declarations()},
                              protocol=si.TYPED_REVIEW)

    def bound(self, reviews=None):
        return semantics.bind(self.extraction, [self.review()] if reviews is None else reviews,
                              snapshot_sha256=self.snapshot_sha)

    def test_typed_review_observes_kind_and_authorship_without_changing_s1(self):
        before = deepcopy(self.extraction)
        request = si.review_request(self.proposals, protocol=si.TYPED_REVIEW)
        props = request['schema']['properties']['decisions']['items']['properties']
        self.assertEqual(props['kind']['enum'], ['fact', 'value', 'prediction', 'uncertain'])
        self.assertEqual(props['authorship']['enum'], list(si.mc.AUTHORSHIP))
        self.assertEqual(request['data']['REVIEW_CONTRACT'], si.TYPED_REVIEW)
        for kind in ('fact', 'value', 'prediction', 'uncertain'):
            review = self.review(typed_declarations(kind=kind))
            self.assertEqual(review['decisions'][0]['declaration']['kind'], kind)
            self.assertFalse(review['factual_verification'])
        self.assertEqual(self.extraction, before)

    def test_legacy_review_remains_explicit_and_has_no_added_fields(self):
        request = si.review_request(self.proposals)
        self.assertEqual(request, si.review_request(self.proposals, protocol=si.REVIEW))
        props = request['schema']['properties']['decisions']['items']['properties']
        self.assertNotIn('kind', props)
        self.assertNotIn('authorship', props)
        self.assertNotIn('REVIEW_CONTRACT', request['data'])
        review = si.bind_review(self.proposals, {'output': legacy.declarations()})
        self.assertEqual(review['artifact_kind'], si.REVIEW)
        self.assertEqual(si.validate_review(review), review)

    def test_record_binds_actual_source_snapshot_requests_and_unicode_spans(self):
        result = self.bound()
        self.assertEqual(result['schema_version'], 'factory-semantics-0.1')
        self.assertEqual(result['snapshot_sha256'], self.snapshot_sha)
        self.assertEqual(result['source_sha256'], digest(self.source))
        self.assertEqual(result['request_sha256'], self.extraction['request_sha256'])
        body = {k: v for k, v in result.items() if k != 'record_sha256'}
        self.assertEqual(result['record_sha256'], digest(body))
        span = result['extraction']['claims'][0]['essential_conditions'][0]
        self.assertEqual(span['text'], self.source['text'][span['start']:span['end']])
        self.assertEqual(semantics.validate(result, snapshot_sha256=self.snapshot_sha,
                                             source=self.source), result)
        self.assertTrue(result['decisions'][0]['nomination_eligible'])
        for key in ('semantic_approval', 'support_approved', 'factual_verification'):
            self.assertIs(result[key], False)

    def test_current_scope_and_mutated_source_review_span_or_flags_are_rejected(self):
        record = self.bound()
        with self.assertRaises(ValueError):
            semantics.validate(record, snapshot_sha256='0' * 64, source=self.source)
        with self.assertRaises(ValueError):
            semantics.validate(record, snapshot_sha256=self.snapshot_sha,
                               source={**self.source, 'parent': None})
        for mutate in (
            lambda r: r['source']['parent'].update(text='Changed.'),
            lambda r: r['extraction']['claims'][0]['essential_conditions'].clear(),
            lambda r: r['reviews'][0]['decisions'][0]['declaration'].update(kind='fact'),
            lambda r: r['decisions'][0].update(nomination_eligible=False),
            lambda r: r.update(support_approved=True),
            lambda r: r.update(record_sha256='0' * 64),
        ):
            changed = deepcopy(record); mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                semantics.validate(changed, snapshot_sha256=self.snapshot_sha, source=self.source)

    def test_independent_reported_or_unclear_authorship_blocks_nomination(self):
        for authorship in ('reported', 'uncertain'):
            result = self.bound([self.review(typed_declarations(authorship=authorship))])
            self.assertFalse(result['decisions'][0]['nomination_eligible'])
            self.assertIn('review_not_own_nomination', result['decisions'][0]['holds'])
            self.assertEqual(result['extraction'], self.extraction)

    def test_record_hash_covers_json_types_not_python_false_zero_equality(self):
        record = self.bound()
        record['support_approved'] = 0
        with self.assertRaises(ValueError):
            semantics.validate(record, snapshot_sha256=self.snapshot_sha, source=self.source)

    def test_missing_and_untyped_reviews_never_fill_independent_observations(self):
        held = self.bound([])
        self.assertEqual(held['reviews'], [])
        self.assertEqual(held['decisions'][0]['holds'], ['semantic_review_missing'])
        self.assertEqual(held['source'], self.source)
        old = si.bind_review(self.proposals, {'output': legacy.declarations()})
        with self.assertRaises(ValueError): self.bound([old])

    def test_missing_unknown_and_duplicate_fields_or_reviews_fail_without_repair(self):
        variants = []
        for field in ('kind', 'authorship'):
            bad = typed_declarations(); bad['decisions'][0].pop(field); variants.append(bad)
            bad = typed_declarations(); bad['decisions'][0][field] = 'invented'; variants.append(bad)
        bad = typed_declarations(); bad['decisions'] *= 2; variants.append(bad)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError): self.review(value)
        review = self.review()
        with self.assertRaises(ValueError): self.bound([review, review])
        with self.assertRaises(ValueError):
            semantics.bind(self.extraction, [], snapshot_sha256='unbound')

    def test_parent_can_resolve_reference_but_not_become_own_reason(self):
        value = typed_declarations(); decision = value['decisions'][0]
        decision.update(reference_use='resolved', references=[
            {'expression_id': 'S000', 'antecedent_ids': ['P000']}])
        review = self.review(value)
        self.assertEqual(review['decisions'][0]['references'][0]['antecedents'][0]['origin'],
                         'parent_reference_only')
        decision['scope_links'] = [{'kind': 'reason', 'segment_ids': ['P000']}]
        with self.assertRaises(ValueError): self.review(value)

    def test_collect_preserves_empty_reported_and_missing_review_sources(self):
        empty = legacy.extract({**self.source, 'id': 'empty'}, [])
        reported = legacy.extract({**self.source, 'id': 'reported'}, [row(author='reported')])
        records = semantics.collect([self.extraction, empty, reported], [],
                                    snapshot_sha256=self.snapshot_sha)
        self.assertEqual({r['source']['id'] for r in records}, {'own', 'empty', 'reported'})
        self.assertTrue(all(not d['nomination_eligible'] for r in records for d in r['decisions']))
        self.assertEqual(next(r for r in records if r['source']['id'] == 'empty')['completion'],
                         'unresolved')
        with self.assertRaises(ValueError):
            semantics.collect([self.extraction, self.extraction], [], snapshot_sha256=self.snapshot_sha)
        with self.assertRaises(ValueError):
            semantics.collect([empty], [self.review()], snapshot_sha256=self.snapshot_sha)

    def test_continuation_and_bounded_reviews_retain_both_request_lineages(self):
        source = {'id': 'long', 'text': ' '.join(f'Preserve option {i}.' for i in range(17)),
                  'parent': None}
        first = legacy.extract(source, [row(evidence=(f'S{i:03}',)) for i in range(16)], more=True)
        final = legacy.extract(source, [row(evidence=('S016',))], previous=first)
        tasks = si.review_tasks([final])
        self.assertEqual([len(t['interpretations']) for t in tasks], [8, 8, 1])
        reviews = [si.bind_review(t['interpretations'],
                    {'output': typed_declarations(len(t['interpretations']))},
                    protocol=si.TYPED_REVIEW) for t in tasks]
        bound = semantics.bind(final, reviews, snapshot_sha256=self.snapshot_sha)
        self.assertEqual(len(bound['decisions']), 17)
        self.assertEqual(bound['request_sha256'], final['request_sha256'])
        self.assertEqual(bound['extraction']['previous'], first)
        self.assertEqual(set(bound['review_request_sha256s']), {r['request_sha256'] for r in reviews})
        self.assertEqual(bound, semantics.bind(final, reviews[::-1], snapshot_sha256=self.snapshot_sha))
        missing = semantics.bind(final, reviews[:-1], snapshot_sha256=self.snapshot_sha)
        self.assertEqual(sum(d['holds'] == ['semantic_review_missing'] for d in missing['decisions']), 1)
        self.assertEqual(len(missing['extraction']['claims']), 17)


class SourceSemanticsPipelineTests(unittest.TestCase):
    def fixture(self, *, malformed=False, reported=False, missing_source=False):
        helper = legacy.SemanticReviewPipelineTests()
        fixture, base = helper.fixture()
        self.addCleanup(helper.doCleanups)

        class Runner:
            calls = base.calls

            def __init__(self):
                self.missing_source = missing_source

            def call(self, stage, request):
                if self.missing_source and request['system'].startswith(compact.PREFIX):
                    self.calls.append((stage, request))
                    self.missing_source = False
                    return {'output': {}}
                if request['data'].get('REVIEW_CONTRACT') == si.TYPED_REVIEW:
                    self.calls.append((stage, request))
                    value = typed_declarations(len(request['data']['PROPOSALS']))
                    for decision, proposal in zip(value['decisions'], request['data']['PROPOSALS']):
                        decision['speech_act'] = 'request'
                        if reported and proposal['text'] == 'Adopt P.':
                            decision['authorship'] = 'reported'
                        if malformed: decision.pop('kind')
                    return {'output': value}
                return base.call(stage, request)

        return fixture, Runner()

    def process(self, fixture, runner):
        return fixture.process(runner, extraction_protocol=compact.TRACED_PROPOSALS,
                               review_interpretations=True, source_review_protocol=si.TYPED_REVIEW)

    def test_opt_in_adapter_reaches_two_agents_six_answers_and_keeps_support_checks(self):
        from experiments.framed_agent_probe import runtime_probe
        from commentscope.factory import minimal_pipeline
        fixture, runner = self.fixture()
        result = self.process(fixture, runner)
        self.assertFalse(result['errors'])
        self.assertEqual(result['artifact_kind'], minimal_pipeline.SOURCE_SEMANTICS_VERSION)
        self.assertEqual(len(result['source_records']), 6)
        self.assertEqual(result['source_review_protocol'], si.TYPED_REVIEW)
        self.assertEqual(fixture.saved['source-records'], result['source_records'])
        from commentscope.factory.framed_corpus import sources
        current = sources(fixture.snapshot, include_video_context=True)
        for record in result['source_records']:
            semantics.validate(record, snapshot_sha256=digest(fixture.snapshot.to_dict()),
                               source=current[record['source']['id']])
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 2)
        self.assertEqual(len(runtime_probe(result['agent_inputs']['bundle'], runner)['turns']), 6)
        self.assertTrue(result['nomination_batches'])
        self.assertTrue(result['memberships'])
        self.assertTrue(result['audits'])
        self.assertFalse(result['quality_gate_passed'])
        self.assertFalse(result['runtime_reference_labels'])
        self.assertEqual(len([q for _,q in runner.calls if q['data'].get('REVIEW_CONTRACT') == si.TYPED_REVIEW]), 6)

    def test_malformed_typed_review_is_held_once_without_unreviewed_nomination(self):
        fixture, runner = self.fixture(malformed=True)
        result = self.process(fixture, runner)
        self.assertEqual(len(result['errors']), 6)
        self.assertEqual(len(result['source_records']), 6)
        self.assertFalse(result['candidates'])
        self.assertTrue(all(d['holds'] == ['semantic_review_missing']
                            for r in result['source_records'] for d in r['decisions']))
        self.assertEqual(len([q for _,q in runner.calls if q['data'].get('REVIEW_CONTRACT') == si.TYPED_REVIEW]), 6)

    def test_one_reviewed_position_cannot_erase_the_other_sources(self):
        fixture, runner = self.fixture(reported=True)
        result = self.process(fixture, runner)
        self.assertEqual(len(result['source_records']), 6)
        self.assertEqual(len(result['agent_inputs']['compiled']['profiles']), 1)
        self.assertNotIn('Adopt P.', [c['text'] for c in result['candidates']])
        self.assertEqual(len([d for r in result['source_records'] for d in r['decisions']
                              if 'review_not_own_nomination' in d['holds']]), 3)

    def test_failed_s1_keeps_full_processing_scope_without_fabricating_a_record(self):
        fixture, runner = self.fixture(missing_source=True)
        result = self.process(fixture, runner)
        self.assertEqual(result['canonical_population'], 6)
        self.assertEqual(len(result['processing_ids']), 6)
        self.assertEqual(len(result['unextracted_source_ids']), 1)
        self.assertEqual(len(result['source_records']), 5)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(len([q for _,q in runner.calls if q['system'].startswith(compact.PREFIX)]), 6)
        exported = {r['source']['id'] for r in result['source_records']}
        self.assertFalse(exported.intersection(result['unextracted_source_ids']))
        self.assertEqual(exported | set(result['unextracted_source_ids']), set(result['processing_ids']))

    def test_wrong_protocol_is_rejected_before_dispatch_and_legacy_does_not_export_records(self):
        fixture, runner = self.fixture()
        for kwargs in ({'source_review_protocol': si.TYPED_REVIEW},
                       {'source_review_protocol': 'unknown', 'review_interpretations': True,
                        'extraction_protocol': compact.TRACED_PROPOSALS}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                fixture.process(runner, **kwargs)
        self.assertEqual(runner.calls, [])
        result = fixture.process(runner, extraction_protocol=compact.TRACED_PROPOSALS,
                                 review_interpretations=True)
        self.assertNotIn('source_records', result)
        self.assertNotIn('source_review_protocol', result)


if __name__ == '__main__':
    unittest.main()
