import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import release_client as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.preview = Path(self.tmp.name) / "preview"
        patcher = patch.object(release, "PREVIEW", self.preview)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.key = b"AI" + b"za" + b"x" * 35
        self.template = b'const browserKey="' + release.MARKER + b'";'
        self.script = self.template.replace(release.MARKER, self.key)
        self.route = "/assets/index-test.js"
        self.manifest = {"entry_script": self.route, "assets": {self.route: release.digest(self.script)}}

    def test_prepare_restores_verified_bytes_and_reuses_them_offline(self):
        with patch.dict(os.environ, {"REVIEW_FIREBASE_WEB_API_KEY": ""}):
            with patch.object(release, "fetch", return_value=self.script) as fetch:
                release.prepare(self.manifest, {"/": b"home", self.route: self.template})
                fetch.assert_called_once_with(self.route)
            with patch.object(release, "fetch", side_effect=AssertionError("unexpected network request")):
                result = release.restore_script(self.manifest, self.template)
        self.assertEqual(result, self.script)
        self.assertEqual((self.preview / "assets" / "index-test.js").read_bytes(), self.script)

    def test_incorrect_configuration_does_not_replace_existing_preview(self):
        self.preview.mkdir()
        (self.preview / "index.html").write_bytes(b"saved")
        with patch.dict(os.environ, {"REVIEW_FIREBASE_WEB_API_KEY": "incorrect"}):
            with self.assertRaisesRegex(ValueError, "configuration unavailable"):
                release.prepare(self.manifest, {"/": b"changed", self.route: self.template})
        self.assertEqual((self.preview / "index.html").read_bytes(), b"saved")
        self.assertFalse((self.preview / "assets").exists())

    def test_local_browser_configuration_requires_the_deployed_scripts_hash(self):
        with patch.dict(os.environ, {"REVIEW_FIREBASE_WEB_API_KEY": self.key.decode()}):
            self.assertEqual(release.restore_script(self.manifest, self.template), self.script)
            with self.assertRaises(ValueError):
                release.restore_script(self.manifest, self.template + b"modified")
