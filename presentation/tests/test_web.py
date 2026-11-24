import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from filter_comments import digest
from llm_client import ModelError
from perspective_agents import ChatSession
from test_perspective_agents import bundle
from web_data import Translator
from web_server import Application, BusyError


class EnglishClient:
    model = 'test/english'

    def __init__(self):
        self.calls = []
        self.fail_agent = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.korean_answer = False

    def structured(self, system, payload, schema, name):
        self.calls.append((system, copy.deepcopy(payload), name))
        if name == 'web_translation':
            korean = 'Korean for searching' in system
            return {'data': {'translations': [{'id': x['id'], 'text': '주4일제 가족 시간' if korean else 'A full day off for family time.'} for x in payload['items']]}}
        if name == 'chat_title':
            return {'data': {'title': '근무 단축의 피해자' if '피해' in json.dumps(payload, ensure_ascii=False) else 'Why a day off helps'}}
        if name == 'reflection_review':
            room = payload['conversations'][0]
            agent = next(m for m in room['messages'] if m['role'] == 'agent')
            return {'data': {'before_fragments': ['time with family', 'not in the view'], 'after_fragments': ['I still want'],
                             'items': [{'category': 'stayed', 'title': 'Family time still matters', 'explanation': 'You kept this.',
                                        'before_quote': 'time with family', 'now_quote': 'invented quote', 'room_id': room['room_id'],
                                        'message_id': agent['message_id'], 'agent_quote': agent['text'][:10], 'user_quote': 'Why does'},
                                       {'category': 'open', 'title': 'Who covers shifts?', 'explanation': 'Still unclear to you.',
                                        'before_quote': '', 'now_quote': '', 'room_id': 'foreign', 'message_id': 'm0001',
                                        'agent_quote': '', 'user_quote': ''}]}}
        self.entered.set()
        self.release.wait(3)
        if payload['agent_id'] == self.fail_agent:
            raise ModelError('simulated provider failure')
        return {'data': {'segments': [{'text': '한국어 응답' if self.korean_answer else 'My perspective values usable time with family.',
                                      'basis': 'comment', 'evidence_ids': [payload['evidence'][0]['evidence_id']]}],
                         'follow_up_questions': ['Which trade-off matters most to you?']}, 'model': self.model}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.client = EnglishClient()
        self.b = bundle()
        self.translator = Translator(self.root/'translations.json', self.client)
        data = SimpleNamespace(output=self.root, bundle=self.b, translator=self.translator, catalog=lambda: {'fingerprint': 'test'})
        data.comment = lambda c, t: {'comment_id': c['comment_id'], 'text': t, 'original_text': c['text'], 'like_count': c['like_count'], 'url': 'https://www.youtube.com/watch?v=test'}
        data.comments = lambda cs: [data.comment(c, t) for c, t in zip(cs, self.translator.translate([c['text'] for c in cs]))]
        with patch('web_server.WebData', return_value=data):
            self.app = Application(self.root, self.client)

    def tearDown(self):
        self.client.release.set()
        self.app.executor.shutdown(wait=True)
        self.tmp.cleanup()

    def create(self, ids=None):
        return self.app.create_room({'participants': ids or ['g1', 'g2'], 'initial_opinion': 'I want time with family.'})['room_id']

    def wait(self, job):
        until = time.monotonic()+5
        while self.app.jobs[job['job_id']]['status'] == 'running' or job.get('room_id') in self.app.active:
            if time.monotonic() > until:
                self.fail('Job did not complete.')
            time.sleep(.005)
        return self.app.jobs[job['job_id']]

    def ask(self, rid, ids=None, request_id='ask-1'):
        return self.app.ask(rid, {'text': 'Why does a day off help?', 'recipients': ids or ['g1', 'g2'], 'request_id': request_id})

    def test_english_room_retains_language_retrieval_query_and_exact_sources(self):
        rid = self.create(['g1'])
        self.assertEqual(self.wait(self.ask(rid, ['g1']))['status'], 'completed')
        room = self.app.room(rid)
        self.assertEqual(room.state['language'], 'en')
        self.assertIn('주4일제', room.state['messages'][0]['retrieval_query'])
        answer = room.state['messages'][1]
        self.assertEqual(answer['evidence'][0]['text'], self.b['agents'][0]['comments'][0]['text'])
        system = next(s for s, _, n in self.client.calls if n == 'perspective_reply')
        self.assertIn('Speak natural, conversational English', system)
        self.assertNotIn('Speak natural, conversational Korean', system)
        public = self.app.public_room(rid)
        self.assertNotIn('retrieval_query', public['messages'][0])
        self.assertEqual(public['messages'][1]['evidence'][0]['text'], 'A full day off for family time.')
        self.assertEqual(self.app.room(rid).state['initial_opinion'], 'I want time with family.')

    def test_korean_question_gets_korean_replies_focused_on_the_question(self):
        self.client.korean_answer = True
        rid = self.create()
        question = '주4일제로 피해를 보는 사람은 누구일까?'
        self.wait(self.app.ask(rid, {'text': question, 'recipients': ['g1', 'g2'], 'request_id': 'ko'}))
        self.app.set_paused(rid, False)
        self.wait(self.app.advance(rid, {'request_id': 'turn'}))
        replies = [(s, p) for s, p, n in self.client.calls if n == 'perspective_reply']
        self.assertEqual(len(replies), 3)
        for system, payload in replies:
            self.assertIn('Speak natural, conversational Korean in every answer', system)
            self.assertIn('Keep replies short', system)
            self.assertIn('first person', system)
            self.assertIn('댓글에서는', system)  # named as a phrase to avoid
            self.assertEqual(payload['user_question'], question)
        self.assertEqual(replies[-1][1]['target_message']['role'], 'agent')
        # A Korean question is its own search query: no translation call.
        self.assertFalse(any(n == 'web_translation' and 'Korean for searching' in s for s, _, n in self.client.calls))
        state = self.app.room(rid).state
        self.assertEqual(state['messages'][0]['language'], 'ko')
        self.assertEqual(state['messages'][0]['retrieval_query'], question)
        self.assertEqual({m['language'] for m in self.app.public_room(rid)['messages']}, {'ko'})

    def test_room_title_follows_question_and_reflection_quotes_are_verified(self):
        rid = self.create(['g1'])
        self.wait(self.ask(rid, ['g1']))
        self.assertEqual(self.app.public_room(rid)['title'], 'Why a day off helps')
        result = self.app.reflect('I want time with family.', 'I still want a full day off.')
        stayed, open_item = result['items']
        self.assertEqual(stayed['before_quote'], 'time with family')
        self.assertEqual(stayed['now_quote'], '')  # not an exact substring of the current view
        self.assertEqual(stayed['moment']['room_id'], rid)
        self.assertEqual(stayed['moment']['user_quote'], 'Why does')
        self.assertIsNone(open_item['moment'])  # unknown room is dropped, not shown
        self.assertEqual(result['before_excerpt'], 'time with family')
        self.assertEqual((result['one_to_one'], result['group']), (1, 0))
        saved = self.app.save_reflection({'initial_opinion': 'a', 'current_view': 'b', 'analysis': result, 'feedback': {}})
        self.assertTrue(saved['saved_at'])

    def test_delete_room_removes_it_but_not_while_replying(self):
        rid = self.create(['g1'])
        self.client.release.clear()
        job = self.ask(rid, ['g1'])
        self.assertTrue(self.client.entered.wait(2))
        with self.assertRaises(BusyError):
            self.app.delete_room(rid)
        self.client.release.set()
        self.wait(job)
        self.assertEqual(self.app.delete_room(rid), {'deleted': rid})
        self.assertNotIn(rid, [r['room_id'] for r in self.app.list_rooms()])
        with self.assertRaises(FileNotFoundError):
            self.app.public_room(rid)

    def test_non_english_generation_rejected_and_retry_keeps_user_message(self):
        self.client.korean_answer = True
        rid = self.create(['g1'])
        self.wait(self.ask(rid, ['g1']))
        self.assertEqual(len(self.app.room(rid).state['messages']), 1)
        self.assertEqual(len(self.app.public_room(rid)['errors']), 1)
        self.client.korean_answer = False
        self.wait(self.app.retry(rid, {'recipients': ['g1'], 'target_message_id': 'm0001', 'request_id': 'retry'}))
        self.assertEqual(len(self.app.room(rid).state['messages']), 2)
        self.assertEqual(self.app.public_room(rid)['errors'], [])

    def test_duplicate_requests_and_busy_room_do_not_duplicate_model_calls(self):
        rid = self.create()
        self.client.release.clear()
        first = self.ask(rid)
        self.assertTrue(self.client.entered.wait(2))
        self.assertEqual(self.ask(rid)['job_id'], first['job_id'])
        with self.assertRaises(BusyError):
            self.ask(rid, request_id='another')
        self.client.release.set()
        self.wait(first)
        self.assertEqual(len([x for x in self.client.calls if x[2] == 'perspective_reply']), 2)
        self.assertEqual(len(self.app.room(rid).state['messages']), 3)

    def test_pause_during_inflight_reply_is_immediate_and_persisted(self):
        rid = self.create()
        self.wait(self.ask(rid))
        self.app.set_paused(rid, False)
        self.client.release.clear()
        self.client.entered.clear()
        job = self.app.advance(rid, {'request_id': 'turn'})
        self.assertTrue(self.client.entered.wait(2))
        self.assertTrue(self.app.set_paused(rid, True)['paused'])
        self.client.release.set()
        self.wait(job)
        self.assertTrue(self.app.room(rid).state['web_paused'])
        with self.assertRaises(ValueError):
            self.app.advance(rid, {'request_id': 'should-not-run'})

    def test_bounded_auto_discussion_and_selected_followup(self):
        rid = self.create()
        self.wait(self.ask(rid))
        self.app.set_paused(rid, False)
        for i in range(6):
            self.wait(self.app.advance(rid, {'request_id': f'turn-{i}'}))
        self.assertTrue(self.app.public_room(rid)['paused'])
        self.assertEqual(self.app.public_room(rid)['auto_turns'], 6)
        self.wait(self.ask(rid, ['g2'], 'followup'))
        messages = self.app.room(rid).state['messages']
        self.assertEqual(messages[-1]['sender_id'], 'g2')
        self.assertEqual(messages[-1]['reply_to'], messages[-2]['message_id'])

    def test_failed_agent_retry_does_not_rebill_successful_agent(self):
        rid = self.create()
        self.client.fail_agent = 'g2'
        self.wait(self.ask(rid))
        self.assertEqual(len(self.app.room(rid).state['messages']), 2)
        self.client.fail_agent = None
        self.wait(self.app.retry(rid, {'recipients': ['g1', 'g2'], 'target_message_id': 'm0001', 'request_id': 'retry'}))
        self.assertEqual(len(self.app.room(rid).state['messages']), 3)
        self.assertEqual(sum(1 for _, p, n in self.client.calls if n == 'perspective_reply' and p['agent_id'] == 'g1'), 1)

    def test_translation_cache_and_source_id_validation(self):
        self.translator.translate(['가족과 하루를 쉬자'])
        calls = len(self.client.calls)
        self.assertEqual(self.translator.translate(['가족과 하루를 쉬자']), ['A full day off for family time.'])
        self.assertEqual(calls, len(self.client.calls))
        self.assertEqual(Translator(self.translator.path, self.client).cache, self.translator.cache)
        with patch.object(self.client, 'structured', return_value={'data': {'translations': [{'id': 'foreign', 'text': 'Wrong'}]}}):
            with self.assertRaises(ValueError):
                self.translator.translate(['another uncached source'])

    def test_path_traversal_and_foreign_recipients_rejected(self):
        for rid in ('../.env', 'g1', 'x'*32):
            with self.assertRaises(ValueError):
                self.app.path(rid)
        rid = self.create(['g1'])
        with self.assertRaises(ValueError):
            self.ask(rid, ['g2'])
        self.assertEqual(self.client.calls, [])


if __name__ == '__main__':
    unittest.main()
