import copy
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from filter_comments import digest
from firebase_backend import AuthenticationError
import test_web
from web_server import Accounts, Handler


class MemoryStore:
    def __init__(self):
        self.records = {}
        self.lock = threading.RLock()

    def load(self, key):
        with self.lock:
            return copy.deepcopy(self.records.get(key))

    def save(self, key, value, expected_hash):
        with self.lock:
            previous = self.records.get(key)
            if (digest(previous) if previous is not None else None) != expected_hash:
                raise ValueError('Concurrent update.')
            self.records[key] = copy.deepcopy(value)

    def list_ids(self, collection):
        return [key.split('/')[1] for key in self.records if key.startswith(collection+'/')]

    def delete(self, key):
        self.records.pop(key, None)


class FakeBackend:
    def __init__(self):
        self.stores = {}

    def verify(self, authorization):
        if authorization not in ('Bearer alice', 'Bearer bob'):
            raise AuthenticationError('Invalid session.')
        return authorization[7:]

    def for_user(self, uid):
        return self.stores.setdefault(uid, MemoryStore())


class AccountStorageTests(unittest.TestCase):
    def setUp(self):
        test_web.WebTests.setUp(self)
        self.backend = FakeBackend()
        with patch('web_server.WebData', return_value=self.app.data):
            self.accounts = Accounts(self.root, self.client, self.backend, self.root/'users')
        self.alice = self.accounts.for_user('alice')
        self.bob = self.accounts.for_user('bob')

    def tearDown(self):
        self.client.release.set()
        self.accounts.executor.shutdown(wait=True)
        self.accounts.titles.shutdown(wait=True)
        self.app.titles.shutdown(wait=True)
        test_web.WebTests.tearDown(self)

    def create(self):
        return self.alice.create_room({'participants': ['g1'], 'initial_opinion': 'Private view'})['room_id']

    def test_rooms_and_profile_survive_new_application_without_local_json(self):
        room_id = self.create()
        self.alice.update_profile({'initial_opinion': 'My view', 'saved_evidence': []})
        self.accounts.apps.pop('alice')
        reloaded = self.accounts.for_user('alice')
        self.assertEqual(reloaded.public_room(room_id)['initial_opinion'], 'Private view')
        self.assertEqual(reloaded.profile()['initial_opinion'], 'My view')
        self.assertEqual(list(reloaded.rooms_dir.glob('*.json')), [])

    def test_other_user_cannot_read_delete_or_reflect_on_private_room(self):
        room_id = self.create()
        self.assertEqual(self.bob.list_rooms(), [])
        self.assertEqual(self.bob.transcripts(), [])
        self.assertEqual(self.bob.profile(), {})
        for action in (self.bob.public_room, self.bob.delete_room):
            with self.assertRaises(FileNotFoundError):
                action(room_id)
        self.assertEqual(self.alice.public_room(room_id)['room_id'], room_id)

    def test_concurrent_session_save_rejects_stale_transcript(self):
        room_id = self.create()
        first = self.alice.room(room_id)
        stale = self.alice.room(room_id)
        first.state['web_title'] = 'First'
        first.save()
        stale.state['web_title'] = 'Stale'
        with self.assertRaises(ValueError):
            stale.save()
        self.assertEqual(self.alice.room(room_id).state['web_title'], 'First')

    def test_forged_saved_evidence_is_rejected(self):
        room_id = self.create()
        with self.assertRaises(ValueError):
            self.alice.update_profile({'saved_evidence': [{'room_id': room_id, 'message_id': 'm0001', 'source': {'comment_id': 'invented'}}]})
        with self.assertRaises(FileNotFoundError):
            self.bob.update_profile({'saved_evidence': [{'room_id': room_id, 'message_id': 'm0001', 'source': {}}]})

    def test_provider_error_details_are_not_returned_in_room(self):
        room_id = self.create()
        room = self.alice.room(room_id)
        room.state['errors'].append({'agent_id': 'g1', 'target_message_id': 'm0001', 'error': 'private-provider-detail'})
        room.save()
        public = self.alice.public_room(room_id)
        self.assertTrue(public['errors'])
        self.assertNotIn('private-provider-detail', json.dumps(public))

    def test_api_requires_token_and_scopes_room_and_job_requests(self):
        room_id = self.create()
        self.alice.jobs['a'*32] = {'job_id': 'a'*32, 'status': 'completed', 'result': 'private'}
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.app = self.accounts
        server.allowed_origins = {'https://commentmas.vercel.app'}
        server.private_values = ('never-return-this-secret',)
        self.alice.jobs['b'*32] = {'job_id': 'b'*32, 'status': 'failed', 'error': 'never-return-this-secret'}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}/api'

        def status(path, token=None, origin=None):
            headers = {}
            if token:
                headers['Authorization'] = 'Bearer '+token
            if origin:
                headers['Origin'] = origin
            try:
                with urlopen(Request(base+path, headers=headers), timeout=5) as response:
                    return response.status, json.load(response)
            except HTTPError as error:
                with error:
                    return error.code, json.load(error)

        try:
            self.assertEqual(status('/bootstrap')[0], 401)
            self.assertEqual(status('/bootstrap', 'invalid')[0], 401)
            self.assertEqual(status('/bootstrap', 'alice', 'https://foreign.example')[0], 401)
            self.assertEqual(status('/rooms/'+room_id, 'alice')[0], 200)
            self.assertEqual(status('/rooms/'+room_id, 'bob')[0], 404)
            self.assertEqual(status('/jobs/'+'a'*32, 'bob')[0], 404)
            self.assertEqual(status('/bootstrap', 'bob')[1]['rooms'], [])
            self.assertEqual(status('/jobs/'+'a'*32, 'alice')[1]['result'], 'private')
            code, response = status('/jobs/'+'b'*32, 'alice')
            self.assertEqual(code, 503)
            self.assertNotIn('never-return-this-secret', json.dumps(response))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
