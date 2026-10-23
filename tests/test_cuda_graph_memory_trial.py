from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from commentscope.storage import write_json_exclusive as write
from experiments import cuda_graph_memory_trial as trial


class CudaGraphMemoryTrialTests(unittest.TestCase):
    def test_environment_is_restored_after_failure(self):
        with patch.dict(os.environ, {'GGML_CUDA_DISABLE_GRAPHS': 'old'}):
            with self.assertRaises(RuntimeError):
                with trial.environment(trial.ENVIRONMENT):
                    self.assertEqual(os.environ['GGML_CUDA_DISABLE_GRAPHS'], '1')
                    raise RuntimeError('test')
            self.assertEqual(os.environ['GGML_CUDA_DISABLE_GRAPHS'], 'old')

    def test_environment_does_not_leak_or_accept_other_changes(self):
        with patch.dict(os.environ, {}, clear=True):
            with trial.environment(trial.ENVIRONMENT): pass
            self.assertNotIn('GGML_CUDA_DISABLE_GRAPHS', os.environ)
            with self.assertRaises(ValueError):
                with trial.environment({'unrelated': '1'}): pass

    def test_short_trial_is_not_quality_or_corpus_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root/'server/resources/000001.json', {'observation': {
                'commit_limit': 8*1024**3, 'committed_bytes': 6*1024**3, 'available_mb': 8192}})
            result = trial.metrics(root, [{'errors': []}]*6, [])
            self.assertTrue(result['short_run_execution_viable'])
            self.assertFalse(result['quality_gate_passed'])
            self.assertFalse(result['fresh_corpus_analysis'])
            write(root/'server/resources/stop-requested.json', {'stop_reasons': ['low_host_commit_headroom']})
            self.assertFalse(trial.metrics(root, [{'errors': []}]*6, [])['short_run_execution_viable'])

    def test_missing_observation_or_failed_output_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(trial.metrics(root, [{'errors': []}]*6, [])['short_run_execution_viable'])
            write(root/'server/resources/000001.json', {'observation': {
                'commit_limit': 8*1024**3, 'committed_bytes': 6*1024**3, 'available_mb': 8192}})
            self.assertFalse(trial.metrics(root, [{'errors': []}]*5, [])['short_run_execution_viable'])
            self.assertFalse(trial.metrics(root, [{'errors': ['call_error']}]*6, [])['short_run_execution_viable'])
            self.assertFalse(trial.metrics(root, [{'errors': []}]*6, ['A'])['short_run_execution_viable'])


if __name__ == '__main__': unittest.main()
