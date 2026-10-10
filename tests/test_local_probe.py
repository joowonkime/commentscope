"""Offline runner checks; fake model responses do not measure model quality."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'experiments/local_claim_probe.py'
FIXTURE = ROOT / 'tests/fixtures/synthetic-snapshot.json'


class LocalProbeTests(unittest.TestCase):
    def execute(self, output, extra=()):
        args = [str(SCRIPT), '--snapshot', str(FIXTURE), '--output', str(output),
                '--model-label', 'fake', '--model-revision', 'test', '--runtime', 'test',
                '--limit', '2', *extra]
        response = {'choices': [{'message': {'content': json.dumps({
            'eligibility': 'non_substantive', 'claims': []})}, 'finish_reason': 'stop'}]}
        opener = MagicMock()
        opener.open.side_effect = lambda *a, **k: io.BytesIO(json.dumps(response).encode())
        with patch('sys.argv', args), patch('urllib.request.build_opener', return_value=opener), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(SCRIPT), run_name='__main__')
        return opener

    def test_manifest_and_html_are_written_without_claim_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'probe.json'
            opener = self.execute(output)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['summary']['contract_pass'], 2)
            self.assertEqual(report['generation_schema_version'], 'claim-generation-0.3')
            self.assertEqual(report['semantic_review_status'], 'pending')
            self.assertTrue(output.with_suffix('.html').exists())
            self.assertEqual(opener.open.call_count, 2)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:8091/v1/chat/completions')

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'probe.json'
            self.execute(output)
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                self.execute(output)
            self.assertEqual(output.read_bytes(), original)

    def test_exclude_and_replay_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / 'first.json'
            second = Path(tmp) / 'second.json'
            third = Path(tmp) / 'third.json'
            self.execute(first)
            self.execute(second, ['--exclude-report', str(first)])
            self.execute(third, ['--replay-report', str(first)])
            def ids(path):
                return [r['comment_id'] for r in json.loads(path.read_text(encoding='utf-8'))['results']]
            self.assertFalse(set(ids(first)) & set(ids(second)))
            self.assertEqual(ids(first), ids(third))
