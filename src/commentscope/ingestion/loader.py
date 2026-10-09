"""Read exact UTF-8 source bytes once and retain their digest."""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from commentscope.contracts import DatasetSnapshot, parse_snapshot
from commentscope.errors import PipelineError


@dataclass(frozen=True)
class LoadedSnapshot:
    snapshot: DatasetSnapshot
    sha256: str


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def load_snapshot(path: str | Path) -> LoadedSnapshot:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise PipelineError("INPUT_READ_ERROR", "ingestion", None, "could not read input file") from exc
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant, parse_float=_float)
    except (ValueError, RecursionError) as exc:
        raise PipelineError("INVALID_SNAPSHOT", "ingestion", None, "invalid UTF-8 JSON, duplicate key or invalid number") from exc
    return LoadedSnapshot(parse_snapshot(value), hashlib.sha256(raw).hexdigest())
