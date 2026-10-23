from copy import deepcopy
from unittest import TestCase

from commentscope.factory import minimal_claims as mc, source_bound_core as sb
from test_raw_membership import candidate
from test_contextual_propositions import selected, original


class SourceBoundCoreTests(TestCase):
    def setUp(self):
        self.source = original('I support free school meals only if local funding is secured.')
        self.candidate = candidate(self.source, self.source['text'])
        self.core = 'Free school meals should be introduced only if local funding is secured.'
        self.yes = {'output': {key: 'yes' for key in sb.CHECK_FIELDS}}

    def test_original_normalization_and_parent_survive_without_rewriting(self):
        source = original('Cafe\u0301  access should be free.')
        source['parent'] = {'id': 'parent', 'text': 'The city owns this cafe.'}
        target = mc.candidates([selected(source)])[0]
        request = sb.proposal_request(target, source)
        self.assertEqual(request['data']['SELECTED_ASSERTION']['text'], source['text'])
        self.assertEqual(request['data']['ORIGINAL_CONTEXT_ONLY']['PARENT_CONTEXT_ONLY'], source['parent'])
        self.assertEqual(request['data']['SELECTED_ASSERTION']['end'], len(source['text']))
        self.assertNotEqual(target['text'], source['text'])
        changed = deepcopy(target); changed['text'] = 'Cafe access should be expensive.'
        with self.assertRaises(ValueError): sb.proposal_request(changed, source)

    def test_checker_receives_selected_anchor_and_full_context_without_prior_judgment(self):
        source = original('The plan is expensive. Safety reviews should be mandatory.')
        target = candidate(source, 'The plan is expensive.')
        request = sb.check_request(target, source, 'Safety reviews should be mandatory.')
        self.assertEqual(request['data']['SELECTED_ASSERTION']['text'], target['text'])
        self.assertEqual(set(request['data']), {'SELECTED_ASSERTION', 'ORIGINAL_CONTEXT_ONLY', 'CORE_HYPOTHESIS'})
        self.assertEqual(''.join(p['text'] for p in request['data']['ORIGINAL_CONTEXT_ONLY']['ORIGINAL_SEGMENTS']), source['text'])

    def test_cross_source_anchor_or_hypothesis_cannot_reuse_a_check(self):
        proposal = sb.bind_proposal(self.candidate, self.source, {'output': {'status': 'proposed', 'core': self.core}})
        check = sb.bind_check(self.candidate, self.source, self.core, self.yes)
        self.assertTrue(sb.checked_proposal(proposal, check)['eligible_for_membership_check'])
        other = {**self.source, 'id': 'another-source'}
        foreign = sb.bind_check(candidate(other, other['text']), other, self.core, self.yes)
        with self.assertRaises(ValueError): sb.checked_proposal(proposal, foreign)
        different = sb.bind_check(self.candidate, self.source, 'Free school meals should be introduced.', self.yes)
        with self.assertRaises(ValueError): sb.checked_proposal(proposal, different)
        for record, validator in ((proposal, sb.validate_proposal), (check, sb.validate_check)):
            self.assertEqual(validator(record), record)
            mutated = deepcopy(record); mutated['anchor']['assertion']['end'] -= 1
            with self.assertRaises(ValueError): validator(mutated)
        self.assertFalse(sb.checked_proposal(proposal, check)['membership_vote'])

    def test_uncertain_or_negative_dimension_holds_and_never_claims_factual_truth(self):
        for key in sb.CHECK_FIELDS:
            for value in ('no', 'uncertain'):
                result = deepcopy(self.yes); result['output'][key] = value
                check = sb.bind_check(self.candidate, self.source, self.core, result)
                self.assertFalse(check['passed']); self.assertFalse(check['factual_verification'])
                self.assertFalse(check['generated_text_is_evidence'])
        for result in ({'output': {'status': 'defer', 'core': self.core}},
                       {'output': {'status': 'proposed', 'core': ''}},
                       {'output': {'status': 'proposed', 'core': 'x' * (sb.MAX_CORE + 1)}},
                       {'output': {'status': 'defer', 'core': ''}, 'errors': ['transport']}):
            with self.assertRaises(ValueError): sb.bind_proposal(self.candidate, self.source, result)
        held = sb.bind_proposal(self.candidate, self.source, {'output': {'status': 'defer', 'core': ''}})
        self.assertEqual(sb.validate_proposal(held), held)
        with self.assertRaises(ValueError):
            sb.checked_proposal(held, sb.bind_check(self.candidate, self.source, self.core, self.yes))

    def test_ambiguous_occurrence_requires_a_contextual_original_span(self):
        source = original('I agree. I agree.')
        with self.assertRaises(ValueError): sb.proposal_request(candidate(source, 'I agree.'), source)
