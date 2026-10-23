import json
from pathlib import Path
import sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory
import unittest

from commentscope.factory import shared_claims
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha, read_json
from commentscope.providers.checkpoint_calls import VERSION as CHECKPOINT_VERSION
from commentscope.storage import write_json_exclusive as write
from experiments.completed_shared_proposals import load, BOUNDARY


class CompletedSharedProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir='runs'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.db = self.root/'ledger.sqlite'
        self.originals = [{'id': 'a', 'text': 'Adopt P.', 'parent': None},
                          {'id': 'b', 'text': 'Adopt P now.', 'parent': None}]
        self.deployment = {'runtime': {'reasoning': 'off', 'reasoning_budget': 0, 'context': 8192}}
        proposal = {'candidates': [{'text': 'Adopt P.', 'nominees': ['A0', 'A1']}]}
        req = shared_claims.request(self.originals, version=shared_claims.COMMON)
        self.record = shared_claims.bind(self.originals, {'output': proposal}, version=shared_claims.COMMON)
        plan = {'proposal_contract': shared_claims.COMMON, 'deployment': self.deployment,
                'budget': {'ledger': str(self.db)}, 'code_sha256': {p: sha(p) for p in BOUNDARY}}
        write(self.root/'plan.json', plan); self.plan_hash = sha(self.root/'plan.json')
        output = {'records': [self.record], 'candidates': shared_claims.candidates([self.record])}
        write(self.root/'artifacts/output.json', output)
        write(self.root/'completed.json', {'plan_sha256': self.plan_hash,
            'output_sha256': sha(self.root/'artifacts/output.json'), 'errors': [],
            'capacity_holds': [], 'completed_proposal_calls': 1})
        raw = json.dumps(proposal); response = {'choices': [{'finish_reason': 'stop',
            'message': {'content': raw}}], 'usage': {'total_tokens': 12}}
        result = {'raw': raw, 'output': proposal, 'errors': [], 'usage': response['usage'], 'seconds': 0}
        stage = 'shared-proposal-'+digest(req)[:24]
        self.request_path = self.root/'calls'/('0001-'+stage+'.request.json')
        write(self.request_path, {'request': req, 'request_sha256': digest(req), 'plan_sha256': self.plan_hash})
        write(self.request_path.with_name(self.request_path.name.replace('.request.json', '.result.json')), result)
        identity = {'artifact_kind': CHECKPOINT_VERSION, 'plan_sha256': self.plan_hash,
                    'stage': stage, 'request_sha256': digest(req), 'provider': 'local_llama'}
        checkpoint = self.root/'checkpoints'/digest(identity)
        write(checkpoint.with_suffix('.intent.json'), identity)
        write(checkpoint.with_suffix('.result.json'), {'identity': identity, 'result': result,
                                                       'result_sha256': digest(result)})
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('create table calls(id integer primary key, plan_sha text, request_sha text, request_json text, response_json text, state text)')
            db.execute('insert into calls values(?,?,?,?,?,?)',
                       (1, self.plan_hash, digest(req), json.dumps(req), json.dumps(response), 'ok'))

    def test_completed_response_reuses_no_calls_and_confers_no_semantic_approval(self):
        records, proof = load(self.root, deployment=self.deployment, originals=self.originals)
        self.assertEqual(records, [self.record])
        self.assertEqual(proof['new_model_calls'], 0)
        self.assertFalse(proof['semantic_approval'])
        self.assertEqual(proof['receipts'][0]['ledger_call_id'], 1)

    def test_modified_or_unfinished_ledger_cannot_become_a_cache_hit(self):
        for update in ("update calls set response_json='{}'", "update calls set state='interrupted'"):
            with closing(sqlite3.connect(self.db)) as db, db:
                original = db.execute('select response_json,state from calls').fetchone()
                db.execute(update)
            with self.subTest(update=update), self.assertRaises((ValueError, KeyError)):
                load(self.root, deployment=self.deployment, originals=self.originals)
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute('update calls set response_json=?,state=?', original)

    def test_changed_request_is_rejected_despite_unchanged_result_file(self):
        packet = read_json(self.request_path); packet['request']['data']['ORIGINALS'][0]['source_id'] = 'changed'
        self.request_path.write_text(json.dumps(packet))
        with self.assertRaises(ValueError):
            load(self.root, deployment=self.deployment, originals=self.originals)


if __name__ == '__main__': unittest.main()
