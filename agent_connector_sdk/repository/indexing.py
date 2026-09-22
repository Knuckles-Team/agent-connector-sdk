"""Bounded, one-call repository indexing through the public EG client."""

from __future__ import annotations

from dataclasses import dataclass

from epistemic_graph.client import EpistemicGraphClient
from epistemic_graph.generated.index_repository import IndexResult

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.models import RepositoryBatchLimits, RepositoryFile

__all__ = ["RepositoryBatchReceipt"]


@dataclass(frozen=True)
class RepositoryBatchReceipt:
    """The source paths and unchanged native EG result for one resolution batch."""

    paths: tuple[str, ...]
    result: IndexResult


class _RepositoryBatcher:
    """Accumulate files until one configured engine-call bound is reached."""

    def __init__(self, limits: RepositoryBatchLimits) -> None:
        self.limits = limits
        self.files: list[RepositoryFile] = []
        self.byte_count = 0

    def add(self, item: RepositoryFile) -> tuple[RepositoryFile, ...]:
        """Add a file and return the preceding full batch, if any."""
        size = len(item.content)
        if size > self.limits.max_file_bytes:
            raise RepositoryTransportError(
                f"repository file exceeds limit: {item.path}"
            )
        full = len(self.files) >= self.limits.max_files
        bytes_full = bool(self.files) and self.byte_count + size > self.limits.max_bytes
        ready = self.finish() if full or bytes_full else ()
        self.files.append(item)
        self.byte_count += size
        return ready

    def finish(self) -> tuple[RepositoryFile, ...]:
        """Return and clear the pending batch."""
        ready = tuple(self.files)
        self.files, self.byte_count = [], 0
        return ready


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    if not isinstance(value, str):
        raise RepositoryTransportError("index outcome status is not a string enum")
    return value


def _valid_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    payload = value.removeprefix("sha256:")
    return len(payload) == 64 and all(char in "0123456789abcdef" for char in payload)


def _validate_outcomes(result: IndexResult, files: tuple[RepositoryFile, ...]) -> None:
    try:
        outcomes = result.file_outcomes
    except AttributeError as exc:
        raise RepositoryTransportError(
            "epistemic-graph result lacks typed file_outcomes"
        ) from exc
    if len(outcomes) != len(files):
        raise RepositoryTransportError(
            "epistemic-graph returned incomplete file outcomes"
        )
    for outcome, source in zip(outcomes, files, strict=True):
        if outcome.file_path != source.path:
            raise RepositoryTransportError("epistemic-graph reordered file outcomes")
        if outcome.content_digest != source.blob_digest:
            raise RepositoryTransportError("epistemic-graph outcome digest mismatch")
        if _status_value(outcome.status) not in {
            "success",
            "unsupported",
            "error",
        }:
            raise RepositoryTransportError(
                "epistemic-graph returned unknown parse status"
            )
        if not _valid_digest(outcome.parser_capability_digest):
            raise RepositoryTransportError("parser capability digest is invalid")
        if not isinstance(outcome.diagnostics, list):
            raise RepositoryTransportError("index diagnostics must be a list")


async def submit_repository_batch(
    client: EpistemicGraphClient, files: tuple[RepositoryFile, ...]
) -> RepositoryBatchReceipt:
    """Make the sole high-level EG call for one batch and validate outcomes."""
    payload = [(item.path, item.content) for item in files]
    result = await client.graph.index_repository(payload)
    _validate_outcomes(result, files)
    return RepositoryBatchReceipt(
        paths=tuple(item.path for item in files),
        result=result,
    )
