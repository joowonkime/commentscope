from contextlib import nullcontext
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import resource_profile_probe as probe


class ResourceProfileProbeTests(unittest.TestCase):
    def execute(self, *, call_error=False, binding_error=False):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name)
        request = {'system': 'synthetic', 'data': {}, 'schema': {}, 'max_tokens': 100}
        plan = {'artifact_kind': probe.VERSION, 'inputs': {}, 'code_sha256': {},
                'deployment': {'server': {'path': 'server', 'sha256': 'hash'},
                               'models': {'baseline': {'path': 'model', 'sha256': 'hash'}}},
                'budget': {'ledger': 'unused', 'cycle_id': 'synthetic'},
                'requests': [{'id': str(i), 'source': {}, 'request': request, 'request_sha256': digest(request)} for i in range(6)]}
        write(directory/'plan.json', plan)
        write(directory/'server/resources/000001.json', {'observation': {
            'available_mb': 8000, 'committed_bytes': 36*1024**3, 'commit_limit': 38*1024**3,
            'disk_free_bytes': 18*1024**3, 'commit_percent': 95}, 'stop_reasons': []})
        runner = Mock(plan_sha=sha(directory/'plan.json'), started=time.monotonic())
        runner.call.return_value = {'errors': ['transport'] if call_error else [], 'output': {}}
        budget = Mock(); budget.summary.return_value = {'calls': []}
        with patch.object(probe, 'file_hash', return_value='hash'), patch.object(probe, 'Runner', return_value=runner), \
             patch.object(probe, 'InferenceBudget', return_value=budget), \
             patch.object(probe, 'owned_server', return_value=nullcontext()), \
             patch.object(probe.frames, 'bind', side_effect=ValueError if binding_error else None, return_value={}):
            probe.run(directory)
        return read_json(directory/'completed.json'), runner

    def test_execution_qualification_is_not_quality_approval(self):
        report, runner = self.execute()
        self.assertTrue(report['eligible_for_whole_corpus_trial'])
        self.assertFalse(report['quality_gate_passed'])
        self.assertFalse(report['fresh_corpus_analysis'])
        self.assertEqual(runner.call.call_count, 6)
        self.assertEqual(report['maximum_observed_commit_percent'], 95)

    def test_call_error_or_invalid_frame_prevents_execution_qualification(self):
        for kwargs in ({'call_error': True}, {'binding_error': True}):
            report, _ = self.execute(**kwargs)
            self.assertFalse(report['eligible_for_whole_corpus_trial'])

    def test_existing_probe_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): probe.prepare(Path(tmp), Path('absent'), Path('absent'))


if __name__ == '__main__': unittest.main()
