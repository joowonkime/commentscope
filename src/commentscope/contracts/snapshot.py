"""Strict snapshot parsing. No source retrieval or semantic classification."""

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from commentscope.errors import PipelineError

SCHEMA_VERSION = "0.1"
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_LANGUAGE = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*")


@dataclass(frozen=True)
class Video:
    video_id: str
    title: str
    url: str | None
    primary_language: str


@dataclass(frozen=True)
class Sampling:
    method: str
    description: str
    target_count: int | None


@dataclass(frozen=True)
class Usage:
    basis: str
    expires_at: str | None


@dataclass(frozen=True)
class Language:
    tag: str
    confidence: float | None
    method: str


@dataclass(frozen=True)
class SamplingOrigin:
    method: str
    rank: int | None


@dataclass(frozen=True)
class Comment:
    comment_id: str
    text_original: str
    parent_id: str | None
    parent_status: str
    replies_status: str
    published_at: str | None
    language: Language
    source_url: str | None
    sampling_origins: tuple[SamplingOrigin, ...]
    likes: int | None


@dataclass(frozen=True)
class DatasetSnapshot:
    schema_version: str
    snapshot_id: str
    source_kind: str
    video: Video
    captured_at: str
    sampling: Sampling
    usage: Usage
    comments: tuple[Comment, ...]

    def to_dict(self) -> dict:
        """Return a detached JSON-serializable representation."""
        return asdict(self)

    def counts(self) -> dict[str, int]:
        roots = sum(c.parent_status == "root" for c in self.comments)
        return {
            "source_count": len(self.comments),
            "top_level_count": roots,
            "reply_count": len(self.comments) - roots,
            "missing_parent_count": sum(c.parent_status == "missing" for c in self.comments),
        }


def _invalid(path: str, message: str) -> None:
    raise PipelineError("INVALID_SNAPSHOT", "ingestion", None, f"{path}: {message}")


def _object(value: object, fields: str, path: str) -> dict:
    if type(value) is not dict:
        _invalid(path, "expected an object")
    expected = set(fields.split())
    if set(value) != expected:
        _invalid(path, "missing required fields or contains unknown fields")
    return value


def _string(value: object, path: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value.strip()):
        _invalid(path, "expected a nonblank string" if not empty else "expected a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _invalid(path, "contains an invalid Unicode surrogate")
    return value


def _enum(value: object, choices: str, path: str) -> str:
    result = _string(value, path)
    if result not in choices.split():
        _invalid(path, "unknown enum value")
    return result


def _integer(value: object, path: str, minimum: int = 0) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < minimum:
        _invalid(path, f"expected null or an integer >= {minimum}")
    return value


def _timestamp(value: object, path: str, *, nullable: bool = True) -> str | None:
    if value is None and nullable:
        return None
    text = _string(value, path)
    if not _TIMESTAMP.fullmatch(text):
        _invalid(path, "expected YYYY-MM-DDTHH:MM:SS[.ffffff] with Z or a numeric timezone")
    if not text.endswith("Z") and (int(text[-5:-3]) > 23 or int(text[-2:]) > 59):
        _invalid(path, "invalid UTC offset")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        _invalid(path, "invalid calendar date, time or UTC offset")


def _url(value: object, path: str) -> str | None:
    if value is None:
        return None
    text = _string(value, path)
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in text) or "\\" in text:
        _invalid(path, "URL cannot contain whitespace, control characters or backslashes")
    try:
        parsed = urlsplit(text)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            _invalid(path, "expected an HTTPS URL without embedded credentials")
        # Accessing port validates malformed and out-of-range ports.
        _ = parsed.port
    except ValueError:
        _invalid(path, "invalid HTTPS URL")
    return text


def _language_tag(value: object, path: str) -> str:
    text = _string(value, path)
    if not _LANGUAGE.fullmatch(text):
        _invalid(path, "expected a language tag such as ko, en, und or zh-Hant")
    return text


def _language(value: object, path: str) -> Language:
    obj = _object(value, "tag confidence method", path)
    confidence = obj["confidence"]
    if confidence is not None:
        # Bounds first also avoid converting arbitrarily large integers to float.
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1 or not math.isfinite(confidence):
            _invalid(path + ".confidence", "expected null or a finite number from 0 to 1")
        confidence = float(confidence)
    return Language(
        _language_tag(obj["tag"], path + ".tag"), confidence,
        _enum(obj["method"], "provided detected unknown", path + ".method"),
    )


