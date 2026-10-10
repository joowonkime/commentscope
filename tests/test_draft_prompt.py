import json
import unittest

from commentscope import perspective_prompt_v2, perspective_prompt_v3
from commentscope.factory.perspective_drafts import draft, draft_prompt_for, inputs_for


class DraftPromptTests(unittest.TestCase):
    def test_v3_keeps_v2_inputs_schema_binding_and_approval_boundary(self):
        prepared = {'claims': [{'claim_id': 'c1', 'source_comment_id': 's1', 'claim': 'extracted', 'quote': 'Could help.'}],
                    'sources': {'s1': {'text': 'Could help.'}}}
        before = inputs_for(prepared, ['c1'], 'v2')
        after = inputs_for(prepared, ['c1'], 'v3')
        self.assertEqual(before, after)
        wire = {'assignments': {'M01': {'group_id': 'G1', 'exclusion_reason': None}},
                'groups': [{'group_id': 'G1', 'common': 'Could help.', 'details': []}]}
        calls = []
        def provider(system, payload, schema):
            calls.append((system, payload, schema))
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(wire)}}]}
        old = draft(*before, provider, revision='v2')
        new = draft(*after, provider, revision='v3')
        self.assertEqual(calls[0][0], perspective_prompt_v2.SYSTEM)
        self.assertEqual(calls[1][0], perspective_prompt_v3.SYSTEM)
        self.assertEqual(calls[0][1:], calls[1][1:])
        self.assertEqual(new['contract_errors'], [])
        self.assertEqual(old['canonical_output'], new['canonical_output'])
        self.assertEqual(new['bound_draft']['accepted_perspectives'], 0)
        self.assertEqual(new['bound_draft']['semantic_review_status'], 'pending')

    def test_unknown_revision_rejected(self):
        with self.assertRaises(ValueError): draft_prompt_for('v4')
        with self.assertRaises(ValueError): inputs_for({}, [], 'v4')
