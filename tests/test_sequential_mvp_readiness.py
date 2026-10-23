"""Readiness mechanics only; synthetic labels never approve the real corpus."""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import sequential_mvp_readiness as readiness
from tests import test_sequential_corpus_pipeline as fixture


class ReadinessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.execution = fixture.SequentialCorpusTests(); self.execution.setUp()
        self.addCleanup(self.execution.doCleanups)
        self.run = self.execution.directory; self.runs = self.execution.runs
        self.execution.prepare(); readiness.pipeline.run(self.run)
        self.clusters = self.runs/'cluster-review'; self.agents = self.runs/'agent-review'
        readiness.clusters.prepare(self.clusters, self.run)
        readiness.agents.prepare(self.agents, self.run)
        self.output = self.runs/'readiness'

    def evaluate(self, cluster_parts=(), agent_parts=()):
        with patch.object(readiness, 'replay_benchmark', return_value={'passed': True, 'synthetic': True}):
            return readiness.evaluate(self.output, self.run, self.clusters, list(cluster_parts),
                                      self.agents, list(agent_parts), self.runs/'synthetic-facts')

    def test_empty_reviews_fail_without_inference_or_runtime_mutation(self):
        before = {str(p): sha(p) for p in self.run.rglob('*.json')}
        calls = len(self.execution.requests)
        with patch.object(readiness.pipeline, 'Runner', side_effect=AssertionError('No inference')):
            report = self.evaluate()
        self.assertFalse(report['factory_requirements_met'])
        self.assertEqual(report['correct_comment_utilization'], 0)
        self.assertEqual(report['support_counts']['unreviewed'], 3)
        self.assertIn('all_counted_supports_valid', report['unmet_requirements'])
        self.assertEqual(calls, len(self.execution.requests))
        self.assertEqual(before, {str(p): sha(p) for p in self.run.rglob('*.json')})

    def test_all_supplied_pass_reviews_do_not_hide_low_coverage_or_one_agent(self):
        cluster = read_json(self.clusters/'part-template.json')
        for row in cluster['clusters']: row.update(verdict='coherent', reason='Synthetic coherent stance.')
        for row in cluster['supports']: row.update(verdict='supported', reason='Synthetic valid support.')
        agent = read_json(self.agents/'part-template.json')
        for row in agent['rows']: row.update(verdict='pass', reason='Synthetic review mechanics only.')
        cp = self.runs/'cluster-part.json'; ap = self.runs/'agent-part.json'
        write(cp, cluster); write(ap, agent)
        report = self.evaluate([cp], [ap])
        self.assertEqual(report['correct_comment_utilization'], .6)
        self.assertTrue(report['requirements']['all_counted_supports_valid'])
        self.assertFalse(report['factory_requirements_met'])
        self.assertEqual(len(report['all_generated_agent_supports']), 1)

    def test_other_run_review_and_missing_completion_are_rejected_before_output(self):
        path = self.agents/'manifest.json'; original = read_json(path)
        changed = deepcopy(original); changed['run_directory'] = str(self.runs/'other')
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'same completed run'): self.evaluate()
        self.assertFalse(self.output.exists())
        path.write_text(json.dumps(original)); (self.run/'completed.json').rename(self.run/'completed-backup.json')
        with self.assertRaisesRegex(ValueError, 'Completed Agent'): self.evaluate()
        self.assertFalse(self.output.exists())

    def test_private_and_non_overwriting_results(self):
        self.evaluate()
        with self.assertRaisesRegex(ValueError, 'overwrite'): self.evaluate()
        self.output = self.execution.root/'public'
        with self.assertRaisesRegex(ValueError, 'private'): self.evaluate()


