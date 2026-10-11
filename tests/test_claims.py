import unittest
from commentscope.contracts.claims import bind_source, validate_extraction
from commentscope.contracts.claim_generation import constrained_schema
from commentscope.contracts.claims import SCHEMA, ELIGIBILITY


class ClaimContractTests(unittest.TestCase):
    def test_generation_branches_match_eligibility_invariant(self):
        substantive, other = constrained_schema()['anyOf']
        self.assertEqual(substantive['properties']['eligibility']['enum'], [ELIGIBILITY[0]])
        self.assertEqual(substantive['properties']['claims']['minItems'], 1)
        self.assertEqual(other['properties']['eligibility']['enum'], ELIGIBILITY[1:])
        self.assertEqual(other['properties']['claims']['maxItems'], 0)

    def test_generation_schema_does_not_mutate_previous_revision(self):
        constrained_schema()['anyOf'][0]['properties']['claims']['maxItems'] = 100
        self.assertEqual(SCHEMA['properties']['claims']['maxItems'], 6)
        self.assertNotIn('minItems', SCHEMA['properties']['claims'])

    def example(self):
        return {'eligibility':'argument_or_experience','claims':[{
            'issue':'work choice','claim':'I might work more.','quote':'I might work more.',
            'stance_target':None,'stance':'neutral','reason':None,'reason_quote':None,
            'condition':None,'condition_quote':None,'scope':'personal','modality':'possible'}]}

    def test_valid_and_deterministic(self):
        x=self.example()
        a=bind_source(x,'c1','I might work more.')
        self.assertEqual(a,bind_source(x,'c1','I might work more.'))
        self.assertEqual(a['semantic_review_status'],'pending')
        self.assertNotEqual(a['claims'][0]['claim_id'],bind_source(x,'c2','I might work more.')['claims'][0]['claim_id'])

    def test_eligibility_contradiction(self):
        x=self.example(); x['eligibility']='contextual_reaction'
        self.assertIn('eligibility_claims_inconsistent',validate_extraction(x,'I might work more.'))

    def test_false_empty_substantive(self):
        self.assertIn('eligibility_claims_inconsistent',validate_extraction({'eligibility':'argument_or_experience','claims':[]},'text'))

    def test_no_stance_without_target(self):
        x=self.example(); x['claims'][0]['stance']='support'
        self.assertIn('claims[0].missing_stance_target',validate_extraction(x,'I might work more.'))

    def test_reason_requires_evidence(self):
        x=self.example(); x['claims'][0]['reason']='because happy'
        self.assertIn('claims[0].reason_evidence_pair',validate_extraction(x,'I might work more.'))

    def test_parent_quote_not_accepted(self):
        self.assertIn('claims[0].quote_not_in_target',validate_extraction(self.example(),'yes'))

    def test_model_cannot_assign_source_id(self):
        x=self.example(); x['claims'][0]['source_comment_id']='invented'
        self.assertIn('claims[0].keys',validate_extraction(x,'I might work more.'))

    def test_non_substantive_can_be_empty(self):
        self.assertEqual([],validate_extraction({'eligibility':'non_substantive','claims':[]},'lol'))
