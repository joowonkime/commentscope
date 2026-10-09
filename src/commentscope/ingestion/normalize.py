"""Derived text and context-aware duplicate aliases; originals remain unchanged."""

import unicodedata
from dataclasses import dataclass

from commentscope.contracts import DatasetSnapshot

NORMALIZATION_VERSION = "nfc-whitespace-v1"


@dataclass(frozen=True)
class NormalizedComment:
    comment_id: str
    text_analysis: str
    normalization_version: str
    duplicate_of: str | None


def normalize_snapshot(snapshot: DatasetSnapshot) -> tuple[NormalizedComment, ...]:
    texts = {c.comment_id: " ".join(unicodedata.normalize("NFC", c.text_original).split()) for c in snapshot.comments}
    canonical = {}
    for c in snapshot.comments:
        text = texts[c.comment_id]
        if text:
            key = (text, c.parent_id)
            canonical[key] = min(c.comment_id, canonical.get(key, c.comment_id))
    result = []
    for c in snapshot.comments:
        text = texts[c.comment_id]
        representative = canonical.get((text, c.parent_id)) if text else None
        duplicate = representative if representative != c.comment_id else None
        result.append(NormalizedComment(c.comment_id, text, NORMALIZATION_VERSION, duplicate))
    return tuple(result)
