"""Offline contract failures across stages, without a model or source corpus."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.contracts.perspective_draft import obj, array
from commentscope.contracts.structured_output import inspect_schema, check_output
from commentscope.factory.automatic_contract import digest
from tools.audit_factory_contracts import audit_runs


class StructuredOutputAuditTests(unittest.TestCase):
    def test_nested_limits_and_schema_paths_without_exposing_values(self):
        schema = obj({'rows': array(obj({'basis': {'type': 'string', 'maxLength': 4}}), maximum=1)})
        result = check_output(schema, {'rows': [{'basis': 'PRIVATE-SENTENCE'}, {'basis': 'x'}]})
        self.assertTrue(result['checked'])
        self.assertEqual({e['keyword'] for e in result['errors']}, {'maxLength', 'maxItems'})
        self.assertNotIn('PRIVATE-SENTENCE', json.dumps(result))

    def test_anyof_checks_sibling_constraints_and_exact_object_fields(self):
        schema = {**obj({'state': {'type': 'string', 'enum': ['ok']}}),
                  'anyOf': [{'properties': {'state': {'const': 'ok'}}}, {'type': 'null'}]}
        self.assertEqual(check_output(schema, {'state': 'ok'})['errors'], [])
        for value in ({'state': 'other'}, {'state': 'ok', 'foreign': 1}, {}):
            self.assertTrue(check_output(schema, value)['errors'])

    def test_boolean_does_not_equal_integer_enum_or_const(self):
        for schema in ({'enum': [1]}, {'const': 1}, {'type': 'integer'}):
            self.assertTrue(check_output(schema, True)['errors'])
        self.assertFalse(check_output({'type': 'boolean'}, True)['errors'])

    def test_uniqueness_patterns_and_unicode_length(self):
        schema = array({'type': 'string', 'pattern': '^[01]+$', 'minLength': 2}, maximum=3)
        schema['uniqueItems'] = True
        result = check_output(schema, ['10', '10', 'x'])
        self.assertEqual({e['keyword'] for e in result['errors']}, {'uniqueItems', 'pattern', 'minLength'})
        self.assertFalse(check_output({'type': 'string', 'maxLength': 2}, '한글')['errors'])

    def test_unsupported_or_malformed_schemas_never_claim_a_complete_check(self):
        for schema in ({'allOf': [{}]}, {'type': 'string', 'maxLength': -1},
                       {'type': 'array', 'minItems': 3, 'maxItems': 2},
                       {'enum': []}, {'type': 'string', 'pattern': '['}):
            with self.subTest(schema=schema):
                self.assertFalse(inspect_schema(schema)['supported'])
                self.assertFalse(check_output(schema, 'anything')['checked'])

    def test_audit_lists_host_obligations_without_claiming_provider_enforcement(self):
        schema = obj({'anchor': {'type': 'string'},
                      'basis': {'type': 'string', 'maxLength': 240}})
        inspected = inspect_schema(schema)
        self.assertTrue(inspected['supported'])
        self.assertEqual({o['kind'] for o in inspected['obligations']},
                         {'free_text', 'string_length'})
        self.assertFalse(inspected['semantic_approval'])

    def make_run(self, root, name, stage, schema, output, *, binder_error=False, errors=()):
        run = root/name
        calls = run/'calls'; calls.mkdir(parents=True)
        request = {'system': 'Untrusted ORIGINALS', 'data': {'text': 'PRIVATE-ORIGINAL'},
                   'schema': schema, 'max_tokens': 128}
        request_sha = digest(request)
        prefix = '0001-'+stage+'-'+request_sha[:20]
        result = {'raw': json.dumps(output), 'output': output, 'errors': list(errors)}
        request_path = calls/(prefix+'.request.json')
        request_path.write_text(json.dumps({'request': request, 'request_sha256': request_sha}))
        (calls/(prefix+'.result.json')).write_text(json.dumps(result))
        if binder_error:
            directory = run/'artifacts'/'errors'; directory.mkdir(parents=True)
            (directory/(stage+'.json')).write_text(json.dumps({'stage': stage,
                'request_sha256': request_sha, 'exception': 'ValueError',
                'message': 'PRIVATE-BINDER-DIAGNOSTIC', 'result': result, 'items': []}))
        return run, request_path

    def test_recorded_failures_distinguish_schema_binder_and_generation_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, _ = self.make_run(root, 'a', 'candidate-world', obj({'anchor': {'type': 'string'}}),
                                 {'anchor': 'x'*175}, binder_error=True)
            b, _ = self.make_run(root, 'b', 'argument-audit', obj({'basis': {'type': 'string', 'maxLength': 4}}),
                                 {'basis': 'too long'}, binder_error=True)
            c, _ = self.make_run(root, 'c', 'extract', obj({'c': array({'type': 'string'})}),
                                 None, binder_error=True, errors=['incomplete_generation'])
            with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')):
                report = audit_runs([a, b, c])
            self.assertEqual(report['counts']['requests'], 3)
            self.assertEqual(report['counts']['binding_failures'], 3)
            self.assertEqual({f['classification'] for f in report['binding_failures']},
                             {'binder_only_rejection', 'schema_violation', 'generation_or_transport_error'})
            self.assertNotIn('PRIVATE', json.dumps(report))
            self.assertEqual(report['network_calls'], 0)
            self.assertFalse(report['semantic_approval'])

    def test_missing_result_and_request_tampering_remain_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            run, request_path = self.make_run(Path(directory), 'a', 'source-context', {}, {})
            request_path.with_name(request_path.name.replace('.request.json', '.result.json')).unlink()
            self.assertEqual(audit_runs([run])['counts']['missing_results'], 1)
            record = json.loads(request_path.read_text())
            record['request']['data']['text'] = 'changed'
            request_path.write_text(json.dumps(record))
            report = audit_runs([run])
            self.assertEqual(report['counts']['integrity_errors'], 1)

    def test_nested_boolean_values_are_not_equal_to_numbers_for_uniqueness(self):
        schema = {'type': 'array', 'uniqueItems': True}
        self.assertFalse(check_output(schema, [{'v': True}, {'v': 1}])['errors'])
        self.assertTrue(check_output(schema, [{'v': 1}, {'v': 1.0}])['errors'])

    def test_unsupported_contract_is_visible_even_without_a_completed_response(self):
        with tempfile.TemporaryDirectory() as directory:
            run, request_path = self.make_run(Path(directory), 'a', 'future-stage', {'allOf': [{}]}, {})
            request_path.with_name(request_path.name.replace('.request.json', '.result.json')).unlink()
            report = audit_runs([run])
            self.assertEqual(report['counts']['unsupported_contracts'], 1)

    def test_nonfinite_output_and_nonstring_property_names_fail_explicitly(self):
        self.assertTrue(check_output({}, float('nan'))['errors'])
        self.assertFalse(inspect_schema({'properties': {1: {'type': 'string'}}})['supported'])


if __name__ == '__main__':
    unittest.main()
