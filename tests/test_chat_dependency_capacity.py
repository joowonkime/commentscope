"""Chat capacity belongs to its actual transport; no provider calls."""
from copy import deepcopy
import unittest

from commentscope.factory import argument_dependencies as deps
from commentscope.providers import openrouter, openrouter_decisions as od, remote_verification as remote
from test_typed_verification import case


def large_task():
    record, cores = case()
    template = deepcopy(record['units'][0])
    texts = ['Synthetic stance '+str(i)+' '+('carefully '*32)+'.' for i in range(16)]
    record['source']['text'] = ' '.join(texts)
    record['units'] = []
    start = 0
    for i, text in enumerate(texts, 1):
        record['units'].append({**deepcopy(template), 'id': 'u'+str(i), 'local_id': 'U'+str(i),
            'text': text, 'evidence': [{'start': start, 'end': start+len(text), 'text': text}]})
        start += len(text)+1
    cores[0]['candidate']['text'] = texts[0]
    return deps.tasks(record, cores, typed=True)[0]


class ChatDependencyCapacityTests(unittest.TestCase):
    def test_large_complete_graph_uses_sol_capacity_while_jev_still_rejects_it(self):
        task = large_task()
        with self.assertRaisesRegex(ValueError, 'short-state limit'):
            deps.requests(task)
        requests = deps.chat_requests(task)
        client = openrouter.Client(remote.SOL)
        for request in requests:
            self.assertEqual(request['data']['state']['ORIGINAL'], task['original'])
            self.assertEqual(len(request['data']['state']['UNITS']), len(task['units']))
            self.assertLessEqual(len(request['schema']['properties']), od.DEPLOYMENT['max_questions'])
            self.assertTrue(client.measure(request)['fits'])
        self.assertGreater(len(requests), 1)

    def test_small_chat_payload_matches_the_previous_typed_conversion_exactly(self):
        record, cores = case()
        task = deps.tasks(record, cores, typed=True)[0]
        old = deps.requests(task)
        chat = deps.chat_requests(task)
        self.assertEqual(len(chat), len(old))
        for before, after in zip(old, chat, strict=True):
            self.assertEqual(after['data'], {'state': before['state'], 'questions': before['questions']})
            self.assertEqual(after['schema']['required'], list(before['questions']))
            self.assertEqual(after['schema']['properties'], {k: {'type': 'string', 'enum': list(q['criteria'])}
                for k, q in before['questions'].items()})
            self.assertEqual(after['max_tokens'], 600)

    def test_actual_sol_context_remains_a_limit(self):
        task = large_task()
        task['parent_context_only'] = {'id': 'parent', 'text': 'x'*remote.SOL['context']}
        requests = deps.chat_requests(task)
        self.assertFalse(openrouter.Client(remote.SOL).measure(requests[0])['fits'])

    def test_structural_question_validation_still_applies_to_chat(self):
        task = large_task()
        task['units'][0]['id'] = 'bad alias!'
        with self.assertRaisesRegex(ValueError, 'bounded Choice'):
            deps.chat_requests(task)
