"""Terminal transport recovery preserves money and never resends a failed call."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from tools import wide_mining_recovery as recovery
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import sha
from commentscope.providers.openrouter_budget import SpendLedger


class WideMiningRecoveryTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('calls', 'checkpoints'):
            (self.root/name).mkdir()
        self.plan = {'artifact_kind': recovery.wide.VERSION, 'mode': 'development',
                     'spend_policy': {'ledger': str(self.root/'money.sqlite'), 'account_id': 'synthetic',
                                      'maximum_usd': '50', 'opening_charge_usd': '0'},
                     'spend_scope_sha256': 'a'*64,
                     'deployment': deepcopy(recovery.executor.remote.SOL),
                     'verification_deployment': deepcopy(recovery.executor.remote.SOL)}
        self.write('plan.json', self.plan)
        self.request = {'system': 'synthetic', 'data': {'node': 'synthetic'},
                        'schema': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
                        'max_tokens': 128}
        self.stage = 'shared-owned-position-'+digest(self.request)[:20]
        self.wire_stage, self.req_sha = recovery.wire_identity(self.plan, self.stage, self.request)
        actual = recovery.allocate(self.request, recovery.executor.openrouter.generation_allocation(
            self.plan['deployment'], require_explicit=True))
        self.request_file = self.root/'calls'/('0001-'+self.wire_stage+'.request.json')
        self.write(self.request_file, {'request': actual, 'request_sha256': self.req_sha,
                                     'plan_sha256': sha(self.root/'plan.json')})
        self.result_file = self.request_file.with_name(self.request_file.name.replace('.request.json', '.result.json'))
        self.result = {'raw': None, 'output': None, 'errors': ['bounded_call_failed'], 'seconds': None, 'usage': None}
        self.write(self.result_file, self.result)
        identity = {'artifact_kind': recovery.CHECKPOINT_VERSION, 'plan_sha256': sha(self.root/'plan.json'),
                    'stage': self.wire_stage, 'request_sha256': self.req_sha,
                    'provider': recovery.executor.openrouter.Runner.provider_identity}
        self.intent = self.root/'checkpoints'/(digest(identity)+'.intent.json')
        self.write(self.intent, identity)
        self.checkpoint = self.intent.with_name(self.intent.name.replace('.intent.json', '.result.json'))
        self.write(self.checkpoint, {'identity': identity, 'result': self.result, 'result_sha256': digest(self.result)})
        with closing(sqlite3.connect(self.root/'inference.sqlite')) as db, db:
            db.execute('CREATE TABLE calls(id INTEGER,plan_sha TEXT,request_sha TEXT,state TEXT,error TEXT)')
            db.execute('INSERT INTO calls VALUES(1,?,?,?,?)',
                       (sha(self.root/'plan.json'), self.req_sha, 'error',
                        json.dumps({'type': 'HTTPError', 'http_status': 503, 'body': 'synthetic timeout'})))
        self.money = recovery.executor.ledger(self.plan['spend_policy'])
        self.cid = self.money.reserve('a'*64, self.req_sha, '0.04201575', run_limit_usd='15', key_remaining_usd='150')
        self.money.finish(self.cid, None)
        self.manifest = self.root/'recoveries/0001/manifest.json'

    def write(self, name, value):
        path = Path(name)
        if not path.is_absolute():
            path = self.root/path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value)+'\n')

    def prepare(self):
        with patch.object(recovery.wide, 'validate', return_value=self.plan), \
                patch.object(recovery.executor, 'private'):
            return recovery.prepare(self.root, self.manifest, user_request='Continue within the original cap; no retries.')

    def test_reconciles_full_reservation_and_holds_exact_failed_request_without_provider_call(self):
        before = self.money.summary()
        report = self.prepare()
        after = self.money.summary()
        self.assertEqual(before['charged_usd'], after['charged_usd'])
        self.assertEqual(after['conservative_usd'], '0.04201575')
        self.assertEqual(after['uncertain_calls'], 0)
        self.assertEqual(report['unavailable_requests'], 1)
        provider = Mock()
        with self.assertRaises(recovery.PriorRequestUnavailable):
            recovery.guarded_call(self.root, self.plan, self.manifest, self.stage, self.request, provider)
        provider.assert_not_called()
        self.assertEqual(self.money.summary()['calls'], 1)

    def test_other_request_uses_original_session_and_cannot_borrow_failed_response(self):
        self.prepare()
        provider = Mock(return_value={'original': 'unchanged'})
        different = deepcopy(self.request)
        different['data']['node'] = 'another synthetic node'
        result = recovery.guarded_call(self.root, self.plan, self.manifest, self.stage, different, provider)
        self.assertEqual(result, {'original': 'unchanged'})
        provider.assert_called_once_with()

    def test_active_or_foreign_uncertain_charge_blocks_preparation(self):
        with closing(sqlite3.connect(self.money.path)) as db, db:
            db.execute("UPDATE calls SET state='reserved' WHERE id=?", (self.cid,))
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.manifest.exists())

    def test_non_temporary_error_and_interrupted_call_cannot_be_skipped(self):
        for error, state in [({'type': 'HTTPError', 'http_status': 401}, 'error'),
                             ({'type': 'Interrupted'}, 'error'),
                             ({'type': 'HTTPError', 'http_status': 503}, 'reserved')]:
            with closing(sqlite3.connect(self.root/'inference.sqlite')) as db, db:
                db.execute('UPDATE calls SET error=?,state=?', (json.dumps(error), state))
            with self.assertRaises(ValueError):
                recovery.terminal_evidence(self.root, self.plan, self.request_file)

    def test_unreconciled_wrong_scope_or_changed_original_cannot_hold_a_request(self):
        self.prepare()
        bad_plan = deepcopy(self.plan)
        bad_plan['spend_scope_sha256'] = 'b'*64
        with self.assertRaises(ValueError):
            recovery.validate(self.root, self.manifest, bad_plan)
        self.write(self.result_file, {**self.result, 'raw': 'made up success'})
        with self.assertRaises(ValueError):
            recovery.validate(self.root, self.manifest, self.plan)

    def test_manifest_archive_and_inflight_changes_are_rejected(self):
        self.prepare()
        binding = recovery.dispatch_binding(self.root, self.manifest, self.plan)
        value = json.loads(self.manifest.read_text())
        value['provider_retries'] = 1
        self.write(self.manifest, value)
        with self.assertRaises(ValueError):
            recovery.guarded_call(self.root, self.plan, self.manifest, self.stage, self.request, Mock(), _binding=binding)
        value['provider_retries'] = 0
        self.write(self.manifest, value)
        Path(value['launcher_archive']).write_text('altered archive')
        with self.assertRaises(ValueError):
            recovery.validate(self.root, self.manifest, self.plan)

    def test_semantic_or_usage_bearing_result_cannot_be_relabelled_as_transport_failure(self):
        self.write(self.result_file, {**self.result, 'usage': {'cost': 0.001}})
        with self.assertRaises(ValueError):
            recovery.terminal_evidence(self.root, self.plan, self.request_file)
        self.assertEqual(self.money.summary()['uncertain_calls'], 1)

    def test_duplicate_checkpoint_or_money_reservation_is_rejected(self):
        self.write(self.intent.with_name('duplicate.intent.json'), json.loads(self.intent.read_text()))
        with self.assertRaises(ValueError):
            recovery.terminal_evidence(self.root, self.plan, self.request_file)

    def test_foreign_uncertain_charge_cannot_be_cleared_by_this_recovery(self):
        with closing(sqlite3.connect(self.money.path)) as db, db:
            db.execute("INSERT INTO calls(plan_sha,request_sha,reserved,charged,state) VALUES(?,?,?,?,?)",
                       ('b'*64, 'c'*64, 100, 100, 'unknown'))
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.money.summary()['uncertain_calls'], 2)
        self.assertFalse(self.manifest.exists())

    def test_plan_change_or_unsettled_reservation_cannot_continue(self):
        self.prepare()
        with closing(sqlite3.connect(self.money.path)) as db, db:
            db.execute("UPDATE calls SET state='unknown' WHERE id=?", (self.cid,))
        with self.assertRaises(ValueError):
            recovery.validate(self.root, self.manifest, self.plan)
        with closing(sqlite3.connect(self.money.path)) as db, db:
            db.execute("UPDATE calls SET state='conservative' WHERE id=?", (self.cid,))
        self.write('plan.json', {**self.plan, 'changed': True})
        with self.assertRaises(ValueError):
            recovery.validate(self.root, self.manifest, self.plan)

