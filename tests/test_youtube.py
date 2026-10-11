import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from commentscope.cli import main
from commentscope.errors import PipelineError
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.ingestion.youtube import CollectionConfig, collect_youtube, video_id_from_input
from commentscope.ingestion.youtube_client import YouTubeClient, _NoRedirect

VIDEO = "AbCdEfGhI_1"
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
TEST_KEY = "synthetic-key-not-a-credential"


def comment(cid, parent=None):
    snippet = {"textDisplay": f"API text <not-html> &amp; {cid} 한국어", "publishedAt": "2026-10-01T00:00:00Z",
               "likeCount": 2, "authorDisplayName": "do-not-save-this-author", "textOriginal": "not-requested"}
    if parent is not None:
        snippet["parentId"] = parent
    return {"id": cid, "snippet": snippet}


def thread(cid, replies=0):
    return {"id": "thread-resource-" + cid, "snippet": {
        "videoId": VIDEO, "totalReplyCount": replies, "topLevelComment": comment(cid)},
        "replies": {"comments": [comment("ignore-inline-reply", cid)]}}


def page(items, token=None):
    result = {"items": items}
    if token is not None:
        result["nextPageToken"] = token
    return result


def video():
    return page([{"id": VIDEO, "snippet": {"title": "Synthetic collection test"}}])


def http_error(status, reason="unknown"):
    body = json.dumps({"error": {"message": TEST_KEY, "errors": [{"reason": reason}]}}).encode()
    return HTTPError("https://upstream.invalid/?secret=" + TEST_KEY, status, TEST_KEY, {}, io.BytesIO(body))


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        if not self.responses:
            raise AssertionError("unexpected API call")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode("utf-8"))


def client_for(responses, **kwargs):
    opener = FakeOpener(responses)
    sleeps = []
    client = YouTubeClient(TEST_KEY, opener=opener, sleep=sleeps.append, **kwargs)
    return client, opener, sleeps


class VideoInputTests(unittest.TestCase):
    def test_accepts_supported_url_forms(self):
        for value in [VIDEO, " " + VIDEO + " ", f"https://www.youtube.com/watch?v={VIDEO}&t=30",
                      f"https://youtu.be/{VIDEO}?si=share", f"https://m.youtube.com/watch?v={VIDEO}",
                      f"https://www.youtube.com/shorts/{VIDEO}", f"https://youtube.com/live/{VIDEO}",
                      f"https://www.youtube.com/embed/{VIDEO}"]:
            with self.subTest(value=value):
                self.assertEqual(video_id_from_input(value), VIDEO)

    def test_rejects_unrelated_hosts_ambiguous_ids_and_nonvideo_urls(self):
        for value in ["", "bad", "https://evil.example/watch?v=" + VIDEO,
                      "https://youtube.com.evil.example/watch?v=" + VIDEO,
                      "https://youtube.com@evil.example/watch?v=" + VIDEO,
                      f"https://youtube.com/watch?v={VIDEO}&v={VIDEO}",
                      f"https://youtube.com:443/watch?v={VIDEO}", "https://youtube.com/playlist?list=x",
                      "file:///etc/passwd", "https://youtu.be/" + VIDEO + "/extra"]:
            with self.subTest(value=value):
                with self.assertRaises(PipelineError) as caught:
                    video_id_from_input(value)
                self.assertEqual(caught.exception.code, "INVALID_VIDEO_INPUT")


