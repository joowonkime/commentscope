import unittest
from copy import deepcopy
from commentscope.factory import scoped_discovery as s


class ScopedDiscoveryTests(unittest.TestCase):
    def fixture(self):
        return {'claims':[{'id':'C','text':'The commenter favors shorter workweeks.',
                 'kind':'value','scope':{'entity':'commenter','time':'','conditions':''},
                 'requires':[],'anchor_id':'A','quote':'I favor shorter workweeks.'}]}

    def test_proposal_does_not_assign_members(self):
        value=self.fixture()
        self.assertEqual(list(s.validate_proposal(value,{'A':'I favor shorter workweeks.','B':'No.'})),['C'])
        self.assertNotIn('members',s.proposal_request({'A':'Hi'})['schema']['properties'])

    def test_no_claim_valid(self):
        self.assertEqual(s.validate_proposal({'claims':[]},{'A':'lol'}),{})

    def test_fabricated_quote_rejected(self):
        with self.assertRaises(ValueError): s.validate_proposal(self.fixture(),{'A':'Not that.'})

    def test_premise_cannot_disappear_or_cycle(self):
        x=self.fixture(); x['claims'][0]['requires']=['F1']
        with self.assertRaises(ValueError): s.validate_proposal(x,{'A':'I favor shorter workweeks.'})
        f=deepcopy(x['claims'][0]); f.update(id='F1',kind='fact',requires=['F1']); x['claims'].append(f)
        with self.assertRaises(ValueError): s.validate_proposal(x,{'A':'I favor shorter workweeks.'})

    def test_full_source_and_no_reference(self):
        claim={k:v for k,v in self.fixture()['claims'][0].items() if k not in ['quote','anchor_id']}
        text='Opponents say yes. But I disagree.'
        self.assertEqual(s.judge_request(text,claim)['data']['SOURCE'],text)
        self.assertEqual(set(s.judge_request(text,claim)['data']),{'SOURCE','TARGET'})

    def test_error_not_support(self):
        self.assertEqual(s.verdict({'errors':['bad'],'output':{'verdict':'supported'}}),'error')
        self.assertEqual(s.verdict({'errors':[],'output':{'verdict':'supported','reason':'Present'}}),'supported')
