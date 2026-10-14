from copy import deepcopy
import json
import tempfile
import unittest

from commentscope.factory.automatic import Calls
from commentscope.providers.schema_visible import SchemaVisibleCalls


class SchemaVisibleTests(unittest.TestCase):
    def test_visible_contract_without_moving_untrusted_data_or_mutation(self):
        seen = []
        schema = {'type': 'object', 'properties': {'status': {'enum': ['yes', 'no']}}}
        data = {'COMMENT': 'untrusted text'}
        original = deepcopy([data, schema])
        wrapped = SchemaVisibleCalls(lambda *args: seen.append(args), ['select'])
        wrapped('select', data, schema)
        system, got_data, got_schema = seen[0]
        self.assertEqual(json.loads(system.split('Required JSON output schema:\n')[1]), schema)
        self.assertNotIn('untrusted text', system)
        self.assertEqual([data, schema], original)
        self.assertEqual((got_data, got_schema), (data, schema))

    def test_other_stages_are_unchanged(self):
        seen = []
        SchemaVisibleCalls(lambda *args: seen.append(args), ['select'])('audit', {}, {})
        self.assertEqual(seen, [('audit', {}, {})])

    def test_effective_prompt_has_distinct_checkpoint_identity(self):
        seen = []
        def provider(system, data, schema):
            seen.append(system)
            return {'choices': [{'message': {'content': '{"status":"yes"}'}, 'finish_reason': 'stop'}]}
        with tempfile.TemporaryDirectory() as directory:
            calls = Calls(directory, {'expires_at': '2099-01-01T00:00:00Z'}, provider)
            visible = SchemaVisibleCalls(calls, ['select'])
            schema = {'type': 'object', 'properties': {'status': {'type': 'string'}}}
            calls('select', {}, schema)
            visible('select', {}, schema)
            visible('select', {}, schema)
            self.assertEqual(calls.new_calls, 2)
            self.assertEqual(len(seen), 2)
            self.assertNotEqual(seen[0], seen[1])