class RequirementCompositionTests(unittest.TestCase):
    def evidence(self):
        sources = {str(i): {} for i in range(5)}
        members = {'a': ['0', '1', '2'], 'b': ['2', '3', '4']}
        plan = {'goal_revision': 'factory-goal-20261014-r4', 'canonical_population': 5,
                'runtime_reference_labels': False, 'cross_run_response_reuse': False}
        completion = {'execution_complete': True, 'analysis_seconds_including_resume_downtime': 50.}
        output = {'source_states': [{'source_id': s, 'state': 'positions'} for s in sources], 'errors': []}
        cluster = {'scope': 'full_corpus', 'canonical_population': 5, 'evaluated_sources': 5,
            'meaningful_sources': 5, 'correct_comment_utilization': .8, 'coverage_target_met': True,
            'support_validity_passed': True, 'utilized_source_ids': ['0', '1', '2', '3'],
            'unutilized_meaningful_ids': ['4'], 'excluded_source_ids': [], 'support_counts': {'supported': 6},
            'per_cluster': [{'perspective_id': cid, 'counted_support': 3, 'reviewed_supported': 3,
                'incorrect_support': 0, 'unresolved_support': 0, 'cluster_review': 'coherent'} for cid in members]}
        packet = {'sources': sources, 'agents': [{'profile': {'candidate_id': cid},
                    'counted_support_source_ids': ids} for cid, ids in members.items()],
                  'argument_deferrals': [], 'fact_deferrals': []}
        agent = {'agent_content_runtime_review_passed': True, 'review_counts': {'pass': 10}}
        return [plan, completion, output, cluster, packet, agent, {'passed': True}]

    def test_all_independent_conditions_required_and_wrong_support_not_offset(self):
        values = self.evidence()
        self.assertTrue(readiness.summarize(*values)['factory_requirements_met'])
        for index, key in [(3, 'coverage_target_met'), (3, 'support_validity_passed'),
                           (5, 'agent_content_runtime_review_passed'), (6, 'passed')]:
            changed = deepcopy(values); changed[index][key] = False
            result = readiness.summarize(*changed)
            self.assertFalse(result['factory_requirements_met'])
            self.assertTrue(result['unmet_requirements'])

    def test_every_agent_needs_three_unique_reviewed_supporters(self):
        for kind in ('too_few', 'duplicate', 'unreviewed', 'incoherent'):
            values = self.evidence(); row = values[3]['per_cluster'][-1]
            if kind == 'too_few': values[4]['agents'][-1]['counted_support_source_ids'].pop()
            if kind == 'duplicate': values[4]['agents'][-1]['counted_support_source_ids'][-1] = '2'
            if kind == 'unreviewed': row['reviewed_supported'] = 2; row['unresolved_support'] = 1
            if kind == 'incoherent': row['cluster_review'] = 'invalid'
            self.assertFalse(readiness.summarize(*values)['factory_requirements_met'], kind)

    def test_whole_inventory_and_valid_timing_required(self):
        values = self.evidence(); values[2]['source_states'][-1]['source_id'] = '0'
        with self.assertRaisesRegex(ValueError, 'canonical processing'): readiness.summarize(*values)
        for seconds in (None, True, float('nan'), -1):
            values = self.evidence(); values[1]['analysis_seconds_including_resume_downtime'] = seconds
            with self.assertRaisesRegex(ValueError, 'timing'): readiness.summarize(*values)


class FixedBenchmarkReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.directory = self.root/'benchmark'; source = self.root/'source'
        self.addCleanup(patch.stopall)
        patch.object(readiness.pipeline, 'PRIVATE_ROOT', self.root).start()
        relevant = ['src/commentscope/providers/local_nli.py', 'src/commentscope/providers/evidence_nli.py',
                    'experiments/fact_nli_probe.py']
        code = {p: sha(p) for p in relevant}
        metadata = {'model': readiness.local_nli.MODEL, 'revision': readiness.local_nli.REVISION,
            'threshold': .8, 'device': 'cpu', 'dtype': 'float32', 'threads': 6,
            'local_files_only': True, 'trust_remote_code': False, 'use_safetensors': True,
            'torch': 'synthetic-test', 'transformers': 'synthetic-test',
            'id2label': {'0': 'entailment', '1': 'neutral', '2': 'contradiction'}}
        rows = [{'id': str(i), 'expected': 'supported' if i < 10 else 'insufficient'} for i in range(40)]
        write(source/'plan.json', {'rows': rows})
        write(source/'report.json', {'rows': [{'id': r['id'], 'actual': r['expected']} for r in rows]})
        cases = [{'id': str(i), 'text': 'Synthetic claim.', 'evidence': [{'id': 'e', 'text': 'Synthetic passage.'}]} for i in range(40)]
        request = {'system': readiness.evidence_nli.VERSION, 'schema': {}, 'max_tokens': 1, 'data': {'cases': cases}}
        weights = {str(self.root/'model.safetensors'): '1'*64, str(self.root/'tokenizer.json'): '2'*64}
        plan = {'artifact_kind': readiness.benchmark.VERSION, 'expires_at': '2099-01-01T00:00:00Z',
            'source_directory': str(source), 'request': request, 'request_sha256': digest(request),
            'model': {'name': metadata['model'], 'revision': metadata['revision'], 'threshold': .8, 'device': 'cpu'},
            'inputs': {str(p): sha(p) for p in (source/'plan.json', source/'report.json')},
            'model_sha256': weights, 'code_sha256': code, 'scope': 'synthetic evaluator test only'}
        results = []
        for i in range(40):
            raw = [6., 0., 0.] if i < 9 else [0., 6., 0.]
            exps = [math.exp(x - max(raw)) for x in raw]
            scores = {metadata['id2label'][str(j)]: v/sum(exps) for j, v in enumerate(exps)}
            pair = {'id': 'e', 'errors': [], 'raw': raw, 'scores': scores,
                    'relation': readiness.local_nli.decide(scores)}
            results.append({'id': str(i), 'pairs': [pair], **readiness.evidence_nli.aggregate([pair])})
        result = {'metadata': metadata, 'results': results, 'forward_pairs': 40}
        write(self.directory/'plan.json', plan); write(self.directory/'result.json', result)
        write(self.directory/'report.json', readiness.benchmark.summarize(plan, result))
        write(self.directory/'completed.json', {k + '_sha256': sha(self.directory/(k + '.json')) for k in ('plan', 'result', 'report')})
        patch.object(readiness, 'FIXED_BENCHMARK_BINDINGS', read_json(self.directory/'completed.json')).start()
        self.current = {'code_sha256': code, 'model_files': weights,
            'classifier': {'name': metadata['model'], 'revision': metadata['revision'], 'weights_sha256': '1'*64,
                'runtime_sha256': digest({p: code[p] for p in relevant[:2]})}}
        self.metadata = metadata

    def test_replays_all_fixed_rows_without_loading_models(self):
        with patch.object(readiness.local_nli, 'LocalNLI', side_effect=AssertionError('No model loads')):
            result = readiness.replay_benchmark(self.directory, self.current, [{'record': {'metadata': self.metadata}}])
        self.assertTrue(result['passed']); self.assertEqual(result['supported_kept'], 9)
        self.assertEqual(result['unsupported_false_support'], 0)
        self.assertFalse(result['fresh_inference']); self.assertEqual(result['new_model_calls'], 0)

    def test_changed_model_relevant_code_and_actual_runtime_are_rejected(self):
        current = deepcopy(self.current); current['classifier']['revision'] = 'different'
        with self.assertRaisesRegex(ValueError, 'model differ'): readiness.replay_benchmark(self.directory, current, [])
        current = deepcopy(self.current); current['code_sha256']['src/commentscope/providers/local_nli.py'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'decision code'): readiness.replay_benchmark(self.directory, current, [])
        metadata = deepcopy(self.metadata); metadata['torch'] = 'another-runtime'
        with self.assertRaisesRegex(ValueError, 'Actual fact-check runtime'):
            readiness.replay_benchmark(self.directory, self.current, [{'record': {'metadata': metadata}}])

    def test_changed_fixed_result_or_plan_not_accepted_as_new_benchmark(self):
        path = self.directory/'result.json'; value = read_json(path); value['results'].pop()
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'identity or completion'):
            readiness.replay_benchmark(self.directory, self.current, [])
        with patch.object(readiness, 'FIXED_BENCHMARK_BINDINGS', {'different_predefined_benchmark': True}):
            with self.assertRaisesRegex(ValueError, 'identity or completion'):
                readiness.replay_benchmark(self.directory, self.current, [])

    def test_rebinding_a_changed_result_does_not_replace_the_frozen_baseline(self):
        path = self.directory/'result.json'; value = read_json(path)
        value['forward_pairs'] = 999; path.write_text(json.dumps(value))
        completed = read_json(self.directory/'completed.json'); completed['result_sha256'] = sha(path)
        (self.directory/'completed.json').write_text(json.dumps(completed))
        with self.assertRaisesRegex(ValueError, 'identity or completion'):
            readiness.replay_benchmark(self.directory, self.current, [])


if __name__ == '__main__': unittest.main()
