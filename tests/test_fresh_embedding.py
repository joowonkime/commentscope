from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from commentscope.factory.claim_clusters import sha
from commentscope.providers.fresh_embedding import VERSION, generate
from commentscope.storage import write_json_exclusive as write


class FreshEmbeddingTests(unittest.TestCase):
    def test_offline_adapter_preserves_snapshot_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path('tests/fixtures/synthetic-snapshot.json')
            output=Path(tmp)/'raw.json'
            def fake_run(snapshot,path,threshold):
                self.assertEqual(threshold,.45)
                write(path,{'snapshot_sha256':sha(source),'summary':{'source_count':3}})
            with patch('commentscope.cluster_baseline.run',fake_run), patch.dict('os.environ',{}):
                result=generate(VERSION,{'snapshot':str(source),'snapshot_sha256':sha(source),'output':str(output)}, {}, 1)
                self.assertTrue(result['fresh_embedding'])
                self.assertFalse(result['quality_gate_passed'])
                self.assertEqual(result['sha256'],sha(output))

    def test_changed_snapshot_rejected_before_model(self):
        with self.assertRaisesRegex(ValueError,'Snapshot changed'):
            generate(VERSION,{'snapshot':'tests/fixtures/synthetic-snapshot.json','snapshot_sha256':'0'*64,'output':'unused.json'}, {}, 1)

    def test_unknown_request_rejected(self):
        with self.assertRaises(ValueError):generate('other',{}, {}, 1)
