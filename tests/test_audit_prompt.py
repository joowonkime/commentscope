import json
import unittest

from commentscope.factory.draft_audit import audit, audit_pairwise, prompt_for, attach_comparison, SYSTEM
from commentscope import audit_prompt_v2


class AuditPromptTests(unittest.TestCase):
    def test_prompt_revision_changes_only_system_in_requests(self):
        canonical = {'groups': [{'common': {'text': 'The plan could help.', 'evidence': [
            {'member_id': 'M01'}, {'member_id': 'M02'}]}, 'details': []}]}
        members = {'M01': {'target': 'The plan could help.'}, 'M02': {'target': 'The plan will help.'}}
        for runner in [audit, audit_pairwise]:
            calls = []
            def provider(system, payload, schema):
                calls.append((system, payload, schema))
                output = {key: {'verdict': 'supported', 'reason': 'synthetic'} for key in payload['pairs']}
                return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]}
            old = runner(canonical, members, provider)
            before = list(calls); calls.clear()
            new = runner(canonical, members, provider, prompt_revision='v2')
            self.assertEqual(len(calls), len(before))
            for previous, current in zip(before, calls):
                self.assertEqual(previous[0], SYSTEM)
                self.assertEqual(current[0], audit_prompt_v2.SYSTEM)
                self.assertEqual(previous[1:], current[1:])
            self.assertEqual(old['pairs'], new['pairs'])
            self.assertFalse(new['human_approved'])

    def test_unknown_revision_rejected_even_without_model_call(self):
        with self.assertRaises(ValueError): prompt_for('v3')
        with self.assertRaises(ValueError): audit_pairwise({'groups': []}, {}, prompt_revision='v3')

    def test_v2_lint_still_blocks_without_model(self):
        canonical = {'groups': [{'common': {'text': 'M01', 'evidence': [{'member_id': 'M01'}]}, 'details': []}]}
        result = audit_pairwise(canonical, {'M01': {'target': 'A claim.'}},
                                lambda *args: self.fail('Should be linted'), prompt_revision='v2')
        self.assertEqual(result['lint_blocked_pairs'], 1)
        self.assertEqual(result['model_calls'], 0)

    def test_comparison_records_metadata_differences(self):
        old = {'draft_sha256': 'a', 'results': [], 'prompt_sha256': 'old', 'model': 'same', 'audit_mode': 'pairwise'}
        new = {**old, 'prompt_sha256': 'new'}
        attach_comparison(new, old)
        self.assertEqual(new['comparison_metadata_changes'], {'prompt_sha256': {'previous': 'old', 'current': 'new'}})

    def test_render_does_not_mislabel_pairwise_baseline_as_batch(self):
        from commentscope.factory.draft_audit import render
        result = {'cluster_id': 'C1', 'recommendation': 'needs_human_review', 'errors': [],
                  'members': {'M01': {'target': 'Text.'}}, 'pairs': {'P01': {
                      'group': 1, 'statement_kind': 'common', 'text': 'Text.', 'member_id': 'M01'}},
                  'output': {}, 'previous_output': {}}
        page = render({'results': [result]})
        self.assertIn('이전 비교 검사', page)
        self.assertNotIn('이전 일괄 검사', page)
