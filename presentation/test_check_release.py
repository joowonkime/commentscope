from hashlib import sha256
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_release as release


class ReleaseChecks(unittest.TestCase):
    def test_local_comparison_detects_content_and_file_list_changes(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(release, "FRONTEND", Path(folder)):
            dist = Path(folder) / "dist"
            dist.mkdir()
            index = dist / "index.html"
            index.write_bytes(b"published")
            routes = {"/": sha256(index.read_bytes()).hexdigest()}
            release.check_dist(routes)
            index.write_bytes(b"another build")
            with self.assertRaisesRegex(ValueError, "differs at /"):
                release.check_dist(routes)
            (dist / "unexpected.js").write_bytes(b"extra")
            with self.assertRaisesRegex(ValueError, "paths differ"):
                release.check_dist(routes)

    def test_explicit_build_settings_work_offline(self):
        settings = dict.fromkeys(release.FIELDS, "local-test-value")
        with patch.dict(os.environ, settings), patch.object(release, "fetch", side_effect=AssertionError):
            env = release.public_build_environment({})
        self.assertEqual({name: env[name] for name in settings}, settings)

    def test_public_settings_must_come_from_the_recorded_script(self):
        data = b'{apiKey:"example",authDomain:"test.invalid",projectId:"demo",appId:"fixture"}'
        record = {"entry_script": "/assets/test.js", "assets": {"/assets/test.js": sha256(data).hexdigest()}}
        with patch.dict(os.environ, {}, clear=True), patch.object(release, "fetch", return_value=data):
            env = release.public_build_environment(record)
            self.assertEqual(env["VITE_FIREBASE_PROJECT_ID"], "demo")
        with patch.dict(os.environ, {}, clear=True), patch.object(release, "fetch", return_value=data + b"changed"):
            with self.assertRaisesRegex(ValueError, "differs"):
                release.public_build_environment(record)
