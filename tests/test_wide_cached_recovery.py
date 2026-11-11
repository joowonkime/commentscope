"""A cached read cannot invoke a provider or turn a pending call into a retry."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from tools import wide_cached_recovery as cached
from commentscope.factory.automatic_contract import digest
from commentscope.providers.checkpoint_calls import CheckpointRunner, PendingCallError


class Base:
    provider_identity = 'synthetic_provider'
    def __init__(self, directory):
        self.directory = directory
        self.plan_sha = 'a'*64
        self.calls = 0
    def call(self, stage, request, *, provider=None, maximum=None):
        self.calls += 1
        return {'raw': 'synthetic', 'output': {'synthetic': True}, 'errors': [],
                'usage': {'cost': 0.001, 'prompt_tokens': 2}}


class Parent:
    def call(self, stage, request):
        self.parent_calls += 1
        return {'original_guarded_dispatch': True}
    def decide(self, stage, request):
        self.parent_calls += 1
        return {'original_guarded_typed_dispatch': True}
    def inspect(self, request):
        raise AssertionError('Paid-dispatch inspection must not run for a pure local measurement')


class Subject(cached.CachedReads, Parent):
    pass


class CachedRecoveryTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = Base(self.root)
        self.cp = CheckpointRunner(self.base, {'reasoning': 'off', 'reasoning_budget': 0, 'context': 8192})
        self.request = {'system': 'synthetic', 'data': {'original': 'synthetic'}, 'schema': {}, 'max_tokens': 16}
        self.stage = 'argument-node-metadata-'+digest(self.request)[:20]
        self.role = cached.executor.remote.role(self.stage)
        self.key = 'generation' if self.role == 'interaction' else self.role
        self.wire_stage = self.key+'-'+self.stage
        self.expected = self.cp.call(self.wire_stage, self.request)

    def subject(self):
        obj = Subject()
        obj.dispatch = Mock()
        obj.storage = Mock()
        obj.cost_limits = Mock()
        obj.checkpoints = {'generation': self.cp, 'verification': self.cp}
        client = Mock()
        client.measure.return_value = {'fits': True, 'input_upper_bound_tokens': 100, 'provider_margin': 0}
        client.deployment = {'synthetic': True}
        obj.clients = {'generation': client, 'verification': client}
        obj.cached_reads = obj.parent_calls = 0
        obj.plan = {'authorization': {'authorization': {'started_at': '2000-01-01T00:00:00+00:00',
                                                       'deadline': '2100-01-01T00:00:00+00:00'}}}
        return obj

    def test_reads_real_original_checkpoint_without_reinvoking_its_provider(self):
        hit, result = cached.completed_read(self.cp, self.wire_stage, self.request)
        self.assertTrue(hit)
        self.assertEqual(result, self.expected)
        self.assertEqual(self.base.calls, 1)
        result['output']['synthetic'] = False
        self.assertEqual(cached.completed_read(self.cp, self.wire_stage, self.request)[1], self.expected)

    def test_pending_checkpoint_and_changed_result_fail_before_dispatch(self):
        done = next((self.root/'checkpoints').glob('*.result.json'))
        saved = done.read_text()
        done.unlink()
        with self.assertRaises(PendingCallError):
            cached.completed_read(self.cp, self.wire_stage, self.request)
        done.write_text(saved)
        changed = json.loads(saved)
        changed['result']['output']['synthetic'] = False
        done.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            cached.completed_read(self.cp, self.wire_stage, self.request)
        self.assertEqual(self.base.calls, 1)

    def test_different_request_or_plan_cannot_borrow_an_old_response(self):
        different = deepcopy(self.request)
        different['data']['original'] = 'another source'
        self.assertEqual(cached.completed_read(self.cp, self.wire_stage, different), (False, None))
        self.base.plan_sha = 'b'*64
        self.assertEqual(cached.completed_read(self.cp, self.wire_stage, self.request), (False, None))
        self.assertEqual(self.base.calls, 1)

    def test_terminal_failure_is_not_a_successful_cached_answer(self):
        done = next((self.root/'checkpoints').glob('*.result.json'))
        value = json.loads(done.read_text())
        value['result'] = {'raw': None, 'output': None, 'usage': None, 'errors': ['bounded_call_failed']}
        value['result_sha256'] = digest(value['result'])
        done.write_text(json.dumps(value))
        self.assertEqual(cached.completed_read(self.cp, self.wire_stage, self.request), (False, None))

    def test_cached_success_retains_receipt_capacity_and_call_limit_checks(self):
        obj = self.subject()
        with patch.object(cached.executor.remote, 'parsed_receipt') as receipt:
            self.assertEqual(obj._completed_call(self.stage, self.request), self.expected)
        receipt.assert_called_once_with(self.expected, self.request, obj.clients[self.key].deployment)
        obj.cost_limits.admit.assert_called_once()
        self.assertEqual(obj.parent_calls, 0)
        self.assertEqual(obj.cached_reads, 1)
        self.assertEqual(self.base.calls, 1)

    def test_cache_miss_uses_original_guarded_dispatch_and_pending_never_does(self):
        obj = self.subject()
        different = deepcopy(self.request)
        different['data']['original'] = 'fresh request'
        self.assertEqual(obj._completed_call(self.stage, different), {'original_guarded_dispatch': True})
        self.assertEqual(obj.parent_calls, 1)
        next((self.root/'checkpoints').glob('*.result.json')).unlink()
        with self.assertRaises(PendingCallError):
            obj._completed_call(self.stage, self.request)
        self.assertEqual(obj.parent_calls, 1)
        self.assertEqual(self.base.calls, 1)

    def test_local_measurement_keeps_resource_stop_and_does_not_dispatch(self):
        obj = self.subject()
        self.assertTrue(obj.inspect(self.request)['fits'])
        obj.dispatch.check.assert_called_once_with()
        self.assertEqual(obj.parent_calls, 0)
        obj.dispatch.check.side_effect = RuntimeError('latched resource stop')
        with self.assertRaises(RuntimeError):
            obj.inspect(self.request)

    def test_cached_receipt_with_invalid_actual_input_count_is_rejected(self):
        obj = self.subject()
        obj.clients[self.key].measure.return_value['input_upper_bound_tokens'] = 1
        with patch.object(cached.executor.remote, 'parsed_receipt'):
            with self.assertRaises(ValueError):
                obj._completed_call(self.stage, self.request)
        self.assertEqual(obj.parent_calls, 0)

    def test_typed_completed_read_keeps_answers_validation_and_miss_uses_parent(self):
        class TypedClient:
            def generate(self, **kwargs):
                raise AssertionError('Provider must not run for a completed read')
        obj = self.subject()
        obj.plan['membership_judge_protocol'] = 'selected'
        obj.membership_client = TypedClient()
        obj.membership_checkpoint = self.cp
        payload = {'synthetic': 'typed original'}
        stage = 'membership-jev-'+digest(payload)[:20]
        expected = self.cp.call(stage, payload, provider=obj.membership_client.generate)
        with patch.object(cached.trial.decisions, 'wire_sha256', side_effect=lambda value, deployment: digest(value)), \
                patch.object(cached.trial.jev_membership, 'measure', return_value={'fits': True}), \
                patch.object(cached.trial.decisions, 'answers') as answers:
            self.assertEqual(obj.decide(stage, payload), expected)
            answers.assert_called_once_with(payload, expected, cached.trial.decisions.DEPLOYMENT)
            different = {'synthetic': 'fresh typed source'}
            another = 'membership-jev-'+digest(different)[:20]
            self.assertEqual(obj.decide(another, different), {'original_guarded_typed_dispatch': True})
        self.assertEqual(obj.parent_calls, 1)
        self.assertEqual(self.base.calls, 2)

    def test_cache_read_cannot_extend_the_original_phase_window(self):
        obj = self.subject()
        obj.plan['authorization']['authorization']['deadline'] = '2001-01-01T00:00:00+00:00'
        with self.assertRaises(TimeoutError):
            obj._completed_call(self.stage, self.request)
        self.assertEqual(obj.parent_calls, 0)
        self.assertEqual(self.base.calls, 1)
