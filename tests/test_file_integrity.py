import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope import file_integrity as integrity


class FileIntegrityTests(unittest.TestCase):
    def check_file(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.bin'
            path.write_bytes(data)
            before = path.stat()
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded read')):
                actual = integrity.file_sha256(path)
            self.assertEqual(actual, hashlib.sha256(data).hexdigest())
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        return actual

    def test_empty_small_and_multichunk_hashes_without_whole_file_read(self):
        for data in (b'', b'abc', b'0123456789' * 220000):
            with self.subTest(size=len(data)):
                self.check_file(data)

    def test_large_file_advice_covers_read_ranges_without_changing_data(self):
        with patch.object(integrity, 'LARGE_FILE_BYTES', 1), \
             patch.object(integrity, 'CACHE_RELEASE_BYTES', integrity.CHUNK_BYTES), \
             patch.object(os, 'POSIX_FADV_DONTNEED', 4, create=True), \
             patch.object(os, 'posix_fadvise', create=True) as advice:
            self.check_file(b'a' * (2 * integrity.CHUNK_BYTES + 17))
        self.assertEqual([call.args[1:] for call in advice.call_args_list],
                         [(0, integrity.CHUNK_BYTES, 4),
                          (integrity.CHUNK_BYTES, integrity.CHUNK_BYTES, 4),
                          (2 * integrity.CHUNK_BYTES, 17, 4)])

    def test_missing_or_failed_advice_does_not_skip_verification(self):
        with patch.object(integrity, 'LARGE_FILE_BYTES', 1), \
             patch.object(integrity, 'CACHE_RELEASE_BYTES', integrity.CHUNK_BYTES), \
             patch.object(os, 'POSIX_FADV_DONTNEED', 4, create=True):
            with patch.object(os, 'posix_fadvise', None, create=True):
                self.check_file(b'x' * (integrity.CHUNK_BYTES + 1))
            with patch.object(os, 'posix_fadvise', side_effect=OSError('unsupported'), create=True) as advice:
                self.check_file(b'x' * (2 * integrity.CHUNK_BYTES + 1))
                self.assertEqual(advice.call_count, 1)
            with patch.object(os, 'posix_fadvise', side_effect=OSError('unsupported'), create=True):
                self.check_file(b'tail only')

    def test_missing_file_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                integrity.file_sha256(Path(directory) / 'missing')
