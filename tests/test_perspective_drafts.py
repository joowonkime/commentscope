import copy
import json
from urllib.error import URLError
import unittest

from commentscope.contracts.perspective_draft import bind, schema, validate
from commentscope.contracts.perspective_assignment import canonicalize
from commentscope.factory.perspective_drafts import draft, render
from commentscope.factory.draft_audit import audit, pairs_for


class PerspectiveDraftTests(unittest.TestCase):
    def members(self):
        return {f'M{i}': {'claim_id': f'c{i}', 'source_comment_id': f's{i}',
                         'target': 'Automation could require support.',
                         'extracted_claim': 'Automation could require support.'} for i in range(3)}

    def value(self):
        return {'groups': [{'members': list(self.members()), 'common': {
            'text': 'Automation could require support.', 'evidence': [
                {'member_id': mid, 'quote': 'Automation could require support.'} for mid in self.members()]},
            'details': []}], 'excluded': []}

    def test_valid_draft_is_never_approved(self):
        result = bind(self.value(), self.members())
        self.assertEqual(result['accepted_perspectives'], 0)
        self.assertEqual(result['semantic_review_status'], 'pending')
        self.assertEqual(result['groups'][0]['status'], 'needs_semantic_review')
        self.assertEqual(result['groups'][0]['common']['evidence'][0]['source_comment_id'], 's0')

    def test_same_source_is_not_three_supporters(self):
        members = self.members()
        for m in members.values(): m['source_comment_id'] = 'same'
        self.assertEqual(bind(self.value(), members)['groups'][0]['status'], 'rare_needs_review')

    def test_cannot_drop_or_duplicate_members(self):
        for mode in ['drop', 'duplicate']:
            value = self.value()
            if mode == 'drop': value['groups'][0]['members'].pop()
            else: value['excluded'].append({'member_id': 'M0', 'reason': 'duplicate'})
            self.assertIn('partition_not_exact', validate(value, self.members()))

    def test_common_requires_evidence_for_every_member(self):
        value = self.value(); value['groups'][0]['common']['evidence'].pop()
        self.assertIn('groups[0].common.common_does_not_cover_group', validate(value, self.members()))

    def test_parent_or_foreign_quote_rejected(self):
        value = self.value(); value['groups'][0]['common']['evidence'][0]['quote'] = 'not in target'
        self.assertIn('groups[0].common.quote_not_in_target', validate(value, self.members()))

    def test_foreign_member_and_extra_approval_rejected(self):
        value = self.value(); value['groups'][0]['common']['evidence'][0]['member_id'] = 'foreign'
        self.assertIn('groups[0].common.foreign_citation', validate(value, self.members()))
        value = self.value(); value['approved'] = True
        self.assertEqual(validate(value, self.members()), ['envelope_keys'])

    def test_subset_detail_is_allowed_but_cannot_cite_other_group(self):
        value = self.value()
        value['groups'][0]['details'] = [{'kind': 'variation', 'text': 'Only this author says could.',
                                        'evidence': [copy.deepcopy(value['groups'][0]['common']['evidence'][0])]}]
        self.assertEqual(validate(value, self.members()), [])
        value['groups'][0]['details'][0]['evidence'][0]['member_id'] = 'foreign'
        self.assertTrue(validate(value, self.members()))

    def test_all_excluded_is_valid_but_no_drafts(self):
        value = {'groups': [], 'excluded': [{'member_id': mid, 'reason': 'unclear'} for mid in self.members()]}
        self.assertEqual(bind(value, self.members())['groups'], [])

    def test_incomplete_output_is_not_bound(self):
        def fake(*args):
            return {'choices': [{'message': {'content': json.dumps(self.value())}, 'finish_reason': 'length'}]}
        result = draft(self.members(), {}, fake)
        self.assertIn('incomplete_generation', result['contract_errors'])
        self.assertIsNone(result['bound_draft'])

    def test_transport_failure_preserved(self):
        def fake(*args): raise URLError('offline')
        result = draft(self.members(), {}, fake)
        self.assertEqual(result['contract_errors'], ['local_transport_error'])
        self.assertIsNone(result['bound_draft'])

    def test_bad_json_preserved_and_escaped(self):
        def fake(*args):
            return {'choices': [{'message': {'content': '<script>bad()</script>'}, 'finish_reason': 'stop'}]}
        result = draft(self.members(), {}, fake)
        self.assertEqual(result['raw'], '<script>bad()</script>')
        page = render({'summary': {}, 'results': [{'cluster_id': 'test', **result}]})
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)

    def test_schema_only_allows_current_member_refs(self):
        wire = schema(self.members())
        enum = wire['properties']['groups']['items']['properties']['members']['items']['enum']
        self.assertEqual(enum, ['M0', 'M1', 'M2'])

    def assignment(self):
        return {'assignments': {mid: {'group_id': 'G1', 'exclusion_reason': None} for mid in self.members()},
                'groups': [{'group_id': 'G1', 'common': 'Automation could require support.', 'details': []}]}

    def test_assignment_binds_actual_target_without_model_quote_copy(self):
        canonical = canonicalize(self.assignment(), self.members())
        self.assertEqual(canonical['groups'][0]['common']['evidence'][0]['quote'], self.members()['M0']['target'])
        self.assertEqual(validate(canonical, self.members()), [])

    def test_assignment_cannot_omit_member_or_group(self):
        value = self.assignment(); del value['assignments']['M0']
        with self.assertRaises(ValueError): canonicalize(value, self.members())
        value = self.assignment(); value['groups'] = []
        with self.assertRaises(ValueError): canonicalize(value, self.members())

    def test_assignment_exclusion_needs_reason(self):
        value = self.assignment(); value['assignments']['M0']['group_id'] = 'X'
        with self.assertRaises(ValueError): canonicalize(value, self.members())
        value['assignments']['M0']['exclusion_reason'] = 'unclear'
        self.assertEqual(len(canonicalize(value, self.members())['excluded']), 1)

    def test_assignment_detail_cannot_cite_excluded_member(self):
        value = self.assignment()
        value['assignments']['M0'] = {'group_id': 'X', 'exclusion_reason': 'unclear'}
        value['groups'][0]['details'] = [{'kind': 'reason', 'text': 'A reason', 'member_ids': ['M0']}]
        with self.assertRaises(ValueError): canonicalize(value, self.members())

    def test_v2_runner_keeps_raw_and_canonical_separate(self):
        def fake(*args):
            return {'choices': [{'message': {'content': json.dumps(self.assignment())}, 'finish_reason': 'stop'}]}
        result = draft(self.members(), {}, fake, revision='v2')
        self.assertEqual(result['contract_errors'], [])
        self.assertEqual(result['citation_mode'], 'host_bound_full_target')
        self.assertIn('assignments', result['output'])
        self.assertNotIn('assignments', result['canonical_output'])
        self.assertEqual(result['bound_draft']['accepted_perspectives'], 0)

    def test_local_audit_support_is_not_approval(self):
        pairs = pairs_for(self.value())
        def fake(*args):
            output = {key: {'verdict': 'supported', 'reason': 'stated'} for key in pairs}
            return {'choices': [{'message': {'content': json.dumps(output)}, 'finish_reason': 'stop'}]}
        result = audit(self.value(), self.members(), fake)
        self.assertEqual(result['recommendation'], 'needs_human_review')
        self.assertFalse(result['human_approved'])

    def test_local_audit_partial_requires_revision(self):
        pairs = pairs_for(self.value())
        def fake(*args):
            output = {key: {'verdict': 'partial', 'reason': 'too strong'} for key in pairs}
            return {'choices': [{'message': {'content': json.dumps(output)}, 'finish_reason': 'stop'}]}
        self.assertEqual(audit(self.value(), self.members(), fake)['recommendation'], 'revise_before_human_approval')

    def test_local_audit_cannot_skip_pairs(self):
        def fake(*args):
            return {'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]}
        result = audit(self.value(), self.members(), fake)
        self.assertIn('pair_coverage', result['errors'])
        self.assertEqual(result['recommendation'], 'audit_failed')