class TransportTests(unittest.TestCase):
    def test_key_is_in_header_not_url_and_only_read_resources_are_allowed(self):
        client, opener, _ = client_for([page([])])
        client.get("videos", {"id": VIDEO, "part": "snippet"})
        request = opener.calls[0]
        self.assertEqual(urlsplit(request.full_url).hostname, "www.googleapis.com")
        self.assertEqual(request.get_method(), "GET")
        self.assertNotIn(TEST_KEY, request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), TEST_KEY)
        self.assertNotIn(TEST_KEY, repr(client))
        for resource, params in [("https://evil.example", {}), ("videos", {"key": TEST_KEY})]:
            with self.assertRaises(PipelineError):
                client.get(resource, params)
        self.assertEqual(len(opener.calls), 1)

    def test_redirects_cannot_forward_key(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.example"))

    def test_transient_errors_retry_and_count_against_budget(self):
        client, opener, sleeps = client_for([http_error(503), URLError(TEST_KEY), page([])])
        self.assertEqual(client.get("videos", {}), page([]))
        self.assertEqual(client.requests_used, 3)
        self.assertEqual(sleeps, [1, 2])

    def test_configured_budget_bounds_retries(self):
        client, opener, _ = client_for([http_error(500)], max_requests=1)
        with self.assertRaises(PipelineError) as caught:
            client.get("videos", {})
        self.assertEqual(caught.exception.code, "REQUEST_BUDGET_EXHAUSTED")
        self.assertEqual(len(opener.calls), 1)

    def test_error_mapping_does_not_expose_key_or_upstream_body(self):
        cases = [(403, "commentsDisabled", "COMMENTS_DISABLED"),
                 (403, "quotaExceeded", "YOUTUBE_QUOTA_EXCEEDED"),
                 (400, "keyInvalid", "YOUTUBE_AUTH_ERROR"),
                 (403, "accessNotConfigured", "YOUTUBE_AUTH_ERROR"),
                 (404, "videoNotFound", "YOUTUBE_NOT_FOUND"),
                 (403, "forbidden", "YOUTUBE_REQUEST_REJECTED")]
        for status, reason, code in cases:
            with self.subTest(code=code):
                client, opener, sleeps = client_for([http_error(status, reason)])
                with self.assertRaises(PipelineError) as caught:
                    client.get("videos", {})
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(TEST_KEY, str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                self.assertEqual(sleeps, [])

    def test_network_error_after_retries_is_sanitized(self):
        for failure in [URLError(TEST_KEY), IncompleteRead(TEST_KEY.encode())]:
            with self.subTest(failure=type(failure).__name__):
                client, _, _ = client_for([failure] * 3)
                with self.assertRaises(PipelineError) as caught:
                    client.get("videos", {})
                self.assertEqual(caught.exception.code, "YOUTUBE_UNAVAILABLE")
                self.assertTrue(caught.exception.retryable)
                self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_invalid_responses_fail_without_retry(self):
        for response in [b'not JSON', b'\xff', [], {"error": {"message": TEST_KEY}}]:
            with self.subTest(response=response):
                client, _, sleeps = client_for([response])
                with self.assertRaises(PipelineError) as caught:
                    client.get("videos", {})
                self.assertEqual(caught.exception.code, "INVALID_API_RESPONSE")
                self.assertEqual(sleeps, [])

    def test_key_and_transport_config_validation(self):
        for key in ["", " ", "key\nheader", "한글"]:
            with self.subTest(key=key):
                with self.assertRaises(PipelineError):
                    YouTubeClient(key)
        for kwargs in [{"max_requests": 0}, {"max_requests": True}, {"timeout": float("nan")},
                       {"timeout": 0}, {"retries": 5}]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(PipelineError):
                    YouTubeClient(TEST_KEY, **kwargs)


class CollectionTests(unittest.TestCase):
    def test_mixed_sampling_pagination_replies_and_snapshot_compatibility(self):
        responses = [video(), page([thread("a", 2)], "top-2"), page([thread("b")]),
                     page([thread("a", 2), thread("c", 1)]),
                     page([comment("a1", "a")], "reply-2"), page([comment("c1", "c")]),
                     page([comment("a2", "a")])]
        client, opener, _ = client_for(responses)
        result = collect_youtube(VIDEO, client, CollectionConfig(max_comments=10, top_level_limit=4), captured_at=NOW)
        by_id = {c.comment_id: c for c in result.snapshot.comments}
        self.assertEqual(set(by_id), {"a", "b", "c", "a1", "a2", "c1"})
        self.assertEqual([o.method for o in by_id["a"].sampling_origins], ["youtube:relevance", "youtube:time"])
        self.assertEqual([o.rank for o in by_id["b"].sampling_origins], [2])
        self.assertEqual(by_id["a1"].parent_id, "a")
        self.assertEqual(by_id["a"].replies_status, "complete")
        self.assertEqual(by_id["b"].replies_status, "complete")
        self.assertEqual(by_id["c"].replies_status, "complete")
        self.assertEqual(by_id["a1"].replies_status, "unknown")
        self.assertEqual(by_id["a"].text_original, comment("a")["snippet"]["textDisplay"])
        self.assertEqual(by_id["a"].language.tag, "und")
        self.assertEqual(result.snapshot.usage.expires_at, "2026-11-09T00:00:00Z")
        self.assertEqual(result.report["requests_used"], 7)
        self.assertFalse(result.report["target_reached"])
        serialized = json.dumps(result.snapshot.to_dict(), ensure_ascii=False)
        for excluded in [TEST_KEY, "do-not-save-this-author", "not-requested", "ignore-inline-reply"]:
            self.assertNotIn(excluded, serialized)
        queries = [parse_qs(urlsplit(call.full_url).query) for call in opener.calls]
        self.assertEqual(queries[2]["pageToken"], ["top-2"])
        self.assertEqual([q["parentId"][0] for q in queries if "parentId" in q], ["a", "c", "a"])
        self.assertTrue(all(q.get("textFormat") == ["plainText"] for q in queries[1:]))
        self.assertTrue(all("authorDisplayName" not in q["fields"][0] for q in queries))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(serialized, encoding="utf-8")
            loaded = load_snapshot(path)
            self.assertEqual(len(normalize_snapshot(loaded.snapshot)), 6)

    def test_total_comment_limit_and_partial_thread_status(self):
        client, opener, _ = client_for([video(), page([thread("a", 10)]), page([thread("b", 10)]),
                                        page([comment("a1", "a")], "more")])
        result = collect_youtube(VIDEO, client, CollectionConfig(max_comments=3, top_level_limit=2))
        self.assertEqual(len(result.snapshot.comments), 3)
        self.assertIn("total_comment_limit", result.report["stop_reasons"])
        self.assertTrue(result.report["target_reached"])
        self.assertTrue(all(c.replies_status == "partial" for c in result.snapshot.comments[:2]))
        self.assertEqual(len(opener.calls), 4)

    def test_per_thread_reply_cap(self):
        client, _, _ = client_for([video(), page([thread("a", 2)]), page([comment("a1", "a")], "more")])
        result = collect_youtube(VIDEO, client, CollectionConfig(top_level_limit=1, replies_per_thread=1))
        self.assertEqual(result.snapshot.comments[0].replies_status, "partial")
        self.assertIn("per_thread_reply_limit", result.report["stop_reasons"])

    def test_request_budget_preserves_explicit_partial_sample(self):
        client, opener, _ = client_for([video(), page([thread("a", 1)]), page([thread("b", 1)])], max_requests=3)
        result = collect_youtube(VIDEO, client, CollectionConfig(top_level_limit=2))
        self.assertEqual(len(opener.calls), 3)
        self.assertEqual(len(result.snapshot.comments), 2)
        self.assertEqual(result.report["stop_reasons"], ["request_budget"])
        self.assertTrue(all(c.replies_status == "partial" for c in result.snapshot.comments))

    def test_disabled_reply_collection_does_not_claim_completeness(self):
        client, _, _ = client_for([video(), page([thread("a", 1)])])
        result = collect_youtube(VIDEO, client, CollectionConfig(top_level_limit=1, replies_per_thread=0))
        self.assertEqual(result.snapshot.comments[0].replies_status, "partial")
        self.assertIn("reply_collection_disabled", result.report["stop_reasons"])

    def test_missing_replies_count_is_not_treated_as_complete(self):
        client, _, _ = client_for([video(), page([thread("a", 2)]), page([comment("a1", "a")])])
        result = collect_youtube(VIDEO, client, CollectionConfig(top_level_limit=1))
        self.assertEqual(result.snapshot.comments[0].replies_status, "partial")
        self.assertIn("reply_count_changed_or_unavailable", result.report["stop_reasons"])

    def test_repeated_thread_or_reply_tokens_fail(self):
        cases = [
            (CollectionConfig(top_level_limit=8), [video(), page([thread("a")], "same"), page([thread("b")], "same")]),
            (CollectionConfig(top_level_limit=1), [video(), page([thread("a", 3)]),
             page([comment("a1", "a")], "same"), page([comment("a2", "a")], "same")]),
        ]
        for config, responses in cases:
            with self.subTest(config=config):
                client, _, _ = client_for(responses)
                with self.assertRaises(PipelineError) as caught:
                    collect_youtube(VIDEO, client, config)
                self.assertEqual(caught.exception.code, "INVALID_API_RESPONSE")

    def test_wrong_video_parent_or_reused_id_fails(self):
        wrong_thread = thread("a")
        wrong_thread["snippet"]["videoId"] = "another_vid"
        cases = [[video(), page([wrong_thread])],
                 [video(), page([thread("a", 1)]), page([comment("reply", "wrong")])],
                 [video(), page([thread("a", 1)]), page([comment("a", "a")])]]
        for responses in cases:
            with self.subTest(responses=responses):
                client, _, _ = client_for(responses)
                with self.assertRaises(PipelineError) as caught:
                    collect_youtube(VIDEO, client, CollectionConfig(top_level_limit=1))
                self.assertEqual(caught.exception.code, "INVALID_API_RESPONSE")

    def test_unavailable_video_and_comments_disabled(self):
        for responses, code in [([page([])], "YOUTUBE_NOT_FOUND"),
                                 ([video(), http_error(403, "commentsDisabled")], "COMMENTS_DISABLED")]:
            client, _, _ = client_for(responses)
            with self.assertRaises(PipelineError) as caught:
                collect_youtube(VIDEO, client)
            self.assertEqual(caught.exception.code, code)

    def test_empty_video_and_config_bounds(self):
        client, _, _ = client_for([video(), page([]), page([])])
        result = collect_youtube(VIDEO, client)
        self.assertEqual(len(result.snapshot.comments), 0)
        self.assertFalse(result.report["target_reached"])
        for kwargs in [{"max_comments": 10000}, {"max_comments": 0}, {"top_level_limit": False},
                       {"retention_days": 31}, {"replies_per_thread": -1}, {"primary_language": ""}]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(PipelineError):
                    collect_youtube(VIDEO, client, CollectionConfig(**kwargs))


class CollectionCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "snapshot.json"

    def run_cli(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(args)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_missing_key_and_invalid_input_do_not_make_requests(self):
        with patch.dict(os.environ, {}, clear=True), patch("commentscope.ingestion.youtube_client.build_opener") as opener:
            for value, expected in [(VIDEO, "MISSING_API_KEY"), ("invalid", "INVALID_VIDEO_INPUT")]:
                status, out, err = self.run_cli(["collect-youtube", value, "--output", str(self.output)])
                self.assertEqual(status, 2)
                self.assertEqual(json.loads(err)["error"]["code"], expected)
                self.assertFalse(self.output.exists())
                self.assertEqual(out, "")
            opener.assert_not_called()

    def test_existing_output_is_rejected_before_key_or_network(self):
        self.output.write_text("keep", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True), patch("commentscope.cli.YouTubeClient") as constructor:
            status, _, err = self.run_cli(["collect-youtube", VIDEO, "--output", str(self.output)])
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(err)["error"]["code"], "OUTPUT_EXISTS")
            constructor.assert_not_called()
        self.assertEqual(self.output.read_text(), "keep")

    def test_prompted_key_and_end_to_end_offline_collection(self):
        opener = FakeOpener([video(), page([thread("a")]), page([thread("a")])])
        with patch("commentscope.cli.getpass.getpass", return_value=TEST_KEY), \
             patch("commentscope.ingestion.youtube_client.build_opener", return_value=opener):
            status, out, err = self.run_cli(["collect-youtube", VIDEO, "--prompt-key", "--output", str(self.output)])
        self.assertEqual(status, 0, err)
        self.assertEqual(json.loads(out)["counts"]["source_count"], 1)
        self.assertEqual(len(load_snapshot(self.output).snapshot.comments), 1)
        self.assertNotIn(TEST_KEY, out + err + self.output.read_text(encoding="utf-8"))

    def test_api_failure_does_not_publish_partial_file(self):
        opener = FakeOpener([video(), page([thread("a")]), http_error(403, "quotaExceeded")])
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": TEST_KEY}), \
             patch("commentscope.ingestion.youtube_client.build_opener", return_value=opener):
            status, out, err = self.run_cli(["collect-youtube", VIDEO, "--output", str(self.output)])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "YOUTUBE_QUOTA_EXCEEDED")
        self.assertEqual(out, "")
        self.assertNotIn(TEST_KEY, err)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
