"""Structured errors shared by the library and CLI."""

from dataclasses import asdict, dataclass


@dataclass
class PipelineError(Exception):
    code: str
    stage: str
    entity_id: str | None
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict:
        return asdict(self)
