from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from commentscope.storage import write_json_exclusive as write
from experiments import pending_candidate_probe as probe
from experiments.grounding_contract_demo import fixture


class PendingCandidateProbeTests(unittest.TestCase):
    def population(self):
        queue = [{'proposal': {'id': f'P{i}', 'sources': {'s': 'original'}}} for i in range(7)]
        report = {'outcomes': [{'id': f'P{i}', 'state': 'unprocessed_completion_budget' if i >= 2
                               else 'screened_input' if i == 0 else 'ground_type_unresolved'} for i in range(7)],
                  'attempts': [{'candidate_id': 'P0'}, {'candidate_id': 'P1'}]}
        return queue, report

    def test_all_pending_selected_in_source_order_without_rejected_retry(self):
        queue, report = self.population()
        tasks = probe.pending(queue, report)
        self.assertEqual([t['proposal']['id'] for t in tasks], ['P2','P3','P4','P5','P6'])
        tasks[0]['proposal']['sources']['s'] = 'edited'
        self.assertEqual(queue[2]['proposal']['sources']['s'], 'original')

    def test_attempted_candidate_cannot_be_relabelled_pending(self):
        queue, report = self.population(); report['attempts'].append({'candidate_id':'P2'})
        with self.assertRaises(ValueError): probe.pending(queue, report)

    def test_missing_or_reordered_outcomes_rejected(self):
        queue, report = self.population()
        for outcomes in (report['outcomes'][1:], list(reversed(report['outcomes']))):
            with self.assertRaises(ValueError): probe.pending(queue, {**report, 'outcomes':outcomes})

    def test_duplicate_population_rejected(self):
        queue, report = self.population(); queue[-1] = queue[0]
        with self.assertRaises(ValueError): probe.pending(queue, report)

    def test_no_pending_population_cannot_rerun(self):
        queue, report = self.population()
        for o in report['outcomes']: o['state'] = 'insufficient_core_support'
        with self.assertRaises(ValueError): probe.pending(queue, report)

    def base(self):
        b = fixture(); b['claims'] = b['claims'][:1]; b['checks'] = []
        b['relations'] = [r for r in b['relations'] if r['claim_id'] == 'position']
        b['candidates'][0].update(reason_claim_ids=[], major_fact_ids=[])
        return b

    def run_tasks(self, directory, *, fail=False, available=True):
        base = self.base(); before = deepcopy(base); tasks = self.population()[0][2:]
        allocation = Mock(); allocation.begin.return_value = available
        allocation.refusal = 'unprocessed_completion_budget'
        runner = SimpleNamespace(allocation=allocation)
        calls = []
        def complete(p, *args):
            calls.append(p['id'])
            if fail and p['id'] == 'P3': raise ValueError('synthetic failure')
            return None, 'insufficient_core_support'
        plan = {'expires_at':base['expires_at'], 'classifier':base['model'], 'documents':base['documents']}
        with patch.object(probe.pipeline, 'complete_candidate', side_effect=complete):
            outcomes, compiled = probe.run_tasks(directory, plan, runner, tasks, {}, base)
        self.assertEqual(base, before)
        self.assertEqual(compiled['profiles'], probe.compile_inputs(base)['profiles'])
        return outcomes, calls

    def test_all_pending_attempted_and_existing_profile_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcomes, calls = self.run_tasks(Path(tmp))
            self.assertEqual(calls, ['P2','P3','P4','P5','P6'])
            self.assertEqual(len(outcomes), 5)

    def test_candidate_failure_does_not_drop_base_or_later_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcomes, calls = self.run_tasks(Path(tmp), fail=True)
            self.assertEqual(len(calls), 5)
            self.assertEqual(outcomes[1]['state'], 'candidate_failed_ValueError')

    def test_budget_unknown_remains_unknown_without_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcomes, calls = self.run_tasks(Path(tmp), available=False)
            self.assertEqual(calls, [])
            self.assertTrue(all(o['state'] == 'unprocessed_completion_budget' for o in outcomes))

    def test_diagnostic_rejects_fresh_label_or_larger_time_limit(self):
        limits = deepcopy(probe.pipeline.LIMITS); limits['analysis_seconds'] = probe.SECONDS
        plan = {'artifact_kind':probe.VERSION, 'limits':limits, 'diagnostic_seconds':probe.SECONDS,
                'fresh_analysis':False, 'runtime_reference_labels':False}
        for patch_data in ({'fresh_analysis':True}, {'diagnostic_seconds':3600}, {'runtime_reference_labels':True}):
            with self.assertRaises(ValueError): probe.validate({**plan, **patch_data})


if __name__ == '__main__': unittest.main()
