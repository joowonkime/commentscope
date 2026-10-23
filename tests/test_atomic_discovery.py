import unittest
from experiments.atomic_discovery_probe import invocation
from commentscope.factory import perspective_typing


class AtomicDiscoveryTests(unittest.TestCase):
    def test_core_schema_cannot_mix_type_reasons_and_membership(self):
        request=invocation({'s':'Original comment'})
        self.assertEqual(request['max_tokens'],350)
        no,yes=request['schema']['anyOf']
        self.assertEqual(set(no['properties']),{'decision'})
        self.assertEqual(set(yes['properties']),{'decision','text','anchor_id','quote'})
        self.assertEqual(yes['properties']['anchor_id']['enum'],['s'])
        self.assertEqual(request['data'],{'COMMENTS':{'s':'Original comment'}})

    def test_type_boundary_never_accepts_claim_rewrite(self):
        proposal={'id':'p','claims':{'C':{'id':'C','text':'Original core','kind':'fact',
                  'scope':{'entity':'','time':'','conditions':''},'requires':[]}},'sources':{'s':'Original'}}
        with self.assertRaises(ValueError):
            perspective_typing.apply(proposal,{'status':'classified','kind':'future_expectation',
                   'details':[],'required_fact_ids':[],'text':'Changed core'},proposal['sources'])
