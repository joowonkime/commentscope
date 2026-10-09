"""Bounded, read-only official YouTube Data API transport."""

import json
import math
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from commentscope.errors import PipelineError

BASE_URL = "https://www.googleapis.com/youtube/v3/"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # An unexpected redirect must not forward the API-key header.
        return None


def api_error(code: str, message: str, *, retryable: bool = False) -> PipelineError:
    return PipelineError(code, "youtube_collection", None, message, retryable)


def _http_error(status: int, body: bytes) -> PipelineError:
    reasons = set()
    try:
        parsed = json.loads(body)
        reasons = {item["reason"] for item in parsed["error"]["errors"] if isinstance(item.get("reason"), str)}
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    if "commentsDisabled" in reasons:
        return api_error("COMMENTS_DISABLED", "comments are disabled for this video")
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg"}:
        return api_error("YOUTUBE_QUOTA_EXCEEDED", "API quota exhausted; check the Cloud console")
    if status == 401 or reasons & {"keyInvalid", "accessNotConfigured", "ipRefererBlocked", "forbiddenForNonOwner"}:
        return api_error("YOUTUBE_AUTH_ERROR", "check API enablement, key validity and key restrictions")
    if status == 404:
        return api_error("YOUTUBE_NOT_FOUND", "video or requested comment is unavailable")
    if status == 429 or status >= 500 or reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
        return api_error("YOUTUBE_UNAVAILABLE", "temporary API failure; retry later", retryable=True)
    return api_error("YOUTUBE_REQUEST_REJECTED", f"API rejected the request (HTTP {status}); check access and parameters")


class YouTubeClient:
    def __init__(self, api_key: str, *, max_requests: int = 100, timeout: float = 20,
                 retries: int = 2, opener=None, sleep=time.sleep):
        if not isinstance(api_key, str) or not api_key.strip():
            raise api_error("MISSING_API_KEY", "set YOUTUBE_API_KEY or use --prompt-key")
        if any(ord(c) < 33 or ord(c) > 126 for c in api_key):
            raise api_error("INVALID_API_KEY", "API key must contain printable ASCII without whitespace")
        if type(max_requests) is not int or max_requests < 1:
            raise api_error("INVALID_COLLECTION_CONFIG", "max_requests must be a positive integer")
        if type(retries) is not int or not 0 <= retries <= 2:
            raise api_error("INVALID_COLLECTION_CONFIG", "retries must be from 0 to 2")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise api_error("INVALID_COLLECTION_CONFIG", "timeout must be finite and between 0 and 60 seconds")
        self._api_key = api_key
        self._opener = opener if opener is not None else build_opener(_NoRedirect())
        self._sleep = sleep
        self.max_requests = max_requests
        self.requests_used = 0
        self.timeout = timeout
        self.retries = retries

    def get(self, resource: str, params: dict) -> dict:
        if resource not in {"videos", "commentThreads", "comments"} or "key" in params:
            raise api_error("INVALID_COLLECTION_CONFIG", "only supported read-only API resources are allowed")
        url = BASE_URL + resource + "?" + urlencode(params)
        request = Request(url, headers={"X-Goog-Api-Key": self._api_key, "Accept": "application/json"})
        for attempt in range(self.retries + 1):
            if self.requests_used >= self.max_requests:
                raise api_error("REQUEST_BUDGET_EXHAUSTED", "configured request budget reached")
            self.requests_used += 1
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise api_error("INVALID_API_RESPONSE", "API response exceeded the size limit")
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (ValueError, RecursionError):
                    raise api_error("INVALID_API_RESPONSE", "API did not return valid UTF-8 JSON") from None
                if not isinstance(parsed, dict) or "error" in parsed:
                    raise api_error("INVALID_API_RESPONSE", "unexpected API response envelope")
                return parsed
            except HTTPError as exc:
                try:
                    body = exc.read(65536)
                except (OSError, HTTPException):
                    body = b""
                finally:
                    exc.close()
                error = _http_error(exc.code, body)
            except (URLError, OSError, HTTPException):
                error = api_error("YOUTUBE_UNAVAILABLE", "network connection failed or timed out", retryable=True)
            if not error.retryable or attempt == self.retries:
                # Do not expose the upstream URL/body, headers or exception text.
                raise error from None
            self._sleep(2 ** attempt)
        raise AssertionError("unreachable")
