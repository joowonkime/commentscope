from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from commentscope.factory.automatic_contract import digest
from commentscope.storage import write_json_exclusive
from experiments.grounded_core_probe import reuse_raw, no_model
from experiments.grounded_core_sample import select


class GroundedCoreDiagnosticTests(unittest.TestCase):
    def test_raw_reuse_checks_configuration_and_content_hashes(self):
        critical = ['src/commentscope/factory/automatic.py', 'src/commentscope/providers/local_llama.py',
                    'src/commentscope/providers/local_nli.py', 'experiments/claim_support_probe.py']
        manifest = {k: 'fixed' for k in ['inputs', 'model', 'nli', 'runtime', 'prompts']}
        manifest['code_sha256'] = {p: 'fixed' for p in critical}
        with tempfile.TemporaryDirectory() as d:
            old, new = Path(d)/'old', Path(d)/'new'
            for folder in ['llm', 'nli']: write_json_exclusive(old/folder/'manifest.json', manifest)
            request, result = {'SOURCE': 'Source', 'TARGET': 'Target'}, {'errors': [], 'output': None}
            record = {'request': request, 'result': result, 'result_sha256': digest(result)}
            write_json_exclusive(old/'llm'/('call-'+digest(request)+'.json'), record)
            self.assertEqual(reuse_raw(old, new, manifest), 1)
            self.assertEqual(reuse_raw(old, new, manifest), 1)
            changed = deepcopy(manifest); changed['runtime'] = 'different'
            with self.assertRaises(ValueError): reuse_raw(old, new, changed)
            changed = deepcopy(manifest); changed['code_sha256'][critical[0]] = 'different'
            with self.assertRaises(ValueError): reuse_raw(old, new, changed)

    def test_new_source_selection_is_bounded_stable_and_excludes_prior_controls(self):
        sources = [SimpleNamespace(comment_id=str(i)) for i in range(30)]
        baseline = {'records': [{'source_comment_id': '0'}, {'source_comment_id': '1'}]}
        full = {'groups': [{'member_ids': ['u']}], 'units': [{'claim_id': 'u', 'source_comment_id': '2'}]}
        selected = select(SimpleNamespace(comments=sources), baseline, full)
        self.assertEqual(len(selected), 12)
        self.assertFalse({'0', '1', '2'} & {s.comment_id for s in selected})
        self.assertEqual(selected, select(SimpleNamespace(comments=list(reversed(sources))), baseline, full))

    def test_readonly_miss_raises_nonserialized_error(self):
        with self.assertRaises(RuntimeError): no_model()


if __name__ == '__main__': unittest.main()
