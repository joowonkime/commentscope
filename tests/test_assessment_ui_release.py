from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deploy.assessment_ui import ASSETS, activate, package


@unittest.skipUnless(os.name == 'posix', 'Public nginx host runs Linux')
class AssessmentUiTests(unittest.TestCase):
    def test_ui_changes_can_roll_back_without_replacing_the_backend_or_ledger(self):
        with TemporaryDirectory() as work:
            directory = Path(work)
            root = directory / 'nginx'
            baseline = directory / 'reference'
            original = package('HEAD', baseline)
            frozen = {name: (baseline / name).read_bytes() for name in ASSETS}
            ledger = directory / 'spend.sqlite'
            ledger.write_bytes(b'existing ledger')
            self.assertEqual(activate(baseline, root), original)

            updated = directory / 'update'
            updated.mkdir()
            revision = 'f' * 40
            hashes = {}
            for name, data in frozen.items():
                value = data + b'\n'
                (updated / name).write_bytes(value)
                hashes[name] = {'after': sha256(value).hexdigest()}
            (updated / 'static-manifest.json').write_text(json.dumps({'commit': revision, 'files': hashes}))
            self.assertEqual(activate(updated, root), revision)
            self.assertEqual(activate(updated, root), revision)
            self.assertEqual((root / 'current/mvp.js').read_bytes(), frozen['mvp.js'] + b'\n')

            (updated / 'mvp.js').write_bytes(b'damaged transfer')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                activate(updated, root)
            self.assertEqual((root / 'current').resolve().name, revision)
            self.assertEqual(activate(baseline, root), original)
            self.assertEqual({name: (baseline / name).read_bytes() for name in ASSETS}, frozen)
            self.assertEqual(ledger.read_bytes(), b'existing ledger')
