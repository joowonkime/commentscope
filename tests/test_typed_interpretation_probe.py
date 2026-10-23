import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import typed_interpretation_probe as probe
from commentscope.factory import typed_interpretation_v2 as v2
from test_typed_interpretation_v2 import source, claim, output


class TypedProbeTests(unittest.TestCase):
    def test_replay_dispatches_frozen_v2_without_provider_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for name, value in {'plan.json': {'contract': v2.VERSION},
                'sources.json': [source('Continue.')],
                'output.json': {'cases': [output([claim('Continue.')])]}}.items():
                probe.write(run / name, value)
            (run / 'events.jsonl').write_text(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 1, 'output_tokens': 1}}))
            with patch.object(probe.subprocess, 'run') as provider, contextlib.redirect_stdout(io.StringIO()):
                probe.replay(run)
                provider.assert_not_called()
            record = probe.read(run / 'binding-validation.json')['records'][0]
            self.assertEqual(record['artifact_kind'], v2.VERSION)

    def test_existing_start_marker_prevents_repeat_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp); probe.write(run / 'freeze.json', {'code': {}, 'files': {}})
            probe.write(run / 'started.json', {'requests': 1})
            with patch.object(probe, 'code_freeze', return_value={}), patch.object(probe.subprocess, 'run') as provider:
                with self.assertRaises(FileExistsError): probe.execute(run)
                provider.assert_not_called()

    def test_code_change_blocks_execution_before_start_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp); probe.write(run / 'freeze.json', {'code': {'module': 'old'}, 'files': {}})
            with patch.object(probe, 'code_freeze', return_value={'module': 'new'}), patch.object(probe.subprocess, 'run') as provider:
                with self.assertRaisesRegex(ValueError, 'Frozen'): probe.execute(run)
                provider.assert_not_called()
            self.assertFalse((run / 'started.json').exists())


if __name__ == '__main__': unittest.main()
