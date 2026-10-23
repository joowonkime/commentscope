from copy import deepcopy
import unittest

from commentscope.factory import membership_policy as policy
from commentscope.factory.automatic_contract import digest
from commentscope.factory.scoped_discovery import judge_request
from experiments.directed_membership_probe import directed


class MembershipPolicyTests(unittest.TestCase):
    def row(self, *, modified=True):
        claim = {'id': 'C', 'text': 'I would work.', 'kind': 'fact',
                 'scope': {'entity': '', 'time': '', 'conditions': ''}, 'requires': []}
        req = judge_request('I would work as a nurse.', claim)
        if modified:
            req = directed(req)
            req['max_tokens'] = 512
        return {'id': 'J1', 'text': req['data']['SOURCE'], 'claim': claim,
                'request': req, 'request_sha256': digest(req)}

    def test_exact_directed_policy_and_token_budget_survive(self):
        row = self.row()
        frozen = policy.from_rows([row])
        self.assertEqual(policy.invocation(frozen, row['text'], row['claim']), row['request'])
        self.assertEqual(frozen['max_tokens'], 512)
        self.assertNotIn('labels', frozen)

    def test_new_source_and_target_do_not_change_policy(self):
        row = self.row(); frozen = policy.from_rows([row])
        claim = {**row['claim'], 'text': 'I would travel.'}
        req = policy.invocation(frozen, 'I would cycle.', claim)
        self.assertEqual(req['data']['SOURCE'], 'I would cycle.')
        self.assertEqual(req['data']['TARGET']['text'], 'I would travel.')
        for key in ('system', 'schema', 'max_tokens'):
            self.assertEqual(req[key], row['request'][key])

    def test_type_and_dependency_metadata_do_not_rewrite_judged_target(self):
        row = self.row(); frozen = policy.from_rows([row])
        typed = {**row['claim'], 'kind': 'prediction', 'requires': ['F1']}
        self.assertEqual(policy.invocation(frozen, row['text'], typed), row['request'])
        changed = {**typed, 'text': 'Everyone would work.'}
        self.assertNotEqual(policy.invocation(frozen, row['text'], changed), row['request'])

    def test_mixed_or_unbound_requests_fail(self):
        with self.assertRaises(ValueError): policy.from_rows([])
        with self.assertRaises(ValueError): policy.from_rows([self.row(), self.row(modified=False)])
        for change in ('hash', 'source', 'target', 'schema'):
            row = self.row()
            if change == 'hash': row['request_sha256'] = 'bad'
            else:
                if change == 'source': row['request']['data']['SOURCE'] = 'Another source.'
                elif change == 'target': row['request']['data']['TARGET']['text'] = 'Another target.'
                else: row['request']['schema'] = {}
                row['request_sha256'] = digest(row['request'])
            with self.subTest(change=change), self.assertRaises(ValueError): policy.from_rows([row])

    def test_bad_tokens_and_policy_fields_fail(self):
        frozen = policy.from_rows([self.row()])
        for tokens in (True, 0, -1, 4097, 512.0):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                policy.validate({**frozen, 'max_tokens': tokens})
        with self.assertRaises(ValueError): policy.validate({**frozen, 'labels': {'J1': 'supported'}})

    def test_detail_binding_never_mutates_prior_rows(self):
        row = self.row(); frozen = policy.from_rows([row])
        original = self.row(modified=False); before = deepcopy(original)
        bound = policy.bind_rows(frozen, [original])
        self.assertEqual(original, before)
        self.assertEqual(bound[0]['request'], row['request'])
        self.assertEqual(bound[0]['request_sha256'], digest(bound[0]['request']))
        bound[0]['request']['schema'].clear()
        policy.validate(frozen)
