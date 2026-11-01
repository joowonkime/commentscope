from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.claim_clusters import read_json
from experiments import openrouter_factory_probe as probe
from test_openrouter import deployment


class OpenRouterProbeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir='runs', prefix='test-remote-probe-')
        self.addCleanup(temp.cleanup); self.directory = Path(temp.name)/'probe'
        self.addCleanup(patch.stopall)
        patch.object(probe, 'source_code_hashes', return_value={'synthetic.py': 'fixed'}).start()
        patch.object(probe, 'check_quota').start()
        patch.object(probe, 'quota_watch', return_value=nullcontext()).start()
        self.metadata = patch.object(probe, 'key_metadata', return_value={
            'limit': 50, 'limit_remaining': 50, 'usage': 0}).start()
        self.budget = Mock()
        self.budget.call.side_effect = lambda *args, **kwargs: {
            'choices': [{'message': {'content': '{"synthetic":true}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'cost': 0.00001}}
        patch.object(probe, 'InferenceBudget', return_value=self.budget).start()

    def prepare(self):
        return probe.prepare(self.directory, deployment(), 0.25)

    def test_whole_batch_price_refusal_creates_no_run_or_inference(self):
        with self.assertRaisesRegex(ValueError, 'cost ceiling'):
            probe.prepare(self.directory, deployment(), 0.000001)
        self.assertFalse(self.directory.exists()); self.budget.call.assert_not_called()

    def test_key_remaining_refusal_precedes_inference(self):
        self.prepare(); self.metadata.return_value['limit_remaining'] = 0
        with self.assertRaisesRegex(ValueError, 'cannot cover'): probe.run(self.directory)
        self.budget.call.assert_not_called()

    def test_eight_cases_retain_cost_and_completed_resume_does_not_call_again(self):
        self.prepare(); report = probe.run(self.directory)
        self.assertEqual(report['cases'], 8)
        self.assertAlmostEqual(report['cost_usd'], 0.00008)
        self.assertFalse(report['quality_gate_passed'])
        self.assertEqual(self.budget.call.call_count, 8)
        self.assertEqual(probe.run(self.directory), report)
        self.assertEqual(self.budget.call.call_count, 8)

    def test_missing_charge_stops_and_keeps_first_response(self):
        self.prepare()
        self.budget.call.side_effect = None
        self.budget.call.return_value = {
            'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}], 'usage': {}}
        with self.assertRaisesRegex(ValueError, 'Missing API charge'): probe.run(self.directory)
        self.assertEqual(self.budget.call.call_count, 1)
        self.assertTrue(list((self.directory/'calls').glob('*.result.json')))
        self.assertFalse((self.directory/'completed.json').exists())

    def test_changed_request_pack_is_rejected_before_inference(self):
        self.prepare(); path = self.directory/'requests.json'
        data = read_json(path); data['cases'][0]['request']['system'] = 'changed'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Frozen'): probe.run(self.directory)
        self.budget.call.assert_not_called()

    def test_shared_money_ledger_counts_new_plans_and_completed_reuse(self):
        policy = {'account_id': 'authored-account', 'ledger': str(self.directory.parent/'spend.sqlite'),
                  'maximum_usd': '1', 'opening_charge_usd': '0.1'}
        probe.prepare(self.directory, deployment(), 0.25, spend_policy=policy)
        first = probe.run(self.directory)
        self.assertEqual(first['spending']['charged_usd'], '0.10008')
        self.assertEqual(probe.run(self.directory), first)
        other = self.directory.with_name('second-probe')
        probe.prepare(other, deployment(), 0.25, spend_policy=policy)
        second = probe.run(other)
        self.assertEqual(second['spending']['charged_usd'], '0.10016')
        self.assertEqual(self.budget.call.call_count, 16)


if __name__ == '__main__': unittest.main()
