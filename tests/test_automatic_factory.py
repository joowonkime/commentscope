from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError

from commentscope.agents.runtime import AgentSession
from commentscope.factory.automatic import (Config, run, build_bundle, load_bundle, bind_claims,
    neighbors, group_claims, checked_call, Calls)
from commentscope.factory.automatic_contract import (EXTRACT, GATE, CHECKS, segments, extraction_schema,
    validate_extraction, validate_gate, passed, digest)
from commentscope.factory.automatic_cli import render
from commentscope.ingestion import load_snapshot
from commentscope.storage import write_json_exclusive


def response(output, finish='stop'):
    return {'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(output)}}]}


def supported():
    return {**{key: 'supported' for key in CHECKS}, 'reason': 'Synthetic test support'}


def extraction(statement='Safety reviews should be mandatory.', mode='normative', ids=None):
    return {'status': 'claims', 'claims': [{'statement': statement, 'mode': mode, 'segment_ids': ids or ['S000']}]}


class AutomaticContractTests(unittest.TestCase):
    def test_spans_cover_exact_multilingual_text(self):
        for text in ['Hi! Next.\n마지막 문장。', 'single long clause', 'a\n\nb', 'שלום? 끝!']:
            parts = segments(text)
            self.assertEqual(''.join(p['text'] for p in parts), text)
            for part in parts:
                self.assertEqual(text[part['start']:part['end']], part['text'])

    def test_multiple_claims_can_share_source_but_not_duplicate_claim(self):
        parts = segments('Need reviews. Fees should be waived.')
        value = extraction()
        value['claims'].append(extraction('Waive fees.', ids=['S001'])['claims'][0])
        self.assertEqual(validate_extraction(value, parts), [])
        value['claims'].append(deepcopy(value['claims'][0]))
        self.assertIn('duplicate_claim', validate_extraction(value, parts))

    def test_forged_span_and_status_rejected(self):
        parts = segments('A claim.')
        for value in [None, [], {}, extraction(ids=['S999']), extraction(ids=['S000', 'S000']),
                      {**extraction(), 'status': 'non_substantive'}, extraction(mode=[]),
                      {'status': 'claims', 'claims': []}, {'status': 'uncertain', 'claims': [None]}]:
            self.assertTrue(validate_extraction(value, parts))

    def test_schema_stop_cannot_hide_statement_length_boundary(self):
        self.assertEqual(validate_extraction(extraction(statement='x'*300), segments('A claim.')),
                         ['statement_at_length_limit'])

    def test_every_gate_check_is_required(self):
        self.assertTrue(passed({'output': supported(), 'errors': []}))
        for key in CHECKS:
            for status in ['unsupported', 'unclear', None, []]:
                value = {**supported(), key: status}
                self.assertFalse(passed({'output': value, 'errors': []}))
        self.assertFalse(passed({'output': supported(), 'errors': ['incomplete_generation']}))
        self.assertTrue(validate_gate({**supported(), 'reason': ''}))

    def test_config_limits(self):
        for kwargs in [{'limit': 1001}, {'limit': True}, {'neighbors': 1}, {'min_similarity': float('nan')},
                       {'max_gate_calls': 0}, {'max_source_chars': 100000}]:
            with self.assertRaises(ValueError):
                Config(**kwargs).validate()

    def test_one_format_repair_but_no_semantic_retry(self):
        calls = []
        def invalid(*args):
            calls.append(args)
            return {'output': {}, 'errors': []}
        result = checked_call(invalid, 's', {}, {}, validate_gate)
        self.assertEqual(len(calls), 2)
        self.assertTrue(result['errors'])
        calls.clear()
        def uncertain(*args):
            calls.append(args)
            return {'output': {**supported(), 'compatible': 'unclear'}, 'errors': []}
        self.assertFalse(passed(checked_call(uncertain, 's', {}, {}, validate_gate)))
        self.assertEqual(len(calls), 1)


class AutomaticPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        value = json.loads(Path('tests/fixtures/synthetic-snapshot.json').read_text())
        value['usage']['expires_at'] = '2099-01-01T00:00:00Z'
        value['comments'] = value['comments'][:3]
        for i, source in enumerate(value['comments']):
            source['text_original'] = ['Safety reviews should be mandatory. Fee waivers are another issue.',
                                       'We should require safety reviews.', 'Require safety reviews to prevent harm.'][i]
        self.snapshot = self.root / 'snapshot.json'
        write_json_exclusive(self.snapshot, value)
        self.raw = value
        self.calls = []

    def provider(self, system, data, schema):
        self.calls.append((system, data, schema))
        if system == EXTRACT:
            return response(extraction())
        if system == GATE:
            return response(supported())
        raise AssertionError('Unexpected request')

    def factory(self, **kwargs):
        return run(self.snapshot, self.root/'run', kwargs.pop('config', Config()),
                   provider=kwargs.pop('provider', self.provider), embedder=lambda texts: [[1, 0] for _ in texts], **kwargs)

    def test_end_to_end_no_review_file_and_replay(self):
        report = self.factory()
        bundle = build_bundle(self.snapshot, report)
        self.assertEqual(len(bundle['agents']), 1)
        self.assertFalse(bundle['human_handling'])
        self.assertEqual(report['summary']['covered_unique_sources'], 3)
        self.assertEqual(report['summary']['coverage_of_selected'], 1)
        self.assertEqual(len(self.calls), 6)
        self.assertTrue(all(system in [EXTRACT, GATE] for system, _, _ in self.calls))
        before = len(self.calls)
        self.assertEqual(report, self.factory())
        self.assertEqual(len(self.calls), before)
        write_json_exclusive(self.root/'report.json', report)
        write_json_exclusive(self.root/'bundle.json', bundle)
        self.assertEqual(load_bundle(self.snapshot, self.root/'report.json', self.root/'bundle.json'), bundle)
        self.assertIn('수동 검수 입력 없이', render(report, bundle))

    def test_reject_all_is_explicit_zero_coverage_not_success(self):
        def provider(system, data, schema):
            return response(extraction() if system == EXTRACT else {**supported(), 'core_supported': 'unsupported'})
        report = self.factory(provider=provider)
        self.assertEqual(report['summary']['coverage_of_selected'], 0)
        self.assertEqual(build_bundle(self.snapshot, report)['agents'], [])
        self.assertEqual(len(report['unresolved']), 3)

    def test_no_substantive_and_transport_errors_preserved(self):
        for kind in ['empty', 'transport']:
            with self.subTest(kind=kind):
                def provider(*args):
                    if kind == 'transport': raise URLError('offline')
                    return response({'status': 'non_substantive', 'claims': []})
                report = run(self.snapshot, self.root/kind, provider=provider, embedder=lambda texts: [])
                self.assertEqual(report['summary']['claims'], 0)
                self.assertEqual(len(report['records']), 3)
                self.assertEqual(build_bundle(self.snapshot, report)['agents'], [])

    def test_gate_budget_never_auto_accepts_unchecked_member(self):
        report = self.factory(config=Config(max_gate_calls=2))
        self.assertEqual(report['summary']['gate_decisions'], 2)
        self.assertTrue(report['summary']['gate_budget_exhausted'])
        self.assertEqual(build_bundle(self.snapshot, report)['agents'], [])

    def test_duplicate_alias_does_not_count_as_third_source(self):
        self.raw['comments'][2]['text_original'] = self.raw['comments'][1]['text_original']
        path = self.root/'duplicate.json'; write_json_exclusive(path, self.raw)
        report = run(path, self.root/'dup-run', provider=self.provider, embedder=lambda texts: [[1,0] for _ in texts])
        self.assertEqual(report['summary']['duplicate_aliases'], 1)
        self.assertEqual(report['summary']['auto_agents'], 0)
        self.assertEqual(len(report['source_disposition']), 3)

    def test_limit_and_long_sources_not_silently_removed(self):
        report = self.factory(config=Config(limit=1))
        self.assertEqual(sum(r['status']=='not_selected' for r in report['source_disposition']), 2)
        self.raw['comments'][0]['text_original'] = 'x'*4001
        path = self.root/'long.json'; write_json_exclusive(path, self.raw)
        report = run(path, self.root/'long-run', provider=self.provider, embedder=lambda texts: [[1,0] for _ in texts])
        self.assertEqual(report['summary']['source_statuses']['context_budget_exceeded'], 1)

    def test_source_or_report_mutation_rejected(self):
        report = self.factory()
        for mutate in [lambda r: r['units'][0]['spans'][0].update(text='forged'),
                       lambda r: r['groups'][0].update(common_claim='invented'),
                       lambda r: r['gates'].pop(),
                       lambda r: r['groups'][0]['member_ids'].pop(),
                       lambda r: r.update(human_handling=True),
                       lambda r: r['summary'].update(coverage_of_canonical=0),
                       lambda r: r['source_disposition'].pop(),
                       lambda r: r['records'][0].update(status='uncertain'),
                       lambda r: r['candidates'].update(foreign=[])]:
            bad = deepcopy(report); mutate(bad)
            with self.assertRaises(ValueError): build_bundle(self.snapshot, bad)
        changed = self.root/'changed.json'
        self.raw['comments'][0]['text_original'] += 'changed'
        write_json_exclusive(changed, self.raw)
        with self.assertRaises(ValueError): build_bundle(changed, report)

    def test_expired_snapshot_and_changed_resume_config_rejected(self):
        self.factory()
        with self.assertRaises(ValueError): self.factory(config=Config(limit=2))
        self.raw['usage']['expires_at'] = '2000-01-01T00:00:00Z'
        path = self.root/'expired.json'; write_json_exclusive(path, self.raw)
        with self.assertRaises(ValueError): run(path, self.root/'expired-run')

    def test_modes_not_merged_and_invalid_vectors_rejected(self):
        source = load_snapshot(self.snapshot).snapshot.comments[0]
        units = bind_claims(source, extraction())
        units += [{**deepcopy(units[0]), 'claim_id': 'other', 'source_comment_id': 'other', 'mode': 'prediction'}]
        self.assertTrue(all(not v for v in neighbors(units, [[1,0], [1,0]], Config()).values()))
        for vectors in [[], [[0,0], [1,0]], [[float('nan'),0], [1,0]], [[1], [1,0]]]:
            with self.assertRaises(ValueError): neighbors(units, vectors, Config())

    def test_nontransitive_chain_cannot_create_group_without_direct_support(self):
        report = self.factory()
        units = report['units']
        # A--B--C is not a three-source common claim: every anchor has only one supported peer.
        links = {u['claim_id']: [{'claim_id': v['claim_id'], 'cosine': 1.0}
                                for v in units if v != u] for u in units}
        ids = [u['claim_id'] for u in units]
        def judge(a, b):
            decision = supported()
            if a != b and (ids.index(a['claim_id']) + 1) % 3 != ids.index(b['claim_id']):
                decision['core_supported'] = 'unsupported'
            return {'output': decision, 'errors': []}
        groups, gates, unresolved, hit = group_claims(units, links, {}, Config(), judge)
        self.assertEqual(groups, [])
        self.assertEqual(len(unresolved), 3)

    def test_empty_auto_bundle_ui_cannot_submit_question(self):
        from commentscope.agents.web import ComparisonApp, WebError
        report = self.factory(config=Config(limit=1))
        bundle = build_bundle(self.snapshot, report)
        app = ComparisonApp(bundle, 'test', self.root/'sessions', {})
        state = app.create()
        self.assertFalse(state['can_ask'])
        with self.assertRaises(WebError) as exc:
            app.ask(state['token'], 'question', 'r1')
        self.assertEqual(exc.exception.code, 'no_agents')

    def test_auto_profile_works_in_existing_web_and_export(self):
        from commentscope.agents.web import ComparisonApp
        from commentscope.agents.demo import render as render_comparison
        report = self.factory()
        bundle = build_bundle(self.snapshot, report)
        app = ComparisonApp(bundle, 'test', self.root/'sessions', {})
        state = app.create()
        self.assertTrue(state['can_ask'])
        self.assertFalse(state['bundle']['human_handling'])
        rendered = render_comparison(app._report())
        self.assertIn('수동 검수 입력 없이 자동 생성', rendered)
        self.assertIn('자동 추출 주장', rendered)
        self.assertNotIn('검수자 해석', rendered)

    def test_runtime_receives_only_assigned_spans_and_audits_scope(self):
        bundle = build_bundle(self.snapshot, self.factory())
        profile = bundle['agents'][0]
        evidence_id = profile['evidence'][0]['evidence_id']
        calls = []
        def provider(system, data, schema):
            calls.append((system, data))
            if 'POINT' in data:
                return response({'verdict': 'supported', 'reason': 'synthetic'})
            return response({'answerability': 'grounded', 'points': [{'text': 'Safety reviews are needed.', 'evidence_id': evidence_id}], 'missing_information': ''})
        turn = AgentSession(profile, provider).ask('What do you claim?')
        self.assertEqual(turn['status'], 'model_audit_passed_development_only')
        self.assertNotIn('Fee waivers', json.dumps(calls[0][1]['YOUR_EVIDENCE']))
        self.assertIn('ALLOWED_CLAIM', calls[1][1])
        self.assertIn('ALLOWED_CLAIM', calls[1][0])
        bad = deepcopy(profile); bad['evidence'][0]['support_spans'][0]['text'] = 'forged'
        with self.assertRaises(ValueError): AgentSession(bad, provider)


if __name__ == '__main__':
    unittest.main()