def _comment(value: object, index: int, source_kind: str) -> Comment:
    path = f"$.comments[{index}]"
    obj = _object(value, "comment_id text_original parent_id parent_status replies_status published_at language source_url sampling_origins likes", path)
    parent = obj["parent_id"]
    if parent is not None:
        parent = _string(parent, path + ".parent_id")
    source_url = _url(obj["source_url"], path + ".source_url")
    if source_kind == "synthetic" and source_url is not None:
        _invalid(path + ".source_url", "synthetic comments must not claim a source URL")
    origins = obj["sampling_origins"]
    if type(origins) is not list:
        _invalid(path + ".sampling_origins", "expected an array")
    parsed_origins = []
    for i, origin in enumerate(origins):
        origin_path = f"{path}.sampling_origins[{i}]"
        origin = _object(origin, "method rank", origin_path)
        parsed_origins.append(SamplingOrigin(
            _string(origin["method"], origin_path + ".method"),
            _integer(origin["rank"], origin_path + ".rank", 1),
        ))
    return Comment(
        _string(obj["comment_id"], path + ".comment_id"),
        _string(obj["text_original"], path + ".text_original", empty=True),
        parent,
        _enum(obj["parent_status"], "root present missing", path + ".parent_status"),
        _enum(obj["replies_status"], "complete partial unknown", path + ".replies_status"),
        _timestamp(obj["published_at"], path + ".published_at"),
        _language(obj["language"], path + ".language"),
        source_url, tuple(parsed_origins), _integer(obj["likes"], path + ".likes"),
    )


def _validate_relations(comments: tuple[Comment, ...]) -> None:
    by_id = {}
    for c in comments:
        if c.comment_id in by_id:
            _invalid("$.comments", "duplicate comment ID")
        by_id[c.comment_id] = c

    def bad(c: Comment, message: str) -> None:
        raise PipelineError("INVALID_REFERENCE", "ingestion", c.comment_id, message)

    for c in comments:
        if (c.parent_status == "root") != (c.parent_id is None):
            bad(c, "root status and null parent must agree")
        if c.parent_status == "present" and c.parent_id not in by_id:
            bad(c, "parent marked present does not exist")
        if c.parent_status == "missing" and c.parent_id in by_id:
            bad(c, "parent marked missing exists in the snapshot")
    # Iterative traversal handles long reply chains without Python recursion limits.
    done = set()
    for c in comments:
        chain = set()
        current = c.comment_id
        while current in by_id and current not in done:
            if current in chain:
                bad(by_id[current], "parent graph contains a cycle")
            chain.add(current)
            current = by_id[current].parent_id
        done.update(chain)


def parse_snapshot(value: object) -> DatasetSnapshot:
    """Validate untrusted decoded JSON before constructing immutable contracts."""
    obj = _object(value, "schema_version snapshot_id source_kind video captured_at sampling usage comments", "$")
    version = _string(obj["schema_version"], "$.schema_version")
    if version != SCHEMA_VERSION:
        _invalid("$.schema_version", "unsupported schema version; expected 0.1")
    kind = _enum(obj["source_kind"], "synthetic research", "$.source_kind")
    video = _object(obj["video"], "video_id title url primary_language", "$.video")
    video_url = _url(video["url"], "$.video.url")
    if (kind == "research" and video_url is None) or (kind == "synthetic" and video_url is not None):
        _invalid("$.video.url", "research requires an HTTPS source URL; synthetic requires null")
    sampling = _object(obj["sampling"], "method description target_count", "$.sampling")
    usage = _object(obj["usage"], "basis expires_at", "$.usage")
    if type(obj["comments"]) is not list:
        _invalid("$.comments", "expected an array")
    comments = tuple(_comment(c, i, kind) for i, c in enumerate(obj["comments"]))
    _validate_relations(comments)
    return DatasetSnapshot(
        version, _string(obj["snapshot_id"], "$.snapshot_id"), kind,
        Video(_string(video["video_id"], "$.video.video_id"), _string(video["title"], "$.video.title"),
              video_url, _language_tag(video["primary_language"], "$.video.primary_language")),
        _timestamp(obj["captured_at"], "$.captured_at", nullable=False),
        Sampling(_string(sampling["method"], "$.sampling.method"),
                 _string(sampling["description"], "$.sampling.description"),
                 _integer(sampling["target_count"], "$.sampling.target_count")),
        Usage(_string(usage["basis"], "$.usage.basis"), _timestamp(usage["expires_at"], "$.usage.expires_at")),
        comments,
    )
