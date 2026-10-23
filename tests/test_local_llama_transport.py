import json
from io import BytesIO
import unittest
from unittest.mock import Mock, patch

from commentscope.providers import local_llama


class LocalTransportTests(unittest.TestCase):
    def test_explicit_deadline_does_not_change_payload_or_destination(self):
        opener = Mock()
        opener.open.side_effect = [BytesIO(b'{}'), BytesIO(b'{}')]
        with patch.object(local_llama, 'build_opener', return_value=opener):
            local_llama.generate('system', {'text': 'complete'}, {}, max_tokens=5120)
            local_llama.generate('system', {'text': 'complete'}, {}, max_tokens=5120, timeout_seconds=1800)
        a, b = opener.open.call_args_list
        self.assertEqual(a.kwargs['timeout'], 180)
        self.assertEqual(b.kwargs['timeout'], 1800)
        self.assertEqual(a.args[0].data, b.args[0].data)
        self.assertEqual(b.args[0].full_url, 'http://127.0.0.1:8091/v1/chat/completions')
        self.assertEqual(json.loads(b.args[0].data)['max_tokens'], 5120)

    def test_invalid_deadline_fails_before_transport(self):
        with patch.object(local_llama, 'build_opener') as factory:
            for invalid in (None, True, 0, -1, float('nan'), float('inf')):
                with self.assertRaises(ValueError):
                    local_llama.generate('system', {}, {}, timeout_seconds=invalid)
            factory.assert_not_called()
