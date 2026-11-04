"""Bounded diagnostic execution uses synthetic provider responses only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import source_semantics_diagnostic as probe
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json
from commentscope.storage import write_json_exclusive as write
from test_openrouter import deployment
from test_source_semantics_contract import typed_declarations


class SourceDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir='runs', prefix='source-diagnostic-test-')
        self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.directory = self.root/'diagnostic'
        self.cycle_file = self.root/'cycle.json'
        self.fixture = {'version': 'test-synthetic', 'sources': [
            {'id': 'normal', 'text': 'Protect privacy.', 'parent': None}], 'controls': [
            {'id': 'positive', 'source': {'id': 'value', 'text': 'Protect privacy.', 'parent': None},
             'proposal': 'Protect privacy.', 'expected': {'kind': 'value', 'nomination_eligible': True}}]}
        self.cycle = {'version': probe.CYCLE_VERSION,
            'started_at': datetime.now(timezone.utc).isoformat(), 'tasks': ['TASK-004'],
            'deadline': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            'maximum_additional_usd': '5', 'selected_deployment': {**deployment(), 'context': 65536},
            'shared_policy_file': str(self.root/'policy.json')}
        write(self.cycle_file, self.cycle)
        write(self.root/'policy.json', {'account_id': 'synthetic', 'ledger': str(self.root/'money.sqlite'),
                                     'maximum_usd': '50', 'opening_charge_usd': '0.1'})
        self.addCleanup(patch.stopall)
        patch.object(probe, 'fixture', return_value=deepcopy(self.fixture)).start()
        patch.object(probe, 'provider_preflight', return_value={'synthetic': True}).start()
        self.metadata = patch.object(probe, 'key_metadata', return_value={'limit_remaining': 50}).start()
        self.base = patch.object(probe, 'InferenceBudget').start().return_value
        self.base.call.side_effect = self.response

    def response(self, request, *args, **kwargs):
        if 'PROPOSALS' in request['data']:
            output = typed_declarations(len(request['data']['PROPOSALS']))
        else:
            output = {'c': [{'e': ['S000'], 'k': [], 'a': 'asserted', 't': '', 'l': ''}], 'm': False}
        return {'choices': [{'message': {'content': json.dumps(output)}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'cost': 0.00001}}

    def prepare(self): return probe.prepare(self.directory, self.cycle_file)

    def test_controls_do_not_send_expected_labels_to_model(self):
        value = probe.control_interpretation(self.fixture['controls'][0])
        request = probe.si.review_request([value], protocol=probe.si.TYPED_REVIEW)
        self.assertNotIn('expected', json.dumps(request))
        self.assertNotIn('test-synthetic', json.dumps(request))

    def test_completed_resume_adds_no_paid_calls_and_all_records_bind(self):
        plan = self.prepare(); report = probe.run(self.directory)
        self.assertEqual(report['generated_sources'], 1)
        self.assertEqual(report['controls_passed'], 1)
        self.assertEqual(report['new_requests'], 3)
        self.assertFalse(report['quality_gate_passed'])
        records = read_json(self.directory/'source-records.json')
        self.assertEqual(records[0]['snapshot_sha256'], digest(plan['inputs']))
        self.assertEqual(probe.run(self.directory), report)
        self.assertEqual(self.base.call.call_count, 3)
        self.assertEqual(report['spending_scope']['charged_usd'], '0.00003')
        with patch.object(probe, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.now(timezone.utc)+timedelta(hours=2)
            self.assertEqual(probe.run(self.directory), report)
        self.assertEqual(self.base.call.call_count, 3)

    def test_changed_cycle_or_input_is_refused_before_inference(self):
        self.prepare()
        data = read_json(self.cycle_file); data['maximum_additional_usd'] = '6'
        self.cycle_file.write_text(json.dumps(data))
        with self.assertRaises(ValueError): probe.run(self.directory)
        self.base.call.assert_not_called()

    def test_expired_cycle_refuses_before_provider_or_metadata(self):
        self.cycle['started_at'] = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        self.cycle['deadline'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.cycle_file.write_text(json.dumps(self.cycle))
        with self.assertRaisesRegex(TimeoutError, 'deadline'): self.prepare()
        self.metadata.assert_not_called(); self.base.call.assert_not_called()

    def test_changed_fixture_and_plan_are_refused_before_inference(self):
        self.prepare()
        altered = deepcopy(self.fixture); altered['sources'][0]['text'] = 'Changed.'
        with patch.object(probe, 'fixture', return_value=altered), self.assertRaises(ValueError):
            probe.run(self.directory)
        plan = read_json(self.directory/'plan.json'); plan['max_requests'] += 1
        (self.directory/'plan.json').write_text(json.dumps(plan))
        with self.assertRaises(ValueError): probe.run(self.directory)
        self.base.call.assert_not_called()

    def test_type_control_mismatch_stops_and_preserves_original_observation(self):
        self.fixture['controls'][0]['expected']['kind'] = 'fact'
        patch.object(probe, 'fixture', return_value=deepcopy(self.fixture)).start()
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'control'): probe.run(self.directory)
        observed = read_json(self.directory/'control-positive.json')['observed']
        self.assertEqual(observed['kind'], 'value')
        self.assertEqual(self.base.call.call_count, 1)

    def test_control_mismatch_stops_before_automatic_extraction(self):
        self.fixture['controls'][0]['expected']['nomination_eligible'] = False
        patch.object(probe, 'fixture', return_value=deepcopy(self.fixture)).start()
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'control'): probe.run(self.directory)
        self.assertEqual(self.base.call.call_count, 1)
        self.assertTrue((self.directory/'control-positive.json').exists())
        with self.assertRaises(RuntimeError): probe.run(self.directory)
        self.assertEqual(self.base.call.call_count, 1)

    def test_partial_extraction_stops_without_continuation_or_repair(self):
        self.prepare(); original = self.response
        def partial(request, *args, **kwargs):
            result = original(request, *args, **kwargs)
            if 'PROPOSALS' not in request['data']:
                value = json.loads(result['choices'][0]['message']['content']); value['m'] = True
                result['choices'][0]['message']['content'] = json.dumps(value)
            return result
        self.base.call.side_effect = partial
        with self.assertRaisesRegex(RuntimeError, 'partial'): probe.run(self.directory)
        self.assertEqual(self.base.call.call_count, 2)
        self.assertTrue((self.directory/'extraction-normal.json').exists())

    def test_unknown_cost_holds_shared_ledger_and_is_not_retried(self):
        self.prepare(); self.base.call.side_effect = lambda *a, **k: {'usage': {}}
        with self.assertRaises(RuntimeError): probe.run(self.directory)
        with self.assertRaises(RuntimeError): probe.run(self.directory)
        self.assertEqual(self.base.call.call_count, 1)


if __name__ == '__main__': unittest.main()
