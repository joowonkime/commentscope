import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from collect_comments import YouTubeAPI, YouTubeError, collect, parse_video_id
from test_filter_comments import decision
from test_firebase_backend import FakeBackend, MemoryStore
from test_group_comments import FakeClient
from video_library import IntakeError, LocalRecords, VideoLibrary
from web_server import Accounts, Handler


FIRST = 'aaaaaaaaaaa'
SECOND = 'bbbbbbbbbbb'


def comment(cid, text):
    return {'id': cid, 'snippet': {'textDisplay': text, 'likeCount': 1}}


class VideoClient(FakeClient):
    def structured(self, system, payload, schema, name):
        if name == 'comment_filter':
            data = {'decisions': [decision(x['comment_id'], 'keep') for x in payload['comments']]}
        elif name == 'english_perspectives':
            data = {'agents': [{'agent_id': x['agent_id'], 'title': 'Working time',
                                'subtitle': 'View from comments', 'stance': 'A shorter day.',
                                'reasoning': 'Work and personal time.'} for x in payload['agents']]}
        elif name == 'web_translation':
            data = {'translations': [{'id': x['id'], 'text': 'English wording'} for x in payload['items']]}
        else:
            return super().structured(system, payload, schema, name)
        self.requests += 1
        return {'data': data, 'model': self.model, 'usage': {}}


class ScopedBackend(FakeBackend):
    def for_user(self, uid, video_id=None):
        return self.stores.setdefault((uid, video_id), MemoryStore())


class VideoIntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.client = VideoClient()

    def library(self, directory='worker', key='fake-server-key', **kwargs):
        lib = VideoLibrary(self.root / directory, {'YOUTUBE_API_KEY': key, 'VIDEO_COMMENT_LIMIT': 3},
                           self.client, **kwargs)
        self.addCleanup(lib.worker.shutdown)
        return lib

    def terminal(self, lib, vid=FIRST):
        lib.worker.submit(lambda: None).result(timeout=5)
        return lib.status(vid)

    def test_url_forms_and_invalid_links(self):
        for url in (FIRST, f'https://youtu.be/{FIRST}?t=5', f'https://m.youtube.com/watch?v={FIRST}',
                    f'https://www.youtube.com/shorts/{FIRST}', f'https://youtube.com/live/{FIRST}',
                    f'https://youtube.com/embed/{FIRST}'):
            self.assertEqual(parse_video_id(url), FIRST)
        for url in ('', None, 'https://youtube.example/watch?v='+FIRST, 'https://www.youtube.com/@channel',
                    'https://www.youtube.com/playlist?list='+FIRST, f'https://youtube.com/watch?v={FIRST}&v={SECOND}'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_video_id(url)

    def test_sampling_bounds_roots_and_replies_without_fetching_entire_threads(self):
        def get(endpoint, **params):
            if endpoint == 'commentThreads':
                self.assertEqual(params['order'], 'relevance')
                return {'items': [{'snippet': {'topLevelComment': comment('top', 'Position'), 'totalReplyCount': 150}},
                                  {'snippet': {'topLevelComment': comment('next', 'Another position')}}],
                        'nextPageToken': 'unused'}
            self.assertEqual((endpoint, params['parentId'], params['maxResults']), ('comments', 'top', 3))
            return {'items': [comment(str(i), 'Reply') for i in range(3)], 'nextPageToken': 'unused'}
        with patch.object(YouTubeAPI, 'get', side_effect=get) as send:
            rows = collect(YouTubeAPI('fixture'), FIRST, None, True, max_rows=5, order='relevance')
        self.assertEqual(len(rows), 5)
        self.assertEqual([r['parent_id'] for r in rows], ['', 'top', 'top', 'top', ''])
        self.assertEqual(send.call_count, 2)

    def test_no_key_prepared_example_and_stale_claim(self):
        store = LocalRecords(self.root/'db')
        demo = {'video_id': SECOND, 'title': 'Prepared example'}
        offline = self.library(key='', demo=demo, store=store)
        self.assertFalse(offline.options()['can_generate'])
        self.assertEqual(offline.start(SECOND)['status'], 'ready')
        with self.assertRaises(IntakeError) as no_key:
            offline.start(FIRST)
        self.assertEqual(no_key.exception.status, 503)
        self.assertIsNone(store.load('jobs/'+FIRST))
        expired = {'video_id': FIRST, 'status': 'running', 'stage': 'grouping',
                   'updated': time.time()-600, 'attempt': 'abandoned'}
        store.save('jobs/'+FIRST, expired, None)
        self.assertIn('interrupted', offline.status(FIRST)['error'])
        def no_access(*args):
            raise YouTubeError('commentsDisabled')
        worker = self.library('restart', store=store, generate=no_access)
        self.assertEqual(worker.start(FIRST)['status'], 'running')
        self.assertIn('disabled', self.terminal(worker)['error'].lower())
        self.assertNotEqual(store.load('jobs/'+FIRST)['attempt'], 'abandoned')
        self.assertIsNone(store.load('datasets/abandoned'))

    def test_no_comments_or_viable_groups_do_not_publish_agents(self):
        lib = self.library()
        for comments, message in (([], 'no public comments'), ([comment('minor', '소수 대안')], 'enough comment evidence')):
            def get(endpoint, **_):
                if endpoint == 'videos':
                    return {'items': [{'snippet': {'title': 'Topic'}}]}
                return {'items': [{'snippet': {'topLevelComment': c}} for c in comments]}
            with self.subTest(message=message), patch.object(YouTubeAPI, 'get', side_effect=get):
                lib.start(FIRST)
                state = self.terminal(lib)
                self.assertEqual(state['status'], 'failed')
                self.assertIn(message, state['error'])
                with self.assertRaises(IntakeError):
                    lib.directory(FIRST)

    def test_http_generation_reuse_and_private_rooms_across_users_and_videos(self):
        store = LocalRecords(self.root/'shared.sqlite3')
        lib = self.library(store=store)
        other_worker = self.library('other', key='', store=store)
        accounts = Accounts(None, self.client, ScopedBackend(), self.root/'users', library=lib)
        self.addCleanup(accounts.executor.shutdown)
        self.addCleanup(accounts.titles.shutdown)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.app, server.allowed_origins, server.private_values = accounts, set(), ('fake-server-key',)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def api(path, body=None, *, user='alice', video=None):
            headers = {'Authorization': 'Bearer '+user, 'Content-Type': 'application/json'}
            if video:
                headers['X-Review-Video'] = video
            req = Request(f'http://127.0.0.1:{server.server_port}/api'+path, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
            try:
                response = urlopen(req, timeout=5)
            except HTTPError as exc:
                response = exc
            with response:
                return response.status, json.load(response)
        gate = threading.Event()
        self.addCleanup(gate.set)
        def get(endpoint, **params):
            if endpoint == 'videos':
                if not gate.wait(4):
                    raise AssertionError('generation was not released')
                return {'items': [{'snippet': {'title': 'A public topic'}}]}
            vid = params['videoId']
            return {'items': [{'snippet': {'topLevelComment': comment(vid+'a', '찬성 노동시간 단축')}},
                              {'snippet': {'topLevelComment': comment(vid+'b', '반대 운영 문제')}}]}
        with patch.object(YouTubeAPI, 'get', side_effect=get) as youtube:
            self.assertEqual(api('/videos', {'url': FIRST}, user='invalid')[0], 401)
            self.assertEqual(api('/videos', {'url': 'not a video'})[0], 400)
            self.assertEqual(api('/videos', {'url': 'https://youtu.be/'+FIRST})[0], 202)
            self.assertEqual(api('/videos', {'url': FIRST}, user='bob')[0], 202)
            self.assertEqual(other_worker.start(FIRST)['status'], 'running')
            self.assertEqual(api('/videos/'+FIRST)[1]['stage'], 'collecting')
            self.assertEqual(api('/bootstrap', video=FIRST)[0], 404)
            self.assertEqual(api('/videos', {'url': SECOND})[0], 429)
            gate.set()
            self.assertEqual(self.terminal(lib)['status'], 'ready')
            self.assertEqual(api('/videos', {'url': 'https://youtube.com/watch?v='+FIRST})[0], 200)
            self.assertEqual(other_worker.start(FIRST)['status'], 'ready')
            restored = json.loads((other_worker.directory(FIRST)/'04_web/catalog.json').read_text(encoding='utf-8'))
            self.assertEqual(restored['video']['video_id'], FIRST)
            self.assertEqual(youtube.call_count, 2)
            _, catalog = api('/bootstrap', video=FIRST)
            self.assertEqual(len(catalog['agents']), 2)
            self.assertEqual(catalog['counts']['collected'], 2)
            status, room = api('/rooms', {'participants': ['g1'], 'initial_opinion': 'My private view'}, video=FIRST)
            self.assertEqual(status, 201)
            room_path = '/rooms/'+room['room_id']
            self.assertEqual(api(room_path, video=FIRST, user='bob')[0], 404)
            self.assertEqual(api('/bootstrap', video=FIRST, user='bob')[1]['rooms'], [])
            self.assertEqual(api('/videos', {'url': SECOND})[0], 202)
            self.assertEqual(self.terminal(lib, SECOND)['status'], 'ready')
            self.assertEqual(api(room_path, video=SECOND)[0], 404)
            self.assertEqual(api(room_path, video=FIRST)[1]['initial_opinion'], 'My private view')
            self.assertEqual(youtube.call_count, 4)
