import json
import unittest
from urllib.error import URLError

from commentscope.factory.draft_audit import audit_pairwise, statement_lint, attach_comparison, render, SYSTEM


class PairwiseAuditTests(unittest.TestCase):
    def members(self):
        return {'M01': {'target': 'Policy will happen.'}, 'M02': {'target': 'Policy could help.'}}

    def canonical(self):
        return {'groups': [{'common': {'text': 'Policy could help.', 'evidence': [
            {'member_id': 'M01'}, {'member_id': 'M02'}]}, 'details': []}], 'excluded': []}

    def supported(self, system, payload, schema):
        output = {key: {'verdict': 'supported', 'reason': 'test response'} for key in payload['pairs']}
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]}

    def test_each_request_contains_only_one_pair_and_one_target(self):
        calls = []
        def provider(system, payload, schema):
            calls.append(payload)
            self.assertEqual(system, SYSTEM)
            self.assertEqual(len(payload['pairs']), 1)
            self.assertEqual(len(payload['targets']), 1)
            pair = next(iter(payload['pairs'].values()))
            self.assertEqual(list(payload['targets']), [pair['member_id']])
            self.assertNotIn('previous_output', payload)
            self.assertEqual(set(schema['properties']), set(payload['pairs']))
            return self.supported(system, payload, schema)
        result = audit_pairwise(self.canonical(), self.members(), provider)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['model_calls'], 2)
        self.assertEqual(result['recommendation'], 'needs_human_review')
        self.assertFalse(result['human_approved'])

    def test_id_only_placeholder_never_calls_provider(self):
        canonical = self.canonical(); canonical['groups'][0]['common']['text'] = '`[M01, M02]`'
        def forbidden(*args): self.fail('Lint must run before model call')
        result = audit_pairwise(canonical, self.members(), forbidden)
        self.assertEqual(result['lint_blocked_pairs'], 2)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['recommendation'], 'revise_before_human_approval')
        self.assertTrue(all(r['verdict_origin'] == 'deterministic_lint' for r in result['pair_results'].values()))

    def test_lint_does_not_reject_meaningful_short_or_id_containing_sentence(self):
        for text in ['AI helps.', 'M01 predicts adoption.', 'No.', 'We need UBI.']:
            self.assertEqual(statement_lint(text), [])
        for text in ['M01', 'M999.', '(M01)', 'M01 M02']:
            self.assertEqual(statement_lint(text), ['id_only_placeholder'])

    def test_failure_is_preserved_and_other_pair_continues(self):
        calls = []
        def provider(system, payload, schema):
            calls.append(payload)
            if len(calls) == 1: raise URLError('offline')
            return self.supported(system, payload, schema)
        result = audit_pairwise(self.canonical(), self.members(), provider)
        self.assertEqual(result['recommendation'], 'audit_failed')
        self.assertIn('P01:transport_error', result['errors'])
        self.assertNotIn('P01', result['output'])
        self.assertIn('P02', result['output'])

    def test_callback_preserves_each_pair_with_raw_output(self):
        seen = []
        audit_pairwise(self.canonical(), self.members(), self.supported, lambda key, result: seen.append((key, result)))
        self.assertEqual([key for key, _ in seen], ['P01', 'P02'])
        self.assertTrue(all(r['raw'] for _, r in seen))

    def test_empty_draft_no_model_call(self):
        result = audit_pairwise({'groups': []}, {}, lambda *args: self.fail('No pairs'))
        self.assertEqual(result['recommendation'], 'no_drafts')
        self.assertEqual(result['model_calls'], 0)

    def test_comparison_rejects_different_draft_or_pairs(self):
        report = {'draft_sha256': 'a', 'results': [{'cluster_id': 'C1', 'pairs': {}}]}
        old = {'draft_sha256': 'b', 'results': []}
        with self.assertRaises(ValueError): attach_comparison(report, old)
        old = {'draft_sha256': 'a', 'results': [{'cluster_id': 'C1', 'pairs': {'P1': 'changed'}, 'errors': [], 'output': {}}]}
        with self.assertRaises(ValueError): attach_comparison(report, old)

    def test_comparison_keeps_old_and_new_separate(self):
        result = audit_pairwise(self.canonical(), self.members(), self.supported)
        report = {'draft_sha256': 'a', 'results': [{'cluster_id': 'C1', **result}]}
        old_output = {key: {'verdict': 'partial', 'reason': 'old result'} for key in result['pairs']}
        old = {'draft_sha256': 'a', 'results': [{'cluster_id': 'C1', 'pairs': result['pairs'], 'errors': [], 'output': old_output}]}
        attach_comparison(report, old)
        self.assertEqual(report['results'][0]['previous_output'], old_output)
        self.assertEqual(report['results'][0]['output']['P01']['verdict'], 'supported')

    def test_comparison_rejects_missing_verdicts(self):
        result = audit_pairwise(self.canonical(), self.members(), self.supported)
        report = {'draft_sha256': 'a', 'results': [{'cluster_id': 'C1', **result}]}
        old = {'draft_sha256': 'a', 'results': [{'cluster_id': 'C1', 'pairs': result['pairs'], 'errors': [], 'output': {}}]}
        with self.assertRaises(ValueError): attach_comparison(report, old)

    def test_render_escapes_comparison_and_shows_origin(self):
        members = self.members(); members['M01']['target'] = '<script>source</script>'
        result = audit_pairwise(self.canonical(), members, self.supported)
        result['previous_output'] = {'P01': {'verdict': 'partial', 'reason': '<script>old</script>'}}
        page = render({'results': [{'cluster_id': 'C1', 'members': members, **result}]})
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('local_model', page)
