from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from commentscope.product.analysis import Analysis, from_factory
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from experiments.grounding_contract_demo import fixture


class ProductAnalysisTests(unittest.TestCase):
    def test_catalog_preserves_all_profiles_and_never_qualifies_development_input(self):
        bundle = fixture(); before = deepcopy(bundle)
        analysis = Analysis(bundle, {'source': 'synthetic-fixture'})
        value = analysis.public()
        self.assertEqual(len(value['perspectives']), 1)
        self.assertEqual(value['status'], 'experimental')
        self.assertEqual(value['semantic_reliability'], 'not_assessed')
        self.assertFalse(value['quality_gate_passed'])
        self.assertEqual(bundle, before)
        self.assertEqual(analysis.source(bundle['sources'][0]['id'])['text'], bundle['sources'][0]['text'])

    def test_loader_binds_plan_snapshot_output_and_all_compiler_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); bundle = fixture()
            write(root/'snapshot.json', {'synthetic': True})
            write(root/'plan.json', {'snapshot': str(root/'snapshot.json'),
                'snapshot_sha256': sha(root/'snapshot.json'), 'quality_gate_passed': False})
            generated = {'bundle': bundle, 'quality_gate_passed': False}
            write(root/'artifacts/agent-inputs.json', generated)
            write(root/'artifacts/output.json', {'agent_inputs': generated})
            registry = {s['id']: s for s in bundle['sources']}
            with patch('commentscope.product.analysis.load_snapshot', return_value=Mock(snapshot=object())), \
                 patch('commentscope.product.analysis.source_registry', return_value=registry):
                analysis = from_factory(root)
                self.assertEqual(len(analysis.compiled['profiles']), 1)
                self.assertTrue(analysis.provenance['automatically_generated'])
                self.assertFalse(analysis.public()['quality_gate_passed'])
                (root/'snapshot.json').write_text('{}')
                with self.assertRaises(ValueError): from_factory(root)

    def test_changed_generation_output_or_source_is_not_published(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); bundle = fixture()
            write(root/'snapshot.json', {'synthetic': True})
            write(root/'plan.json', {'snapshot': str(root/'snapshot.json'),
                'snapshot_sha256': sha(root/'snapshot.json')})
            write(root/'artifacts/agent-inputs.json', {'bundle': bundle})
            write(root/'artifacts/output.json', {'agent_inputs': {'bundle': {}}})
            with self.assertRaises(ValueError): from_factory(root)
