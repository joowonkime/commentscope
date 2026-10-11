"""Sample a single video's public comments into a validated snapshot."""

import json
import re
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from commentscope.contracts import DatasetSnapshot, parse_snapshot
from commentscope.errors import PipelineError
from .youtube_client import YouTubeClient, api_error

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_COMMENT_FIELDS = "id,snippet(textDisplay,parentId,likeCount,publishedAt)"


def video_id_from_input(value: str) -> str:
    value = value.strip()
    if _VIDEO_ID.fullmatch(value):
        return value
    try:
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or url.username is not None or url.password is not None or url.port is not None:
            raise ValueError
        parts = url.path.strip("/").split("/")
        if url.hostname in {"youtu.be", "www.youtu.be"} and len(parts) == 1:
            candidate = parts[0]
        elif url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if url.path == "/watch":
                values = parse_qs(url.query).get("v", [])
                candidate = values[0] if len(values) == 1 else ""
            elif len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
                candidate = parts[1]
            else:
                candidate = ""
        else:
            candidate = ""
        if _VIDEO_ID.fullmatch(candidate):
            return candidate
    except ValueError:
        pass
    raise api_error("INVALID_VIDEO_INPUT", "provide an 11-character video ID or a supported YouTube video URL")


@dataclass(frozen=True)
class CollectionConfig:
    max_comments: int = 1000
    top_level_limit: int = 400
    replies_per_thread: int = 100
    retention_days: int = 30
    primary_language: str = "und"
    usage_basis: str = "Official API research collection; downstream analysis-use review pending."

    def validate(self):
        for name, low, high in [("max_comments", 1, 9999), ("top_level_limit", 1, 9999),
                                ("replies_per_thread", 0, 9999), ("retention_days", 1, 30)]:
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise api_error("INVALID_COLLECTION_CONFIG", f"{name} must be an integer from {low} to {high}")
        if not isinstance(self.primary_language, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", self.primary_language):
            raise api_error("INVALID_COLLECTION_CONFIG", "primary_language must be a language tag or und")
        if not isinstance(self.usage_basis, str) or not self.usage_basis.strip():
            raise api_error("INVALID_COLLECTION_CONFIG", "usage_basis must be a nonblank description")


@dataclass(frozen=True)
class CollectionResult:
    snapshot: DatasetSnapshot
    report: dict


def _page(payload: dict) -> tuple[list, str | None]:
    items = payload.get("items")
    token = payload.get("nextPageToken")
    if not isinstance(items, list) or (token is not None and (not isinstance(token, str) or not token)):
        raise api_error("INVALID_API_RESPONSE", "missing items array or invalid pagination token")
    return items, token


def _comment(item: dict, video_id: str, parent: str | None, method: str, rank: int) -> dict:
    try:
        cid, snippet = item["id"], item["snippet"]
        if not isinstance(cid, str) or not cid or not isinstance(snippet, dict):
            raise ValueError
        if snippet.get("parentId") != parent:
            raise ValueError
        text = snippet["textDisplay"]
        if not isinstance(text, str):
            raise ValueError
        return {
            "comment_id": cid, "text_original": text,
            "parent_id": parent, "parent_status": "root" if parent is None else "present",
            "replies_status": "unknown", "published_at": snippet["publishedAt"],
            "language": {"tag": "und", "confidence": None, "method": "unknown"},
            "source_url": "https://www.youtube.com/watch?" + urlencode({"v": video_id, "lc": cid}),
            "sampling_origins": [{"method": method, "rank": rank}], "likes": snippet["likeCount"],
        }
    except (KeyError, TypeError, ValueError):
        raise api_error("INVALID_API_RESPONSE", "invalid comment fields or mismatched parent") from None


def collect_youtube(video: str, client: YouTubeClient, config: CollectionConfig | None = None,
                    *, captured_at: datetime | None = None) -> CollectionResult:
    config = config or CollectionConfig()
    config.validate()
    video_id = video_id_from_input(video)
    started = captured_at or datetime.now(timezone.utc)
    if started.tzinfo is None or started.utcoffset() is None:
        raise api_error("INVALID_COLLECTION_CONFIG", "captured_at must have a timezone")
    started = started.astimezone(timezone.utc)
    videos, _ = _page(client.get("videos", {"part": "snippet", "id": video_id, "fields": "items(id,snippet(title))"}))
    if not videos:
        raise api_error("YOUTUBE_NOT_FOUND", "video is unavailable or not accessible with this key")
    try:
        if len(videos) != 1 or videos[0]["id"] != video_id:
            raise ValueError
        title = videos[0]["snippet"]["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise api_error("INVALID_API_RESPONSE", "invalid video metadata") from None

    stop_reasons = set()
    root_budget = min(config.top_level_limit, config.max_comments)
    quotas = {"relevance": (root_budget + 1) // 2, "time": root_budget // 2}
    streams = {"relevance": [], "time": []}

    def request(resource, params):
        try:
            return _page(client.get(resource, params))
        except PipelineError as exc:
            if exc.code != "REQUEST_BUDGET_EXHAUSTED":
                raise
            stop_reasons.add("request_budget")
            return None

    for order, quota in quotas.items():
        token, seen, received = None, set(), 0
        while received < quota:
            params = {
                "part": "snippet", "videoId": video_id, "order": order, "textFormat": "plainText",
                "maxResults": min(100, quota - received),
                "fields": f"nextPageToken,items(snippet(videoId,totalReplyCount,topLevelComment({_COMMENT_FIELDS})))",
            }
            if token:
                params["pageToken"] = token
            page = request("commentThreads", params)
            if page is None:
                break
            items, token = page
            if len(items) > params["maxResults"]:
                raise api_error("INVALID_API_RESPONSE", "thread page exceeds requested size")
            for item in items:
                try:
                    snippet = item["snippet"]
                    total = snippet["totalReplyCount"]
                    if snippet["videoId"] != video_id or type(total) is not int or total < 0:
                        raise ValueError
                    comment = _comment(snippet["topLevelComment"], video_id, None, f"youtube:{order}", received + 1)
                except (KeyError, TypeError, ValueError):
                    raise api_error("INVALID_API_RESPONSE", "invalid thread metadata") from None
                received += 1
                streams[order].append((comment, total))
            if not token:
                break
            if token in seen:
                raise api_error("INVALID_API_RESPONSE", "repeated thread pagination token")
            seen.add(token)
        if token and received >= quota:
            stop_reasons.add(f"{order}_entry_limit")

    # Interleave ranking streams before scheduling replies. First observed text wins.
    comments, totals = {}, {}
    for index in range(max(map(len, streams.values()))):
        for stream in streams.values():
            if index >= len(stream):
                continue
            comment, total = stream[index]
            cid = comment["comment_id"]
            if cid in comments:
                comments[cid]["sampling_origins"].extend(comment["sampling_origins"])
                totals[cid] = max(totals[cid], total)
            else:
                comments[cid], totals[cid] = comment, total
    for cid, total in totals.items():
        comments[cid]["replies_status"] = "complete" if total == 0 else "partial"
    queue = deque(cid for cid in comments if totals[cid] > 0)
    tokens, token_history = {}, {}
    reply_ids = {cid: set() for cid in queue}
    reply_ranks = {cid: 0 for cid in queue}
    while queue and len(comments) < config.max_comments and config.replies_per_thread:
        parent = queue.popleft()
        remaining = config.replies_per_thread - len(reply_ids[parent])
        params = {
            "part": "snippet", "parentId": parent, "textFormat": "plainText",
            "maxResults": min(20, remaining, config.max_comments - len(comments)),
            "fields": f"nextPageToken,items({_COMMENT_FIELDS})",
        }
        if tokens.get(parent):
            params["pageToken"] = tokens[parent]
        page = request("comments", params)
        if page is None:
            queue.appendleft(parent)
            break
        items, token = page
        if len(items) > params["maxResults"]:
            raise api_error("INVALID_API_RESPONSE", "reply page exceeds requested size")
        for item in items:
            reply_ranks[parent] += 1
            comment = _comment(item, video_id, parent, "youtube:reply", reply_ranks[parent])
            cid = comment["comment_id"]
            if cid in comments:
                if comments[cid]["parent_id"] != parent:
                    raise api_error("INVALID_API_RESPONSE", "comment ID reused under another parent")
                comments[cid]["sampling_origins"].extend(comment["sampling_origins"])
            else:
                comments[cid] = comment
            reply_ids[parent].add(cid)
        if not token:
            if len(reply_ids[parent]) >= totals[parent]:
                comments[parent]["replies_status"] = "complete"
            else:
                stop_reasons.add("reply_count_changed_or_unavailable")
        else:
            seen = token_history.setdefault(parent, set())
            if token in seen:
                raise api_error("INVALID_API_RESPONSE", "repeated reply pagination token")
            seen.add(token)
            tokens[parent] = token
            if len(reply_ids[parent]) < config.replies_per_thread:
                queue.append(parent)
            else:
                stop_reasons.add("per_thread_reply_limit")
    if queue:
        if not config.replies_per_thread:
            stop_reasons.add("reply_collection_disabled")
        if len(comments) >= config.max_comments:
            stop_reasons.add("total_comment_limit")

    report = {
        "collector_version": "youtube-api-mixed-v1", "config": asdict(config),
        "request_limit": client.max_requests, "requests_used": client.requests_used,
        "order_entries": {order: len(stream) for order, stream in streams.items()},
        "stop_reasons": sorted(stop_reasons), "target_reached": len(comments) >= config.max_comments,
        "text_source": "snippet.textDisplay requested with textFormat=plainText; not guaranteed author-raw text",
        "notes": "Rank-bounded sample, not population sampling. API pages are not an atomic snapshot. First observed text retained.",
    }
    raw = {
        "schema_version": "0.1", "snapshot_id": f"youtube-{video_id}-{uuid.uuid4().hex}",
        "source_kind": "research", "video": {
            "video_id": video_id, "title": title, "url": f"https://www.youtube.com/watch?v={video_id}",
            "primary_language": config.primary_language,
        },
        "captured_at": started.isoformat().replace("+00:00", "Z"),
        "sampling": {"method": "youtube-api-mixed-v1", "description": json.dumps(report, ensure_ascii=False),
                     "target_count": config.max_comments},
        "usage": {"basis": config.usage_basis,
                  "expires_at": (started + timedelta(days=config.retention_days)).isoformat().replace("+00:00", "Z")},
        "comments": list(comments.values()),
    }
    return CollectionResult(parse_snapshot(raw), report)
