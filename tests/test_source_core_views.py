from copy import deepcopy
from unittest import TestCase

from commentscope.factory import source_core_views as views, source_bound_core as sb
from test_raw_membership import candidate


class IsolatedCoreViewTests(TestCase):
    def setUp(self):
        self.source = {'id': 'child', 'text': 'It should cover everyone.',
            'parent': {'id': 'parent', 'text': 'Free school meals improve concentration.'}}
        self.candidate = candidate(self.source, self.source['text'])
        self.core = 'Free school meals should cover everyone.'
        self.properties = {'target': 'identified', 'commitment': 'normative', 'world': 'actual',
            'scope': 'population', 'content': 'public_issue_claim', 'voice': 'asserted', 'reason_quotes': []}

    def source_view(self, **updates):
        return views.bind_source(self.candidate, self.source, {'output': {**self.properties, **updates}})

    def core_view(self, text=None, **updates):
        return views.bind_core(text or self.core, {'output': {**self.properties, **updates}})

    def test_core_reader_has_no_original_parent_or_prior_judgment(self):
        req = views.core_request(self.core)
        self.assertEqual(req['data'], {'FOCUS': self.core})
        source = views.source_request(self.candidate, self.source)
        self.assertEqual(source['data']['FOCUS'], self.source['text'])
        self.assertEqual(source['data']['ORIGINAL_CONTEXT_ONLY']['PARENT_CONTEXT_ONLY'], self.source['parent'])
        self.assertNotIn('CORE_HYPOTHESIS', source['data'])

    def test_reasons_cannot_be_quoted_from_parent_or_other_source_clause(self):
        with self.assertRaises(ValueError): self.source_view(reason_quotes=['improve concentration'])
        source = {**self.source, 'text': 'It should cover everyone. Meals improve concentration.'}
        target = candidate(source, 'It should cover everyone.')
        with self.assertRaises(ValueError):
            views.bind_source(target, source, {'output': {**self.properties, 'reason_quotes': ['Meals improve concentration.']}})
        text = 'Free school meals should cover everyone because they improve concentration.'
        view = self.core_view(text, reason_quotes=['because they improve concentration'])
        self.assertIn('reason_added_outside_selected_assertion', views.compare(self.source_view(), view)['guards'])

    def test_property_mismatches_and_unknowns_hold_without_granting_support(self):
        for key, value, guard in [('commitment','possibility','commitment_mismatch'),
                                 ('world','fictional','world_mismatch'),
                                 ('scope','self','scope_mismatch'),
                                 ('target','unresolved','core_target_unresolved'),
                                 ('voice','reported','core_voice_unapproved'),
                                 ('content','media_activity_or_identity_only','core_content_unapproved')]:
            compared = views.compare(self.source_view(), self.core_view(**{key: value}))
            self.assertFalse(compared['properties_compatible']); self.assertIn(guard, compared['guards'])
        self.assertFalse(views.compare(self.source_view(), self.core_view(commitment='unclear'))['properties_compatible'])
        compatible = views.compare(self.source_view(), self.core_view())
        self.assertTrue(compatible['properties_compatible']); self.assertFalse(compatible['membership_vote'])

    def test_exact_check_binding_and_existing_negative_check_remain_required(self):
        check = sb.bind_check(self.candidate, self.source, self.core,
                             {'output': {key: 'yes' for key in sb.CHECK_FIELDS}})
        self.assertTrue(views.guarded_check(check, self.source_view(), self.core_view())['eligible_for_membership_check'])
        with self.assertRaises(ValueError): views.guarded_check(check, self.source_view(), self.core_view('Safety reviews should be voluntary.'))
        other = {**self.source, 'id': 'other'}
        foreign = views.bind_source(candidate(other, other['text']), other, {'output': self.properties})
        with self.assertRaises(ValueError): views.guarded_check(check, foreign, self.core_view())
        output = {key: 'yes' for key in sb.CHECK_FIELDS}; output['anchored_to_selected_assertion'] = 'no'
        negative = sb.bind_check(self.candidate, self.source, self.core, {'output': output})
        self.assertFalse(views.guarded_check(negative, self.source_view(), self.core_view())['eligible_for_membership_check'])

    def test_tampered_provenance_or_context_visibility_is_rejected(self):
        for record, validate in ((self.source_view(), views.validate_source), (self.core_view(), views.validate_core)):
            self.assertEqual(validate(record), record)
            changed = deepcopy(record); changed['request_sha256'] = '0'*64
            with self.assertRaises(ValueError): validate(changed)
        changed = self.core_view(); changed['original_context_visible'] = True
        with self.assertRaises(ValueError): views.validate_core(changed)
