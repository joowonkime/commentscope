from copy import deepcopy
from unittest import TestCase

from commentscope.providers.generation_limits import allocate


class GenerationLimitsTests(TestCase):
    def setUp(self):
        self.req = {'system': 'test', 'data': {'source': 'test'}, 'schema': {}, 'max_tokens': 1024}
        self.runtime = {'reasoning': 'on', 'reasoning_budget': 1024, 'context': 8192}

    def test_reasoning_does_not_consume_final_answer_allowance(self):
        self.assertEqual(allocate(self.req, self.runtime)['max_tokens'], 2048)

    def test_nonreasoning_payload_unchanged(self):
        self.assertEqual(allocate(self.req, {**self.runtime, 'reasoning': 'off', 'reasoning_budget': 0}), self.req)

    def test_logical_request_and_runtime_are_not_mutated(self):
        before = deepcopy((self.req, self.runtime))
        allocated = allocate(self.req, self.runtime)
        allocated['data']['source'] = 'changed'
        self.assertEqual(before, (self.req, self.runtime))

    def test_invalid_or_context_exhausting_budgets_rejected(self):
        for changes in ({'reasoning': 'off'}, {'reasoning_budget': -1}, {'reasoning_budget': 4096},
                        {'reasoning_budget': True}, {'reasoning_budget': None}, {'context': 2048},
                        {'reasoning': 'unknown'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                allocate(self.req, {**self.runtime, **changes})
        for tokens in (True, 0, -1, float('inf')):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                allocate({**self.req, 'max_tokens': tokens}, self.runtime)
