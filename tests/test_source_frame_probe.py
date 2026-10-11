import json
import unittest
from urllib.error import URLError
from experiments.source_frame_probe import probe, validate, validate_members, partitions, existing_vectors, render, SYSTEM, SCHEMA
from commentscope.cluster_baseline import MODEL, REVISION


class SourceFrameProbeTests(unittest.TestCase):
    def value(self):
        return {'assertion_type': 'prediction', 'certainty': 'asserted', 'reason_quote': None, 'condition_quote': 'when ready'}

    def test_source_only_request_no_old_claim_or_group(self):
        def provider(system, payload, schema):
            self.assertEqual(system, SYSTEM); self.assertEqual(schema, SCHEMA)
            self.assertEqual(payload, {'TARGET': 'It will happen when ready.'})
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(self.value())}}]}
        result = probe('It will happen when ready.', provider)
        self.assertEqual(result['errors'], [])
        self.assertFalse(result['human_approved'])
        self.assertEqual(result['semantic_review_status'], 'pending')

    def test_foreign_or_empty_quote_rejected(self):
        for quote in ['invented', '', ' ']:
            value = self.value(); value['reason_quote'] = quote
            self.assertIn('reason_quote_not_in_target', validate(value, 'when ready'))

    def test_enums_keys_and_non_string_quote_rejected(self):
        value = self.value(); value['assertion_type'] = 'approved'
        self.assertIn('assertion_type_enum', validate(value, 'when ready'))
        value = self.value(); value['certainty'] = 'certainly_true'; value['reason_quote'] = []
        self.assertEqual(len(validate(value, 'when ready')), 2)
        value['approved'] = True
        self.assertEqual(validate(value, 'when ready'), ['frame_keys'])

    def test_null_quotes_allowed(self):
        value = self.value(); value['condition_quote'] = None
        self.assertEqual(validate(value, 'A claim.'), [])

    def test_transport_and_truncation_not_success(self):
        def unavailable(*args): raise URLError('offline')
        self.assertIn('transport_error', probe('text', unavailable)['errors'])
        def truncated(*args):
            return {'choices': [{'finish_reason': 'length', 'message': {'content': json.dumps(self.value())}}]}
        self.assertIn('incomplete_generation', probe('when ready', truncated)['errors'])

    def test_bad_json_retained(self):
        def provider(*args): return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'bad'}}]}
        result = probe('text', provider)
        self.assertEqual(result['raw'], 'bad'); self.assertIn('invalid_response', result['errors'])

    def test_small_unique_source_limit(self):
        member = {'source_comment_id': 'one', 'target': 'Text'}
        validate_members({'M1': member})
        for members in [{}, {'M1': member, 'M2': member}, {'M1': {**member, 'target': 'x'*2001}}]:
            with self.assertRaises(ValueError): validate_members(members)
        with self.assertRaises(ValueError):
            validate_members({str(i): {**member, 'source_comment_id': str(i)} for i in range(13)})

    def test_fixed_thresholds_and_partition(self):
        result = partitions(['M1', 'M2', 'M3'], [[1, 0], [1, 0], [0, 1]])
        self.assertEqual(set(result), {'0.25', '0.35', '0.45'})
        self.assertTrue(all(groups == [['M1', 'M2'], ['M3']] for groups in result.values()))
        with self.assertRaises(ValueError): partitions(['M1'], [])

    def test_saved_embedding_provenance_and_member_order(self):
        claims = [{'claim_id': 'a', 'issue': 'Topic', 'claim': 'Claim', 'reason': None, 'condition': None}]
        saved = {'embedding': {'model': MODEL, 'revision': REVISION, 'claim_ids': ['a'], 'texts': ['Topic\nClaim'], 'vectors': [[1, 0]]}}
        self.assertEqual(existing_vectors(saved, {'claims': claims}, {'M1': {'claim_id': 'a'}}), [[1, 0]])
        saved['embedding']['texts'] = ['tampered']
        with self.assertRaises(ValueError): existing_vectors(saved, {'claims': claims}, {'M1': {'claim_id': 'a'}})

    def test_report_escapes_untrusted_source_and_output(self):
        report = {'clustering_comparison': {}, 'members': {'M1': {'target': '<script>source</script>'}},
                  'old_claims': {'M1': {'claim': '<script>claim</script>'}},
                  'results': [{'member_id': 'M1', 'output': {'reason_quote': '<script>quote</script>'}, 'errors': []}]}
        page = render(report)
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
