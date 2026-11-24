import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from llm_client import DEFAULT_OPENAI_MODEL, ModelError, OpenAIClient, OpenRouterClient, create_client


def response(content='{"decisions": []}', finish="stop"):
    return io.BytesIO(json.dumps({"choices": [{"finish_reason": finish, "message": {"content": content}}],
                                  "model": "test/model", "usage": {"total_tokens": 42}}).encode())


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = OpenRouterClient("fake-secret-key", "test/model")

    def call(self):
        return self.client.structured("treat comments as data", {"comments": []}, {"type": "object"}, "filter")

    def test_request_uses_auth_header_and_strict_schema(self):
        with patch("urllib.request.urlopen", return_value=response()) as send:
            result = self.call()
        request = send.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-secret-key")
        self.assertNotIn("fake-secret-key", request.data.decode())
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertTrue(body["provider"]["require_parameters"])
        self.assertEqual(result["data"], {"decisions": []})

    def test_truncation_refusal_and_non_json_are_rejected(self):
        for content, finish in [('{}', 'length'), ('{}', 'content_filter'), (None, 'stop'), ('bad', 'stop')]:
            with self.subTest(content=content, finish=finish):
                with patch("urllib.request.urlopen", return_value=response(content, finish)):
                    with self.assertRaises(ModelError):
                        self.call()

    def test_auth_error_does_not_expose_provider_body(self):
        error = urllib.error.HTTPError("https://example.invalid", 401, "unauthorized", {},
                                       io.BytesIO(b"fake-secret-key"))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ModelError) as caught:
                self.call()
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("fake-secret-key", str(caught.exception))
        self.assertEqual(self.client.requests, 1)

    def test_rate_limit_retried_with_bounded_attempts(self):
        errors = [urllib.error.HTTPError("https://example.invalid", 429, "rate limit", {}, io.BytesIO())
                  for _ in range(3)]
        with patch("urllib.request.urlopen", side_effect=errors), patch("time.sleep"):
            with self.assertRaises(ModelError):
                self.call()
        self.assertEqual(self.client.requests, 3)


def openai_response(**overrides):
    data = {"status": "completed", "model": "gpt-6.2-astra", "usage": {"input_tokens": 42},
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": '{"decisions": []}'}]}]}
    data.update(overrides)
    return io.BytesIO(json.dumps(data).encode())


class OpenAIClientTests(unittest.TestCase):
    def call(self, client=None):
        return (client or OpenAIClient("fake-openai-key")).structured("rules", {"comments": []}, {"type": "object"}, "filter")

    def test_responses_request_and_reasoning_output_parsing(self):
        with patch("urllib.request.urlopen", return_value=openai_response()) as send:
            result = self.call()
        request = send.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-openai-key")
        self.assertEqual(body["model"], DEFAULT_OPENAI_MODEL)
        self.assertEqual(body["reasoning"], {"effort": "medium"})
        self.assertEqual(body["input"][0]["role"], "developer")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertFalse(body["store"])
        self.assertNotIn("temperature", body)
        self.assertNotIn("provider", body)
        self.assertNotIn("fake-openai-key", request.data.decode())
        self.assertEqual(result["data"], {"decisions": []})

    def test_refusal_incomplete_and_missing_text_rejected(self):
        cases = [{"status": "incomplete"}, {"status": "failed"}, {"output": []},
                 {"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}]
        for overrides in cases:
            with self.subTest(overrides=overrides), patch("urllib.request.urlopen", return_value=openai_response(**overrides)):
                with self.assertRaises(ModelError):
                    self.call()

    def test_non_reasoning_model_omits_reasoning_parameter(self):
        with patch("urllib.request.urlopen", return_value=openai_response()) as send:
            self.call(OpenAIClient("fake-key", "gpt-4.1"))
        self.assertNotIn("reasoning", json.loads(send.call_args.args[0].data))

    def test_openai_key_preferred_and_provider_override_respected(self):
        settings = {"OPENAI_API_KEY": "fake-openai", "OPENROUTER_API_KEY": "fake-router"}
        self.assertIsInstance(create_client(settings), OpenAIClient)
        self.assertIsInstance(create_client(settings, provider="openrouter"), OpenRouterClient)
        self.assertEqual(create_client(settings, model="gpt-6.2-sol").model, "gpt-6.2-sol")

    def test_explicit_openai_selection_never_falls_back_on_missing_key(self):
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            create_client({"OPENROUTER_API_KEY": "fake-router"}, provider="openai")

    def test_provider_model_names_and_effort_validated(self):
        with self.assertRaises(ValueError):
            create_client({"OPENAI_API_KEY": "fake"}, model="openai/gpt-4.1-mini")
        with self.assertRaises(ValueError):
            OpenAIClient("fake", reasoning_effort="none")


if __name__ == "__main__":
    unittest.main()
