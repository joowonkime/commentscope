"""Firebase identity and durable, user-scoped JSON records.

The server verifies identity before choosing a store. Admin SDK credentials never
reach the browser. Large transcripts are compressed and split across documents.
"""
import gzip
import json
import re
import uuid

from filter_comments import digest


class AuthenticationError(Exception):
    pass


class FirebaseBackend:
    def __init__(self, project_id):
        import firebase_admin
        from firebase_admin import auth, firestore
        self.auth = auth
        self.firestore = firestore
        self.app = firebase_admin.initialize_app(options={'projectId': project_id})
        self.db = firestore.client(app=self.app)

    def verify(self, authorization):
        if not authorization or not authorization.startswith('Bearer '):
            raise AuthenticationError('Sign in to continue.')
        try:
            claims = self.auth.verify_id_token(authorization[7:], app=self.app, check_revoked=True)
        except Exception:
            raise AuthenticationError('Your session expired. Please sign in again.') from None
        uid = claims.get('uid', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', uid):
            raise AuthenticationError('Invalid account.')
        return uid

    def for_user(self, uid):
        return FirestoreStore(self.db, self.firestore, uid)


class FirestoreStore:
    CHUNK_SIZE = 700_000

    def __init__(self, db, firestore, uid):
        self.db, self.firestore = db, firestore
        self.root = db.collection('users').document(uid)

    def ref(self, key):
        if not re.fullmatch(r'(rooms|reflections|profile)/[A-Za-z0-9_-]{1,160}', key):
            raise ValueError('Invalid record key.')
        collection, name = key.split('/')
        return self.root.collection(collection).document(name)

    def load(self, key):
        ref = self.ref(key)

        @self.firestore.transactional
        def read(transaction):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            meta = snapshot.to_dict()
            chunks = []
            for i in range(meta['chunks']):
                part = ref.collection('chunks').document(f"{meta['version']}-{i}").get(transaction=transaction)
                if not part.exists:
                    raise RuntimeError('Incomplete stored record.')
                chunks.append(part.to_dict()['data'])
            return json.loads(gzip.decompress(b''.join(chunks)))

        return read(self.db.transaction())

    def save(self, key, value, expected_hash):
        ref = self.ref(key)
        payload = gzip.compress(json.dumps(value, ensure_ascii=False).encode())
        chunks = [payload[i:i+self.CHUNK_SIZE] for i in range(0, len(payload), self.CHUNK_SIZE)]
        if len(chunks) > 100:
            raise ValueError('This conversation is full. Start a new conversation.')
        version = uuid.uuid4().hex

        @self.firestore.transactional
        def write(transaction):
            snapshot = ref.get(transaction=transaction)
            previous = snapshot.to_dict() if snapshot.exists else None
            if (previous or {}).get('hash') != expected_hash:
                raise ValueError('Record changed in another request. Reload before saving.')
            for i, chunk in enumerate(chunks):
                transaction.set(ref.collection('chunks').document(f'{version}-{i}'), {'data': chunk})
            transaction.set(ref, {'hash': digest(value), 'version': version, 'chunks': len(chunks),
                                 'updated_at': value.get('updated_at', value.get('saved_at', ''))})
            if previous:
                for i in range(previous['chunks']):
                    transaction.delete(ref.collection('chunks').document(f"{previous['version']}-{i}"))

        write(self.db.transaction())

    def list_ids(self, collection):
        if collection not in ('rooms', 'reflections'):
            raise ValueError('Invalid collection.')
        return [snapshot.id for snapshot in self.root.collection(collection).stream()]

    def delete(self, key):
        ref = self.ref(key)

        @self.firestore.transactional
        def remove(transaction):
            snapshot = ref.get(transaction=transaction)
            if snapshot.exists:
                meta = snapshot.to_dict()
                for i in range(meta['chunks']):
                    transaction.delete(ref.collection('chunks').document(f"{meta['version']}-{i}"))
                transaction.delete(ref)

        remove(self.db.transaction())
